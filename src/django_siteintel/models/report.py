# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_utils.models.base_model import BaseModel

from django_siteintel.enums import ErrorCode, ReportStatus


class Report(BaseModel):
    """One source's result for an audit. `raw` stays server-side; `processed` is the consumer payload."""

    audit = models.ForeignKey("django_siteintel.Audit", on_delete=models.CASCADE, related_name="reports")
    source = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=ReportStatus.choices, default=ReportStatus.PENDING)
    raw = models.JSONField(default=dict, blank=True)
    processed = models.JSONField(default=dict, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    duration_s = models.FloatField(null=True, blank=True)
    error_code = models.CharField(max_length=32, choices=ErrorCode.choices, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["audit", "source"], name="siteintel_report_audit_source")]

    def __str__(self) -> str:
        return f"{self.source} ({self.status})"
