# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import importlib

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import clear_url_caches

from django_siteintel.enums import AuditStatus
from django_siteintel.models import Audit, ExternalApiKey
from django_siteintel.services import audit_service
from tests.conftest import CHANNEL_IDX, DOMAIN, api_url


def _create(admin_api, domain=DOMAIN):
    return admin_api.post(api_url("audits/"), {"domain_or_url": domain, "requested_by": "bdd"}, format="json")


def test_request_201_then_run_now_then_200_same_id(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    created = _create(admin_api)
    assert created.status_code == 201
    audit_id = created.json()["id"]

    done = admin_api.post(api_url(f"test/run-now/{audit_id}/"))
    again = _create(admin_api, f"https://www.{DOMAIN}/")

    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert (again.status_code, again.json()["id"]) == (200, audit_id)


def test_api_never_returns_raw_or_keys(admin_api, recordings):
    ExternalApiKey.objects.create(source="urlscan", key="TEST-urlscan-secret")
    audit = audit_service.run_now(
        audit_service.request_audit(domain_or_url=DOMAIN, channel_idx=CHANNEL_IDX, requested_by="t")
    )

    body = admin_api.get(api_url(f"audits/{audit.pk}/")).content.decode()

    assert '"raw"' not in body and "TEST-urlscan-secret" not in body and "lighthouseResult" not in body
    assert '"processed"' in body


def test_detail_query_count(admin_api, recordings):
    audit = audit_service.run_now(
        audit_service.request_audit(domain_or_url=DOMAIN, channel_idx=CHANNEL_IDX, requested_by="t")
    )
    with CaptureQueriesContext(connection) as queries:
        response = admin_api.get(api_url(f"audits/{audit.pk}/"))
    assert response.status_code == 200 and len(response.json()["reports"]) == 3
    assert len(queries) <= 3


def test_list_filters_and_sort_allowlist(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    _create(admin_api)
    _create(admin_api, "other-shop.test")

    by_domain = admin_api.get(api_url("audits/"), {"domain": f"https://www.{DOMAIN}/x", "status": "pending"}).json()
    assert [item["domain"] for item in by_domain["results"]] == [DOMAIN]
    assert admin_api.get(api_url("audits/"), {"ordering": "domain"}).json()["results"][0]["domain"] == DOMAIN
    assert admin_api.get(api_url("audits/"), {"ordering": "raw"}).status_code == 400


def test_rerun_202_same_id(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    audit_id = _create(admin_api).json()["id"]
    response = admin_api.post(api_url(f"audits/{audit_id}/rerun/"), {}, format="json")
    assert (response.status_code, response.json()["id"], response.json()["requested_by"]) == (
        202,
        audit_id,
        "admin:u1['is_staff']",
    )


def test_invalid_domain_400_and_auth(admin_api, customer_api, client):
    assert _create(admin_api, "ftp://nope").status_code == 400
    assert client.get(api_url("audits/")).status_code == 401
    assert customer_api.get(api_url("audits/")).status_code == 403


def test_other_channel_audit_is_404(admin_api, recordings):
    audit = Audit.objects.create(
        domain=DOMAIN, url="https://x.test", channel_idx="other", requested_by="t", expires_at="2099-01-01T00:00:00Z"
    )
    assert admin_api.get(api_url(f"audits/{audit.pk}/")).status_code == 404


def test_run_now_endpoint_absent_outside_development(admin_api, recordings, settings):
    audit = Audit.objects.create(
        domain=DOMAIN,
        url="https://x.test",
        channel_idx=CHANNEL_IDX,
        requested_by="t",
        expires_at="2099-01-01T00:00:00Z",
    )
    settings.ENVIRONMENT = "production"
    assert admin_api.post(api_url(f"test/run-now/{audit.pk}/")).status_code == 404  # view guard

    from django_siteintel.api.admin import urls

    try:
        importlib.reload(urls)
        assert not [p for p in urls.urlpatterns if str(p.pattern).startswith("test/")]
    finally:
        settings.ENVIRONMENT = "development"
        importlib.reload(urls)
        clear_url_caches()


def test_S09_rerun_running_audit_409(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    audit_id = _create(admin_api).json()["id"]
    Audit.objects.filter(pk=audit_id).update(status=AuditStatus.RUNNING)

    response = admin_api.post(api_url(f"audits/{audit_id}/rerun/"), {}, format="json")

    assert response.status_code == 409
    assert {"error", "message", "debug_id"} <= set(response.json())
    assert Audit.objects.get(pk=audit_id).status == AuditStatus.RUNNING


def test_long_domain_without_scheme_is_400(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    at_limit = "a.test/" + "x" * (2048 - len("https://a.test/"))  # 2040 chars, 2048 once the scheme is added

    assert _create(admin_api, at_limit).status_code == 201
    assert _create(admin_api, at_limit + "x").status_code == 400


def test_item1_rerun_while_another_audit_in_flight_409(admin_api, recordings, monkeypatch):
    monkeypatch.setattr("django_siteintel.tasks.run_audit.delay", lambda audit_id: None)
    old_id = _create(admin_api).json()["id"]
    Audit.objects.filter(pk=old_id).update(status=AuditStatus.EXPIRED)
    _create(admin_api)

    response = admin_api.post(api_url(f"audits/{old_id}/rerun/"), {}, format="json")

    assert response.status_code == 409
    assert {"error", "message", "debug_id"} <= set(response.json())
    assert Audit.objects.get(pk=old_id).status == AuditStatus.EXPIRED
