# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from celery import shared_task

from django_siteintel.services import audit_service
from django_siteintel.settings import QUEUE_DEFAULT


@shared_task(name="django_siteintel.expire_audits", queue=QUEUE_DEFAULT, acks_late=True)
def expire_audits() -> int:
    return audit_service.expire_audits()
