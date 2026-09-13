# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Request schemas of the siteintel admin API v2."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from django_siteintel.enums import AuditStatus

SORT_FIELDS = ("created_at", "domain", "status")


class AuditListQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: str | None = Field(
        default=None,
        max_length=2048,
        description="Domain or URL; matched on its registrable domain.",
        examples=["shop.example"],
    )
    status: AuditStatus | None = Field(default=None, description="Only audits in this status.", examples=["completed"])
    ordering: str = Field(
        default="-created_at",
        pattern=r"^-?(created_at|domain|status)$",
        description="Sort field (created_at, domain, status), '-' prefix for descending.",
        examples=["-created_at"],
    )


class AuditCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_or_url: str = Field(
        min_length=1, max_length=2048, description="Domain or URL to audit.", examples=["https://www.shop.example/pl"]
    )
    requested_by: str = Field(
        min_length=1, max_length=200, description="Subject reference of the requester.", examples=["leads.Company:42"]
    )


class AuditRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Requester; the admin username when omitted.",
        examples=["cms:admin"],
    )


class ExpireNowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime | None = Field(
        default=None, description="Clock to expire against; server time when null.", examples=["2027-01-01T00:00:00Z"]
    )
