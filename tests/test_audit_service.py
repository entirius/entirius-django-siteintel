# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from datetime import timedelta

import pytest
from django.utils import timezone

from django_siteintel.enums import AuditStatus, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.services import audit_service
from django_siteintel.signals import report_ready
from tests.conftest import CHANNEL_IDX, DOMAIN


@pytest.fixture
def signals():
    received = []

    def receiver(sender, audit, succeeded_sources, **kwargs):
        received.append((audit.pk, succeeded_sources))

    report_ready.connect(receiver)
    yield received
    report_ready.disconnect(receiver)


def _request(domain: str = DOMAIN) -> Audit:
    return audit_service.request_audit(domain_or_url=domain, channel_idx=CHANNEL_IDX, requested_by="leads.Company:1")


def test_new_audit_has_one_pending_report_per_source_and_queues_a_run(
    db, recordings, django_capture_on_commit_callbacks, monkeypatch
):
    queued = []
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", queued.append)
    with django_capture_on_commit_callbacks(execute=True):
        audit = _request(f"https://www.{DOMAIN}/pl")

    assert (audit.domain, audit.status) == (DOMAIN, AuditStatus.PENDING)
    assert sorted(audit.reports.values_list("source", "status")) == [
        ("heuristic", "pending"),
        ("lighthouse", "pending"),
        ("urlscan", "pending"),
    ]
    assert queued == [str(audit.pk)]


def test_S01_valid_audit_reused_no_fetch_signal_immediate(db, recordings, signals, monkeypatch):
    first = audit_service.run_now(_request())
    assert first.status == AuditStatus.COMPLETED
    assert signals == [(first.pk, ["heuristic", "lighthouse", "urlscan"])]
    calls, queued = len(recordings.calls), []
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", queued.append)

    again = _request(f"http://{DOMAIN}/other")

    assert again.pk == first.pk
    assert len(recordings.calls) == calls and queued == []
    assert signals[-1] == (first.pk, ["heuristic", "lighthouse", "urlscan"]) and len(signals) == 2


def test_S02_expired_audit_marked_new_created_history_kept(db, recordings):
    old = audit_service.run_now(_request())
    Audit.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    assert audit_service.expire_audits() == 1
    new = _request()

    old.refresh_from_db()
    assert old.status == AuditStatus.EXPIRED and new.pk != old.pk
    assert Audit.objects.filter(domain=DOMAIN).count() == 2
    assert Report.objects.filter(audit=old, status=ReportStatus.COMPLETED).count() == 3


def test_expire_audits_with_shifted_clock_leaves_fresh_ones_alone(db, recordings):
    audit_service.run_now(_request())
    assert audit_service.expire_audits(now=timezone.now()) == 0
    assert audit_service.expire_audits(now=timezone.now() + timedelta(days=91)) == 1


def test_S09_rerun_resets_reports_same_audit_id(
    db, recordings, signals, django_capture_on_commit_callbacks, monkeypatch
):
    audit = audit_service.run_now(_request())
    Audit.objects.filter(pk=audit.pk).update(expires_at=timezone.now())
    queued = []
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", queued.append)

    with django_capture_on_commit_callbacks(execute=True):
        rerun = audit_service.rerun_audit(audit=audit, requested_by="cms:admin")

    assert rerun.pk == audit.pk and rerun.status == AuditStatus.PENDING
    assert rerun.expires_at > timezone.now() + timedelta(days=89)
    assert list(rerun.reports.values_list("status", "raw", "processed", "retry_count")) == [("pending", {}, {}, 0)] * 3
    assert queued == [str(audit.pk)] and len(signals) == 1
    assert audit_service.run_now(rerun).status == AuditStatus.COMPLETED and len(signals) == 2
