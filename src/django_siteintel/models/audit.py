# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import uuid

from django.db import models
from django_utils.models.base_model import BaseModel

from django_siteintel.enums import IN_FLIGHT_AUDIT_STATUSES, AuditStatus


class Audit(BaseModel):
    """One audit run of a registrable domain; reused by every requester while valid."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=253, db_index=True)
    url = models.URLField(max_length=2048)
    channel_idx = models.CharField(max_length=128)
    status = models.CharField(max_length=32, choices=AuditStatus.choices, default=AuditStatus.PENDING)
    requested_by = models.CharField(max_length=200)
    expires_at = models.DateTimeField()
    # A new value per run: tasks of a previous run carry the old one and no-op.
    run_id = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        indexes = [models.Index(fields=["domain", "status"], name="siteintel_audit_domain_status")]
        constraints = [
            # Concurrent first requests for one domain must not create two audits (item 7): only one
            # pending/running row per (domain, channel) at a time; finished/expired rows are unrestricted.
            models.UniqueConstraint(
                fields=["domain", "channel_idx"],
                condition=models.Q(status__in=IN_FLIGHT_AUDIT_STATUSES),
                name="siteintel_audit_one_in_flight_per_domain_channel",
            )
        ]

    def __str__(self) -> str:
        return f"{self.domain} ({self.status})"
