# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared wiring of the admin views — auth declared explicitly, never inherited from service defaults."""

from typing import TypeVar

from django_utils.api.v2_errors import raise_pydantic_as_drf
from pydantic import BaseModel, ValidationError
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_siteintel.models import Audit
from django_siteintel.schemas.responses import AuditDetailResponse, AuditResponse, ReportResponse

SchemaT = TypeVar("SchemaT", bound=BaseModel)

ERROR_RESPONSES = {400: None, 401: None, 403: None, 404: None}


class AdminView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @staticmethod
    def audit(channel_idx: str, audit_id) -> Audit:
        audit = Audit.objects.filter(pk=audit_id, channel_idx=channel_idx).prefetch_related("reports").first()
        if audit is None:
            raise NotFound("Audit not found.")
        return audit


def parse(schema: type[SchemaT], data: object) -> SchemaT:
    """Validate request data; a Pydantic error becomes the v2 400 shape."""
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise_pydantic_as_drf(exc)


def audit_detail(audit: Audit) -> dict:
    reports = sorted(audit.reports.all(), key=lambda report: report.source)
    payload = AuditDetailResponse(
        **AuditResponse.model_validate(audit).model_dump(),
        reports=[ReportResponse.model_validate(report) for report in reports],
    )
    return payload.model_dump(mode="json")
