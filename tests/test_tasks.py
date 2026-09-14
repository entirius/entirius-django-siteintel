# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import sys
from datetime import timedelta

import pytest
from django.utils import timezone

from django_siteintel.enums import AuditStatus, ErrorCode, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.services import audit_service
from django_siteintel.signals import report_ready
from django_siteintel.tasks import finish_audit, poll_urlscan, run_audit, run_source, sweep_stuck_audits
from tests.conftest import CHANNEL_IDX, DOMAIN, GOOD_HTML, PSI, URLSCAN, urlscan_result
from tests.fake_http import FakeResponse


def _audit() -> Audit:
    with_reports = audit_service.request_audit
    return with_reports(domain_or_url=DOMAIN, channel_idx=CHANNEL_IDX, requested_by="t")


@pytest.fixture
def signals():
    received = []
    handler = lambda sender, audit, succeeded_sources, **kw: received.append(succeeded_sources)  # noqa: E731
    report_ready.connect(handler)
    yield received
    report_ready.disconnect(handler)


@pytest.mark.django_db(transaction=True)
def test_S03_psi_upstream_retries_then_partially_completed_signal_lists_succeeded(recordings, eager_celery, signals):
    recordings.add(f"{PSI}/{DOMAIN}.desktop.json", FakeResponse(503))
    audit = _audit()  # on_commit fires: the whole chord runs eagerly

    audit.refresh_from_db()
    lighthouse = Report.objects.get(audit=audit, source="lighthouse")
    assert audit.status == AuditStatus.PARTIALLY_COMPLETED
    assert (lighthouse.status, lighthouse.error_code, lighthouse.retry_count) == ("failed", "upstream", 3)
    assert sum(url.endswith(".desktop.json") for url in recordings.calls) == 4
    assert signals == [["heuristic", "urlscan"]]


@pytest.mark.django_db(transaction=True)
def test_ssrf_fails_at_once_without_retry(http, eager_celery, signals, settings):
    settings.SITEINTEL_ALLOWED_HOSTS = []
    settings.SITEINTEL_PSI_BASE_URL = "http://127.0.0.1/psi"
    settings.SITEINTEL_URLSCAN_BASE_URL = "http://127.0.0.1/urlscan"
    audit = _audit()

    reports = {r.source: (r.status, r.error_code, r.retry_count) for r in Report.objects.filter(audit=audit)}
    assert reports["lighthouse"] == ("failed", "ssrf", 0) and reports["urlscan"] == ("failed", "ssrf", 0)
    assert Audit.objects.get(pk=audit.pk).status == AuditStatus.FAILED
    assert http.calls == [] and signals == [[]]


def test_S04_urlscan_poll_deadline_fails_timeout_no_sleep(db, http, monkeypatch):
    audit = Audit.objects.create(
        domain=DOMAIN, url=f"https://{DOMAIN}", channel_idx="c", requested_by="t", expires_at=timezone.now()
    )
    report = Report.objects.create(
        audit=audit, source="urlscan", status=ReportStatus.RUNNING, raw={"submit": {"uuid": "u"}}
    )
    other = Report.objects.create(audit=audit, source="heuristic", status=ReportStatus.COMPLETED)
    dispatched, run_id = [], str(audit.run_id)
    monkeypatch.setattr(poll_urlscan, "apply_async", lambda args, countdown: dispatched.append((args, countdown)))

    future = (timezone.now() + timedelta(seconds=60)).isoformat()
    poll_urlscan(report.pk, "u", future, run_id)  # result 404, before the deadline → re-dispatched with a countdown
    assert dispatched == [((report.pk, "u", future, run_id), 10)]

    poll_urlscan(report.pk, "u", (timezone.now() - timedelta(seconds=1)).isoformat(), run_id)
    report.refresh_from_db()
    assert (report.status, report.error_code) == (ReportStatus.FAILED, ErrorCode.TIMEOUT)
    assert len(dispatched) == 1
    assert Report.objects.get(pk=other.pk).status == ReportStatus.COMPLETED


def test_run_audit_task_name_and_queue():
    assert (run_audit.name, run_audit.queue) == ("django_siteintel.run_audit", "siteintel_default")


def test_late_worker_run_never_reopens_an_audit_finished_by_run_now(db, recordings, monkeypatch):
    audit = audit_service.run_now(_audit())  # `db` never fires on_commit: the worker run arrives only below
    chords = []
    monkeypatch.setattr(sys.modules["django_siteintel.tasks.run_audit"], "chord", chords.append)
    calls_before = len(recordings.calls)

    run_audit(str(audit.pk))
    for source in ("heuristic", "lighthouse", "urlscan"):
        run_source(str(audit.pk), source, str(audit.run_id))

    assert chords == [] and len(recordings.calls) == calls_before
    assert Audit.objects.get(pk=audit.pk).status == AuditStatus.COMPLETED
    assert set(Report.objects.filter(audit=audit).values_list("status", flat=True)) == {ReportStatus.COMPLETED}


