# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""One report's lifecycle: run a source, poll a polling source, fail, and finish the audit."""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import (
    FINISHED_REPORT_STATUSES,
    SUCCEEDED_REPORT_STATUSES,
    AuditStatus,
    ErrorCode,
    ReportStatus,
)
from django_siteintel.models import Audit, Report
from django_siteintel.services.cleaning_service import clean_snapshot
from django_siteintel.signals import report_ready
from django_siteintel.sources.base import SourceError
from django_siteintel.sources.registry import get_source


def run(report: Report) -> bool:
    """Fetch the source; True when the report is finished, False when a polling source awaits its result."""
    started = timezone.now()
    _save(report, status=ReportStatus.RUNNING)
    source = get_source(report.source)
    raw = source.fetch_raw(report.audit)
    if source.polls:
        _save(report, raw=raw)
        return False
    complete(report, raw, started)
    return True


def poll(report: Report, uuid: str, deadline: datetime) -> bool:
    """One poll of a polling source; True when the report is finished (result stored or deadline passed)."""
    result = get_source(report.source).fetch_result(report.audit, uuid)
    if result is not None:
        complete(report, {**report.raw, "result": result}, deadline - poll_budget())
        return True
    if timezone.now() < deadline:
        return False
    fail(report, SourceError(ErrorCode.TIMEOUT, f"urlscan result not ready within {poll_budget().seconds} s"))
    return True


def complete(report: Report, raw: dict, started: datetime) -> None:
    source = get_source(report.source)
    source.validate(raw)
    try:
        processed = clean_snapshot(source.process(raw))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # An unexpected payload shape must end the report, never escape the chord header task.
        raise SourceError(ErrorCode.INVALID, f"{report.source}: {type(exc).__name__}") from None
    status = ReportStatus.PARTIAL if raw.get("truncated") else ReportStatus.COMPLETED
    error_code = ErrorCode.TRUNCATED if raw.get("truncated") else ""
    duration = (timezone.now() - started).total_seconds()
    _save(report, status=status, raw=raw, processed=processed, error_code=error_code, duration_s=duration)


def fail(report: Report, error: SourceError, retry_count: int | None = None) -> None:
    fields = {"status": ReportStatus.FAILED, "error_code": error.code, "error_detail": error.detail}
    _save(report, **fields, **({} if retry_count is None else {"retry_count": retry_count}))


def note_retry(report: Report, error: SourceError, retry_count: int) -> None:
    """The report stays running while its task waits for the next upstream attempt."""
    _save(report, retry_count=retry_count, error_code=error.code, error_detail=error.detail)


def finish(audit_id) -> bool:
    """Close the run once every report is finished; sends `report_ready` exactly once. False while running."""
    with transaction.atomic():
        audit = Audit.objects.select_for_update().get(pk=audit_id)
        statuses = dict(audit.reports.values_list("source", "status"))
        if audit.status != AuditStatus.RUNNING or not set(statuses.values()) <= set(FINISHED_REPORT_STATUSES):
            return audit.status != AuditStatus.RUNNING
        succeeded = sorted(source for source, status in statuses.items() if status in SUCCEEDED_REPORT_STATUSES)
        audit.status = _audit_status(len(succeeded), len(statuses))
        audit.save(update_fields=["status", "modified_at"])
    report_ready.send(sender=Audit, audit=audit, succeeded_sources=succeeded)
    return True


def poll_budget() -> timedelta:
    return timedelta(seconds=siteintel_settings.value("SITEINTEL_URLSCAN_POLL_BUDGET_S"))


def _audit_status(succeeded: int, total: int) -> str:
    if succeeded == total:
        return AuditStatus.COMPLETED
    return AuditStatus.PARTIALLY_COMPLETED if succeeded else AuditStatus.FAILED


def _save(report: Report, **fields) -> None:
    for name, value in fields.items():
        setattr(report, name, value)
    report.save(update_fields=[*fields, "modified_at"])
