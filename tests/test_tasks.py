# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from datetime import timedelta

import pytest
from django.utils import timezone

from django_siteintel.enums import AuditStatus, ErrorCode, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.services import audit_service
from django_siteintel.signals import report_ready
from django_siteintel.tasks import poll_urlscan, run_audit
from tests.conftest import CHANNEL_IDX, DOMAIN, PSI
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
    dispatched = []
    monkeypatch.setattr(poll_urlscan, "apply_async", lambda args, countdown: dispatched.append((args, countdown)))

    future = (timezone.now() + timedelta(seconds=60)).isoformat()
    poll_urlscan(report.pk, "u", future)  # result 404, before the deadline → re-dispatched with a countdown
    assert dispatched == [((report.pk, "u", future), 10)]

    poll_urlscan(report.pk, "u", (timezone.now() - timedelta(seconds=1)).isoformat())
    report.refresh_from_db()
    assert (report.status, report.error_code) == (ReportStatus.FAILED, ErrorCode.TIMEOUT)
    assert len(dispatched) == 1
    assert Report.objects.get(pk=other.pk).status == ReportStatus.COMPLETED


def test_run_audit_task_name_and_queue():
    assert (run_audit.name, run_audit.queue) == ("django_siteintel.run_audit", "siteintel_default")


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
