# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The public API of the module: request, rerun, expire and (development) run an audit synchronously."""

import uuid
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import (
    FINISHED_REPORT_STATUSES,
    IN_FLIGHT_AUDIT_STATUSES,
    REUSABLE_AUDIT_STATUSES,
    SUCCEEDED_REPORT_STATUSES,
    AuditStatus,
    ErrorCode,
    ReportStatus,
)
from django_siteintel.models import Audit, Report
from django_siteintel.services import report_service
from django_siteintel.signals import report_ready
from django_siteintel.sources.base import SourceError
from django_siteintel.sources.registry import list_sources
from django_siteintel.utils.domains import normalise_domain


def request_audit(*, domain_or_url: str, channel_idx: str, requested_by: str) -> Audit:
    """The valid audit of the domain (S-01, `report_ready` sent at once), else a new pending one with a run queued."""
    domain, url = normalise_domain(domain_or_url)
    reusable = find_valid_audit(domain, channel_idx)
    if reusable is not None:
        succeeded = list(reusable.reports.filter(status__in=SUCCEEDED_REPORT_STATUSES).values_list("source", flat=True))
        report_ready.send(sender=Audit, audit=reusable, succeeded_sources=sorted(succeeded))
        return reusable
    try:
        with transaction.atomic():
            audit = Audit.objects.create(
                domain=domain, url=url, channel_idx=channel_idx, requested_by=requested_by, expires_at=_expiry()
            )
            Report.objects.bulk_create([Report(audit=audit, source=source) for source in list_sources()])
            _dispatch_run(audit)
    except IntegrityError:
        return _find_race_winner(domain, channel_idx)  # a concurrent request won the race (item 7)
    return audit


def _find_race_winner(domain: str, channel_idx: str) -> Audit:
    """The in-flight audit; if the winner already finished, the valid one, else the newest (never None)."""
    audits = Audit.objects.filter(domain=domain, channel_idx=channel_idx).order_by("-created_at")
    in_flight = audits.filter(status__in=IN_FLIGHT_AUDIT_STATUSES).first()
    return in_flight or find_valid_audit(domain, channel_idx) or audits.first()


def find_valid_audit(domain: str, channel_idx: str) -> Audit | None:
    """Reuse is channel-scoped: another channel's audit of the same domain is never returned."""
    valid = Audit.objects.filter(
        domain=domain, channel_idx=channel_idx, status__in=REUSABLE_AUDIT_STATUSES, expires_at__gt=timezone.now()
    )
    return valid.order_by("-created_at").first()


class AuditRunningError(Exception):
    """A rerun was requested while the audit's current run is still in progress."""


class AuditInFlightError(Exception):
    """A rerun was requested while another audit of the same domain and channel is pending or running."""


def rerun_audit(*, audit: Audit, requested_by: str) -> Audit:
    """Same audit row, reports reset to pending, expiry extended, a new run queued (S-09); refused while running."""
    try:
        _reset_for_rerun(audit, requested_by)
    except IntegrityError:
        raise AuditInFlightError(str(audit.pk)) from None  # the one-in-flight constraint (item 1)
    audit.refresh_from_db()
    return audit


def _reset_for_rerun(audit: Audit, requested_by: str) -> None:
    fields = {
        "status": AuditStatus.PENDING,
        "requested_by": requested_by,
        "expires_at": _expiry(),
        "run_id": uuid.uuid4(),
        "modified_at": timezone.now(),
    }
    with transaction.atomic():
        if not Audit.objects.filter(pk=audit.pk).exclude(status=AuditStatus.RUNNING).update(**fields):
            raise AuditRunningError(str(audit.pk))  # the caller's instance is left untouched
        audit.reports.update(
            status=ReportStatus.PENDING, raw={}, processed={}, retry_count=0, duration_s=None, error_code="",
            error_detail="", modified_at=timezone.now(),
        )  # fmt: skip
        _dispatch_run(audit)


def expire_audits(now: datetime | None = None) -> int:
    """Valid audits past `expires_at` become `expired`; rows and reports are kept as history (S-02)."""
    due = Audit.objects.filter(status__in=REUSABLE_AUDIT_STATUSES, expires_at__lte=now or timezone.now())
    return due.update(status=AuditStatus.EXPIRED, modified_at=timezone.now())


def fail_stuck_audits(now: datetime | None = None) -> int:
    """Audits `pending`/`running` longer than `SITEINTEL_AUDIT_STUCK_MINUTES` fail, with their unfinished reports."""
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=siteintel_settings.value("SITEINTEL_AUDIT_STUCK_MINUTES"))
    stuck = Audit.objects.filter(status__in=IN_FLIGHT_AUDIT_STATUSES, modified_at__lt=cutoff).values_list(
        "pk", flat=True
    )
    return sum(_fail_stuck_audit(audit_id, cutoff, now) for audit_id in list(stuck))


def _fail_stuck_audit(audit_id, cutoff: datetime, now: datetime) -> bool:
    """Like `report_service.finish`: the locked row is re-checked, `report_ready` is sent once after the commit."""
    with transaction.atomic():
        audit = Audit.objects.select_for_update().get(pk=audit_id)
        if audit.status not in IN_FLIGHT_AUDIT_STATUSES or audit.modified_at >= cutoff:
            return False  # finished or rerun since the scan
        unfinished = audit.reports.exclude(status__in=FINISHED_REPORT_STATUSES)
        unfinished.update(
            status=ReportStatus.FAILED,
            error_code=ErrorCode.TIMEOUT,
            error_detail=f"audit stuck {audit.status}",
            modified_at=now,
        )
        succeeded = sorted(audit.reports.filter(status__in=SUCCEEDED_REPORT_STATUSES).values_list("source", flat=True))
        audit.status = AuditStatus.FAILED
        audit.save(update_fields=["status", "modified_at"])
        transaction.on_commit(lambda: report_ready.send(sender=Audit, audit=audit, succeeded_sources=succeeded))
    return True


def run_now(audit: Audit) -> Audit:
    """Development only: every source inline (a polling source gets one immediate poll), then finish."""
    Audit.objects.filter(pk=audit.pk).update(status=AuditStatus.RUNNING, modified_at=timezone.now())
    for report in audit.reports.select_related("audit"):
        _run_inline(report)
    report_service.finish(audit.pk)
    audit.refresh_from_db()
    return audit


def _run_inline(report: Report) -> None:
    try:
        if not report_service.run(report):
            uuid = report.raw["submit"]["uuid"]
            report_service.poll(report, uuid, deadline=timezone.now())
    except SourceError as error:
        report_service.fail(report, error)


def _dispatch_run(audit: Audit) -> None:
    from django_siteintel.tasks import run_audit

    audit_id = str(audit.pk)
    transaction.on_commit(lambda: run_audit.delay(audit_id))


def _expiry() -> datetime:
    return timezone.now() + timedelta(days=siteintel_settings.value("SITEINTEL_EXPIRE_DAYS"))
