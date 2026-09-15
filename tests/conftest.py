# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pytest
from celery import current_app
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django_siteintel.sources.registry import reset_registry_for_tests
from tests.fake_http import FakeHttp, FakeResponse

CHANNEL_IDX = "default-europe"
PSI = "http://fixtures:8000/fixtures/siteintel/psi"
URLSCAN = "http://fixtures:8000/fixtures/siteintel/urlscan"
DOMAIN = "example-shop-1.test"
GOOD_HTML = b"<html><head><title>Good</title><meta name='viewport' content='x'></head><body><img alt='a'></body></html>"


def psi_run(score: float = 0.9) -> dict:
    audits = {
        "largest-contentful-paint": {"score": 0.2, "numericValue": 4000, "displayValue": "4 s", "title": "LCP"},
        "final-screenshot": {"details": {"data": "data:image/jpeg;base64,AAAA"}},
    }
    return {
        "lighthouseResult": {
            "finalUrl": f"https://{DOMAIN}/",
            "categories": {"performance": {"score": score}},
            "audits": audits,
        }
    }


def urlscan_result() -> dict:
    return {
        "page": {"url": f"https://{DOMAIN}/", "domain": DOMAIN, "title": "Shop"},
        "verdicts": {"overall": {"malicious": False}},
        "data": {"requests": [{}, {}]},
    }


@pytest.fixture(autouse=True)
def fresh_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


@pytest.fixture
def http(monkeypatch, settings) -> FakeHttp:
    """Recording-mode settings (the zeno shape) and faked `requests`; the guard lets `fixtures` through."""
    fake = FakeHttp()
    monkeypatch.setattr("requests.get", fake.request)
    monkeypatch.setattr("requests.post", fake.request)
    settings.SITEINTEL_PSI_BASE_URL = PSI
    settings.SITEINTEL_URLSCAN_BASE_URL = URLSCAN
    settings.SITEINTEL_ALLOWED_HOSTS = ["fixtures", DOMAIN]
    return fake


@pytest.fixture
def recordings(http) -> FakeHttp:
    """Every source succeeds for DOMAIN: desktop PSI only (mobile 404), urlscan submit + result, the page."""
    http.add(f"{PSI}/{DOMAIN}.desktop.json", FakeResponse(200, psi_run()))
    http.add(f"{URLSCAN}/{DOMAIN}.submit.json", FakeResponse(200, {"uuid": "u-1"}))
    http.add(f"{URLSCAN}/{DOMAIN}.result.json", FakeResponse(200, urlscan_result()))
    http.add(f"https://{DOMAIN}", FakeResponse(200, GOOD_HTML))
    return http


@pytest.fixture
def eager_celery():
    previous = current_app.conf.task_always_eager
    current_app.conf.task_always_eager = True
    yield
    current_app.conf.task_always_eager = previous


def _client_for(**flags) -> APIClient:
    user = get_user_model().objects.create_user(username=f"u{len(flags)}{sorted(flags)}", **flags)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def admin_api(db) -> APIClient:
    return _client_for(is_staff=True)


@pytest.fixture
def customer_api(db) -> APIClient:
    return _client_for()


def api_url(path: str) -> str:
    return f"/api/siteintel/v2/admin/{CHANNEL_IDX}/{path}"
