# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from celery import shared_task
from celery.utils.time import get_exponential_backoff_interval
from django.utils import timezone

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode
from django_siteintel.models import Report
from django_siteintel.services import report_service
from django_siteintel.settings import QUEUE_DEFAULT
from django_siteintel.sources.base import SourceError
from django_siteintel.tasks.poll_urlscan import poll_urlscan

MAX_RETRIES = 3
BACKOFF_MAX_S = 600


# Retries only for `upstream` (S-03); `ssrf`, `timeout`, `invalid` fail at once. The task never raises past the
# retries — an exception would break the chord and `finish_audit` would never run.
@shared_task(
    bind=True, name="django_siteintel.run_source", queue=QUEUE_DEFAULT, acks_late=True, max_retries=MAX_RETRIES
)
def run_source(self, audit_id: str, source: str) -> None:
    report = Report.objects.select_related("audit").get(audit_id=audit_id, source=source)
    try:
        if not report_service.run(report):
            _schedule_poll(report)
    except SourceError as error:
        retries = self.request.retries
        if error.code != ErrorCode.UPSTREAM or retries >= MAX_RETRIES:
            report_service.fail(report, error, retry_count=retries)
            return
        report_service.note_retry(report, error, retries + 1)
        raise self.retry(countdown=get_exponential_backoff_interval(1, retries, BACKOFF_MAX_S, True)) from None


def _schedule_poll(report: Report) -> None:
    deadline = timezone.now() + report_service.poll_budget()
    args = (report.pk, report.raw["submit"]["uuid"], deadline.isoformat())
    poll_urlscan.apply_async(args, countdown=siteintel_settings.value("SITEINTEL_URLSCAN_POLL_INTERVAL_S"))
