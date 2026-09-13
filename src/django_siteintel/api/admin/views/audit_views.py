# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API v2 — audits of a channel: list, detail, request (reuses a valid audit), rerun."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from django_siteintel.api.admin.views._base import ERROR_RESPONSES, AdminView, audit_detail, parse
from django_siteintel.enums import REUSABLE_AUDIT_STATUSES
from django_siteintel.models import Audit
from django_siteintel.schemas.requests import AuditCreateRequest, AuditListQuery, AuditRerunRequest
from django_siteintel.schemas.responses import AuditDetailResponse, AuditListResponse, AuditResponse
from django_siteintel.services import audit_service
from django_siteintel.utils.domains import normalise_domain

_TAGS = ["Siteintel"]
INVALID_DOMAIN = "Not a domain or http(s) URL."


class AuditRunning(APIException):
    status_code = 409
    default_detail = "The audit is still running; rerun it once it has finished."
    default_code = "audit_running"


class AuditPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AuditListView(AdminView):
    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_audits_list",
        summary="List audits requested on the channel",
        parameters=[
            OpenApiParameter("domain", str, description="Domain or URL, matched on its registrable domain."),
            OpenApiParameter("status", str, description="Only audits in this status."),
            OpenApiParameter("ordering", str, description="created_at, domain or status; '-' for descending."),
            OpenApiParameter("page", int, description="Page number."),
        ],
        responses={200: AuditListResponse, **ERROR_RESPONSES},
    )
    def get(self, request: Request, channel_idx: str) -> Response:
        query = parse(AuditListQuery, request.query_params.dict())
        audits = Audit.objects.filter(channel_idx=channel_idx).order_by(query.ordering, "pk")
        if query.domain:
            audits = audits.filter(domain=_domain(query.domain))
        if query.status:
            audits = audits.filter(status=query.status)
        paginator = AuditPagination()
        page = paginator.paginate_queryset(audits, request, view=self)
        payload = AuditListResponse(
            count=paginator.page.paginator.count,
            next=paginator.get_next_link(),
            previous=paginator.get_previous_link(),
            results=[AuditResponse.model_validate(audit) for audit in page],
        )
        return Response(payload.model_dump(mode="json"))

    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_audits_request",
        summary="Request an audit of a domain",
        description="201 with a new pending audit, or 200 with the valid audit of the domain (reused, no fetch).",
        request=AuditCreateRequest,
        responses={200: AuditResponse, 201: AuditResponse, **ERROR_RESPONSES},
    )
    def post(self, request: Request, channel_idx: str) -> Response:
        body = parse(AuditCreateRequest, request.data)
        try:
            audit = audit_service.request_audit(channel_idx=channel_idx, **body.model_dump())
        except ValueError:
            raise ValidationError({"domain_or_url": [INVALID_DOMAIN]}) from None
        status = 200 if audit.status in REUSABLE_AUDIT_STATUSES else 201
        return Response(AuditResponse.model_validate(audit).model_dump(mode="json"), status=status)


class AuditDetailView(AdminView):
    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_audits_detail",
        summary="Get one audit with the processed report of every source",
        responses={200: AuditDetailResponse, **ERROR_RESPONSES},
    )
    def get(self, request: Request, channel_idx: str, audit_id) -> Response:
        return Response(audit_detail(self.audit(channel_idx, audit_id)))


class AuditRerunView(AdminView):
    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_audits_rerun",
        summary="Re-run an audit: same id, reports reset and fetched again",
        request=AuditRerunRequest,
        responses={202: AuditResponse, 409: None, **ERROR_RESPONSES},
    )
    def post(self, request: Request, channel_idx: str, audit_id) -> Response:
        body = parse(AuditRerunRequest, request.data or {})
        requested_by = body.requested_by or f"admin:{request.user.get_username()}"
        try:
            audit = audit_service.rerun_audit(audit=self.audit(channel_idx, audit_id), requested_by=requested_by)
        except audit_service.AuditRunningError:
            raise AuditRunning() from None
        return Response(AuditResponse.model_validate(audit).model_dump(mode="json"), status=202)


def _domain(domain_or_url: str) -> str:
    try:
        return normalise_domain(domain_or_url)[0]
    except ValueError:
        raise ValidationError({"domain": [INVALID_DOMAIN]}) from None
