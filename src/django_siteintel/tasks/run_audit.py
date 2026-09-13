# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from celery import chord, shared_task
from django.utils import timezone

from django_siteintel.enums import AuditStatus
from django_siteintel.models import Audit
from django_siteintel.settings import QUEUE_DEFAULT
from django_siteintel.tasks.finish_audit import finish_audit
from django_siteintel.tasks.run_source import run_source


@shared_task(name="django_siteintel.run_audit", queue=QUEUE_DEFAULT, acks_late=True)
def run_audit(audit_id: str) -> None:
    """Mark the audit running and fan out one `run_source` per report; `finish_audit` closes the run."""
    Audit.objects.filter(pk=audit_id).update(status=AuditStatus.RUNNING, modified_at=timezone.now())
    sources = Audit.objects.get(pk=audit_id).reports.values_list("source", flat=True)
    chord(run_source.si(audit_id, source) for source in sources)(finish_audit.si(audit_id))
