# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class AuditStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    PARTIALLY_COMPLETED = "partially_completed", "Partially completed"
    FAILED = "failed", "Failed"
    EXPIRED = "expired", "Expired"


REUSABLE_AUDIT_STATUSES = (AuditStatus.COMPLETED, AuditStatus.PARTIALLY_COMPLETED)


class ReportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


SUCCEEDED_REPORT_STATUSES = (ReportStatus.COMPLETED, ReportStatus.PARTIAL)
FINISHED_REPORT_STATUSES = (*SUCCEEDED_REPORT_STATUSES, ReportStatus.FAILED)


class ErrorCode(models.TextChoices):
    SSRF = "ssrf", "Refused by the SSRF guard"
    TIMEOUT = "timeout", "Timed out"
    UPSTREAM = "upstream", "Upstream error"
    TRUNCATED = "truncated", "Body over the byte cap"
    INVALID = "invalid", "Invalid or oversized payload"
    RECORDING_MISSING = "recording_missing", "No recording for the domain"
    INTERNAL = "internal", "Unexpected error"
