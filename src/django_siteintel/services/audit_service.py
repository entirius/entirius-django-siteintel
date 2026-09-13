# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The public API of the module: request, rerun, expire and (development) run an audit synchronously."""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import REUSABLE_AUDIT_STATUSES, SUCCEEDED_REPORT_STATUSES, AuditStatus, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.services import report_service
from django_siteintel.signals import report_ready
from django_siteintel.sources.base import SourceError
from django_siteintel.sources.registry import list_sources
from django_siteintel.utils.domains import normalise_domain


def request_audit(*, domain_or_url: str, channel_idx: str, requested_by: str) -> Audit:
    """The valid audit of the domain (S-01, `report_ready` sent at once), else a new pending one with a run queued."""
    domain, url = normalise_domain(domain_or_url)
    reusable = find_valid_audit(domain)
    if reusable is not None:
        succeeded = list(reusable.reports.filter(status__in=SUCCEEDED_REPORT_STATUSES).values_list("source", flat=True))
        report_ready.send(sender=Audit, audit=reusable, succeeded_sources=sorted(succeeded))
        return reusable
    with transaction.atomic():
        audit = Audit.objects.create(
            domain=domain, url=url, channel_idx=channel_idx, requested_by=requested_by, expires_at=_expiry()
        )
        Report.objects.bulk_create([Report(audit=audit, source=source) for source in list_sources()])
        _dispatch_run(audit)
    return audit


def find_valid_audit(domain: str) -> Audit | None:
    valid = Audit.objects.filter(domain=domain, status__in=REUSABLE_AUDIT_STATUSES, expires_at__gt=timezone.now())
    return valid.order_by("-created_at").first()


def rerun_audit(*, audit: Audit, requested_by: str) -> Audit:
    """Same audit row, reports reset to pending, expiry extended, run queued (S-09)."""
    with transaction.atomic():
        audit.reports.update(
            status=ReportStatus.PENDING, raw={}, processed={}, retry_count=0, duration_s=None, error_code="",
            error_detail="", modified_at=timezone.now(),
        )  # fmt: skip
        audit.status, audit.requested_by, audit.expires_at = AuditStatus.PENDING, requested_by, _expiry()
        audit.save(update_fields=["status", "requested_by", "expires_at", "modified_at"])
        _dispatch_run(audit)
    return audit


def expire_audits(now: datetime | None = None) -> int:
    """Valid audits past `expires_at` become `expired`; rows and reports are kept as history (S-02)."""
    due = Audit.objects.filter(status__in=REUSABLE_AUDIT_STATUSES, expires_at__lte=now or timezone.now())
    return due.update(status=AuditStatus.EXPIRED, modified_at=timezone.now())


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
