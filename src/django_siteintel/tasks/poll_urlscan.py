# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime

from celery import shared_task

from django_siteintel import settings as siteintel_settings
from django_siteintel.models import Report
from django_siteintel.services import report_service
from django_siteintel.settings import QUEUE_DEFAULT
from django_siteintel.sources.base import SourceError


@shared_task(name="django_siteintel.poll_urlscan", queue=QUEUE_DEFAULT, acks_late=True)
def poll_urlscan(report_id: int, uuid: str, deadline_iso: str) -> None:
    """One poll; re-dispatched with a countdown while the result is not ready — never sleeps (S-04)."""
    report = Report.objects.select_related("audit").get(pk=report_id)
    try:
        finished = report_service.poll(report, uuid, datetime.fromisoformat(deadline_iso))
    except SourceError as error:
        report_service.fail(report, error)
        return
    if not finished:
        countdown = siteintel_settings.value("SITEINTEL_URLSCAN_POLL_INTERVAL_S")
        poll_urlscan.apply_async((report_id, uuid, deadline_iso), countdown=countdown)