def test_unexpected_payload_shape_fails_invalid_instead_of_raising(db, recordings):
    recordings.add(
        f"{PSI}/{DOMAIN}.desktop.json", FakeResponse(200, {"lighthouseResult": {"categories": ["not", "a", "dict"]}})
    )
    audit = audit_service.run_now(_audit())

    lighthouse = Report.objects.get(audit=audit, source="lighthouse")
    assert (lighthouse.status, lighthouse.error_code, lighthouse.error_detail) == (
        "failed",
        "invalid",
        "lighthouse: AttributeError",
    )
    assert audit.status == AuditStatus.PARTIALLY_COMPLETED


def test_sweep_stuck_audits_task_name_and_queue():
    assert (sweep_stuck_audits.name, sweep_stuck_audits.queue) == (
        "django_siteintel.sweep_stuck_audits",
        "siteintel_default",
    )


def test_run_source_unexpected_error_fails_report(db, recordings, monkeypatch):
    audit = _audit()

    def explode(report):
        raise RuntimeError("boom with details that must not be stored")

    monkeypatch.setattr("django_siteintel.services.report_service.run", explode)
    run_source(str(audit.pk), "heuristic", str(audit.run_id))  # returns normally: the chord still reaches finish_audit

    report = Report.objects.get(audit=audit, source="heuristic")
    assert (report.status, report.error_code, report.error_detail) == ("failed", "internal", "RuntimeError")


def test_nul_characters_stripped_before_save(db, recordings):
    result = urlscan_result()
    result["page"]["title"] = "Sh\x00op"
    recordings.add(f"{URLSCAN}/{DOMAIN}.result.json", FakeResponse(200, {**result, "con\x00sole": ["x\x00"]}))
    recordings.add(f"https://{DOMAIN}", FakeResponse(200, GOOD_HTML.replace(b"<title>Good", b"<title>Go\x00od")))

    audit = audit_service.run_now(_audit())

    urlscan = Report.objects.get(audit=audit, source="urlscan")
    assert audit.status == AuditStatus.COMPLETED
    assert urlscan.raw["result"]["page"]["title"] == "Shop" and urlscan.raw["result"]["console"] == ["x"]
    assert "\x00" not in str(Report.objects.get(audit=audit, source="heuristic").processed)


def test_stale_poll_ignored_after_rerun(db, recordings, monkeypatch):
    audit = audit_service.run_now(_audit())
    old_run_id = str(audit.run_id)
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    audit_service.rerun_audit(audit=audit, requested_by="cms:admin")
    Audit.objects.filter(pk=audit.pk).update(status=AuditStatus.RUNNING)  # the new run has started
    dispatched = []
    monkeypatch.setattr(finish_audit, "apply_async", lambda args, countdown: dispatched.append(args))
    calls_before = len(recordings.calls)

    urlscan = Report.objects.get(audit=audit, source="urlscan")
    poll_urlscan(urlscan.pk, "u-1", (timezone.now() + timedelta(seconds=60)).isoformat(), old_run_id)
    finish_audit(str(audit.pk), old_run_id, attempt=100)  # the old loop past its budget would fail every report

    assert len(recordings.calls) == calls_before and dispatched == []
    assert set(Report.objects.filter(audit=audit).values_list("status", flat=True)) == {ReportStatus.PENDING}
    assert Audit.objects.get(pk=audit.pk).status == AuditStatus.RUNNING


def test_stale_run_source_ignored_after_rerun(db, recordings, monkeypatch):
    audit = audit_service.run_now(_audit())
    old_run_id = str(audit.run_id)
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    audit_service.rerun_audit(audit=audit, requested_by="cms:admin")
    Audit.objects.filter(pk=audit.pk).update(status=AuditStatus.RUNNING)  # the new run has started
    calls_before = len(recordings.calls)

    for source in ("heuristic", "lighthouse", "urlscan"):
        run_source(str(audit.pk), source, old_run_id)  # e.g. an upstream retry of the old run after its countdown
        run_source(str(audit.pk), source)  # a message queued before `run_id` was part of the signature

    assert len(recordings.calls) == calls_before
    reports = Report.objects.filter(audit=audit).values_list("status", "raw", "retry_count", "error_code")
    assert list(reports) == [(ReportStatus.PENDING, {}, 0, "")] * 3
    assert Audit.objects.get(pk=audit.pk).status == AuditStatus.RUNNING


def test_zero_poll_interval_does_not_loop(db, recordings, monkeypatch, settings, caplog):
    settings.SITEINTEL_URLSCAN_POLL_INTERVAL_S = 0
    settings.SITEINTEL_URLSCAN_POLL_BUDGET_S = 0
    audit = _audit()
    Audit.objects.filter(pk=audit.pk).update(status=AuditStatus.RUNNING)
    Report.objects.filter(audit=audit).update(status=ReportStatus.RUNNING)
    queue, countdowns = [(str(audit.pk), str(audit.run_id), 0)], []

    def requeue(args, countdown):
        countdowns.append(countdown)
        queue.append(args)

    monkeypatch.setattr(finish_audit, "apply_async", requeue)
    while queue and len(countdowns) < 100:
        finish_audit(*queue.pop())

    assert countdowns == [1, 1, 1]
    assert Audit.objects.get(pk=audit.pk).status == AuditStatus.FAILED
    assert "SITEINTEL_URLSCAN_POLL_INTERVAL_S=0" in caplog.text
