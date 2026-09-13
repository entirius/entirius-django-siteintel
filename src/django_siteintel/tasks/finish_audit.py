# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from celery import shared_task

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.services import report_service
from django_siteintel.settings import QUEUE_DEFAULT
from django_siteintel.sources.base import SourceError


@shared_task(name="django_siteintel.finish_audit", queue=QUEUE_DEFAULT, acks_late=True)
def finish_audit(audit_id: str, run_id: str, attempt: int = 0) -> None:
    """Close the run; while a polling report is still running, check again after one poll interval."""
    if not Audit.objects.filter(pk=audit_id, run_id=run_id).exists():
        return  # a rerun replaced this run: its reports belong to the new one
    if report_service.finish(audit_id):
        return
    interval = siteintel_settings.poll_interval_s()
    if attempt * interval <= siteintel_settings.poll_budget_s() + interval:
        finish_audit.apply_async((audit_id, run_id, attempt + 1), countdown=interval)
        return
    # A lost poll task must not keep the audit running forever.
    for report in Report.objects.filter(audit_id=audit_id, status__in=[ReportStatus.PENDING, ReportStatus.RUNNING]):
        report_service.fail(report, SourceError(ErrorCode.TIMEOUT, "report still running after the poll budget"))
    report_service.finish(audit_id)
