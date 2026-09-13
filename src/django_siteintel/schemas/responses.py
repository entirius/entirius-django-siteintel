# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Response schemas of the siteintel admin API v2. `Report.raw` and API keys are never exposed."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str = Field(description="Source name (entry point).", examples=["heuristic"])
    status: str = Field(description="pending, running, completed, partial or failed.", examples=["completed"])
    processed: dict = Field(description="Cleaned snapshot, bounded in size.", examples=[{"images_without_alt": 0}])
    retry_count: int = Field(description="Upstream retries made.", examples=[0])
    duration_s: float | None = Field(description="Fetch-to-result seconds.", examples=[1.4])
    error_code: str = Field(
        description="ssrf, timeout, upstream, truncated, invalid or recording_missing.", examples=[""]
    )
    error_detail: str = Field(description="Host and error class of the failure.", examples=[""])
    modified_at: datetime = Field(description="Last change of the report.", examples=["2026-09-13T12:00:00Z"])


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Audit id.", examples=["6f1c1e2a-8a53-4a55-9a8f-0d6c1f7d9b10"])
    domain: str = Field(description="Registrable domain the audit is keyed by.", examples=["shop.example"])
    url: str = Field(description="Audited URL as requested.", examples=["https://www.shop.example/pl"])
    channel_idx: str = Field(description="Channel of the first requester.", examples=["default-europe"])
    status: str = Field(
        description="pending, running, completed, partially_completed, failed or expired.", examples=["completed"]
    )
    requested_by: str = Field(description="Subject reference of the requester.", examples=["leads.Company:42"])
    expires_at: datetime = Field(description="Reused until this moment.", examples=["2026-12-12T12:00:00Z"])
    created_at: datetime = Field(description="When the audit was requested.", examples=["2026-09-13T12:00:00Z"])
    modified_at: datetime = Field(description="Last change of the audit.", examples=["2026-09-13T12:00:05Z"])


class AuditDetailResponse(AuditResponse):
    reports: list[ReportResponse] = Field(description="One report per source.", examples=[[]])


class AuditListResponse(BaseModel):
    count: int = Field(description="Total matching audits.", examples=[1])
    next: str | None = Field(description="Next page URL.", examples=[None])
    previous: str | None = Field(description="Previous page URL.", examples=[None])
    results: list[AuditResponse] = Field(description="Audits of the page.", examples=[[]])


class ExpiredResponse(BaseModel):
    expired: int = Field(description="Audits marked expired.", examples=[2])
