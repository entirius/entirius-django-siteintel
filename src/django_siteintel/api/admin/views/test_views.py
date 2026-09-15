# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Development-only endpoints that let BDD finish an audit without the worker and reset the reuse window.

Registered only when `settings.ENVIRONMENT == "development"`; the view guard answers 404 as well, so a host
that mounts the URLs anyway still exposes nothing.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from django_siteintel.api.admin.views._base import ERROR_RESPONSES, AdminView, audit_detail, parse
from django_siteintel.schemas.requests import ExpireNowRequest
from django_siteintel.schemas.responses import AuditDetailResponse, ExpiredResponse
from django_siteintel.services import audit_service

_TAGS = ["Siteintel (development)"]


def is_development() -> bool:
    return getattr(settings, "ENVIRONMENT", "") == "development"


class _DevelopmentView(AdminView):
    def initial(self, request: Request, *args, **kwargs) -> None:
        if not is_development():
            raise NotFound()
        super().initial(request, *args, **kwargs)


class RunNowView(_DevelopmentView):
    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_test_run_now",
        summary="Run every source of the audit synchronously and finish it (development only)",
        request=None,
        responses={200: AuditDetailResponse, **ERROR_RESPONSES},
    )
    def post(self, request: Request, channel_idx: str, audit_id) -> Response:
        audit = audit_service.run_now(self.audit(channel_idx, audit_id))
        return Response(audit_detail(audit))


class ExpireNowView(_DevelopmentView):
    @extend_schema(
        tags=_TAGS,
        operation_id="siteintel_test_expire_now",
        summary="Expire valid audits against a shifted clock (development only)",
        request=ExpireNowRequest,
        responses={200: ExpiredResponse, **ERROR_RESPONSES},
    )
    def post(self, request: Request, channel_idx: str) -> Response:
        body = parse(ExpireNowRequest, request.data or {})
        return Response(ExpiredResponse(expired=audit_service.expire_audits(now=body.now)).model_dump())
