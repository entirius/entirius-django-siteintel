# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""`siteintel.sources` config check and `siteintel.keys` probe — every branch, no network."""

from unittest.mock import patch

import pytest
import requests
from django.core import checks
from django.core.cache import cache

from django_siteintel.checks import KEYS_FIX_URL, SETTINGS_FIX_URL, keys_accepted, sources_configured
from django_siteintel.models import ExternalApiKey
from django_siteintel.services.source_status import SOURCES, SourceStatus, key_probe
from django_siteintel.settings import PSI_PUBLIC_BASE_URL, URLSCAN_PUBLIC_BASE_URL
from tests.conftest import PSI, URLSCAN
from tests.fake_http import FakeHttp, FakeResponse

LIGHTHOUSE, URLSCAN_SOURCE = SOURCES
DB = ["default"]


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


@pytest.fixture
def live(settings):
    settings.SITEINTEL_PSI_BASE_URL = PSI_PUBLIC_BASE_URL
    settings.SITEINTEL_URLSCAN_BASE_URL = URLSCAN_PUBLIC_BASE_URL + "/"  # a trailing slash is still the public API


@pytest.fixture
def fake(monkeypatch) -> FakeHttp:
    fake = FakeHttp()
    monkeypatch.setattr("requests.get", fake.request)
    return fake


def _keys(*sources, active=True):
    for source in sources:
        ExternalApiKey.objects.create(source=source, key=f"KEY-{source}", is_active=active)


def _rows(messages):
    return {m.obj["scope"]: (m.id, m.obj["state"], m.obj["severity"], m.obj["fix_url"]) for m in messages}


class TestSourcesConfigured:
    def test_recording_mode_one_high_row_per_source_without_db(self, settings):
        settings.SITEINTEL_PSI_BASE_URL = PSI
        settings.SITEINTEL_URLSCAN_BASE_URL = URLSCAN
        messages = sources_configured()  # boot: no `databases`, still reported (settings only)
        assert all(isinstance(m, checks.Warning) for m in messages)
        assert _rows(messages) == {
            "lighthouse": ("siteintel.sources", "recording", "high", SETTINGS_FIX_URL),
            "urlscan": ("siteintel.sources", "recording", "high", SETTINGS_FIX_URL),
        }
        assert "fixtures" in messages[0].hint
        assert str(messages[0].obj) == "lighthouse"

    def test_recording_mode_ignores_missing_keys(self, settings, db):
        settings.SITEINTEL_PSI_BASE_URL = PSI
        settings.SITEINTEL_URLSCAN_BASE_URL = URLSCAN
        assert {m.obj["state"] for m in sources_configured(databases=DB)} == {"recording"}

    @pytest.mark.usefixtures("live")
    def test_live_with_active_keys_is_healthy(self, db):
        _keys("lighthouse", "urlscan")
        assert sources_configured(databases=DB) == []

    @pytest.mark.usefixtures("live")
    def test_live_missing_keys_urlscan_high_lighthouse_medium(self, db):
        assert _rows(sources_configured(databases=DB)) == {
            "lighthouse": ("siteintel.sources", "unconfigured", "medium", KEYS_FIX_URL),
            "urlscan": ("siteintel.sources", "unconfigured", "high", KEYS_FIX_URL),
        }

    @pytest.mark.usefixtures("live")
    def test_inactive_key_counts_as_missing(self, db):
        _keys("lighthouse")
        _keys("urlscan", active=False)
        assert _rows(sources_configured(databases=DB)) == {
            "urlscan": ("siteintel.sources", "unconfigured", "high", KEYS_FIX_URL)
        }

    @pytest.mark.usefixtures("live")
    def test_no_databases_reads_no_rows(self, db, django_assert_num_queries):
        with django_assert_num_queries(0):
            assert sources_configured() == []

    @pytest.mark.usefixtures("live")
    def test_missing_table_reads_no_rows(self, db):
        with patch("django.db.backends.base.introspection.BaseDatabaseIntrospection.table_names", return_value=[]):
            assert sources_configured(databases=DB) == []

    def test_mixed_mode_recording_plus_live_key_row(self, settings, db):
        settings.SITEINTEL_PSI_BASE_URL = PSI
        settings.SITEINTEL_URLSCAN_BASE_URL = URLSCAN_PUBLIC_BASE_URL
        assert _rows(sources_configured(databases=DB)) == {
            "lighthouse": ("siteintel.sources", "recording", "high", SETTINGS_FIX_URL),
            "urlscan": ("siteintel.sources", "unconfigured", "high", KEYS_FIX_URL),
        }


@pytest.mark.usefixtures("live")
class TestKeyProbe:
    def test_recording_skips_the_call(self, settings, fake, db):
        settings.SITEINTEL_PSI_BASE_URL = PSI
        assert key_probe(LIGHTHOUSE) == SourceStatus.RECORDING
        assert fake.calls == []

    def test_no_key_skips_the_call(self, fake, db):
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.UNCONFIGURED
        assert fake.calls == []

    def test_psi_400_without_url_means_key_accepted(self, fake, db):
        _keys("lighthouse")
        fake.add(PSI_PUBLIC_BASE_URL, FakeResponse(400, {"error": {"status": "INVALID_ARGUMENT"}}))
        assert key_probe(LIGHTHOUSE) == SourceStatus.CONFIGURED
        assert fake.headers == [{"X-Goog-Api-Key": "KEY-lighthouse"}]

    def test_psi_api_key_invalid_is_auth_failed(self, fake, db):
        _keys("lighthouse")
        fake.add(PSI_PUBLIC_BASE_URL, FakeResponse(400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}))
        assert key_probe(LIGHTHOUSE) == SourceStatus.AUTH_FAILED

    def test_urlscan_quota_200_and_401(self, fake, db):
        _keys("urlscan")
        fake.add("https://urlscan.io/user/quotas/", FakeResponse(401), FakeResponse(200, {"limits": {}}))
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.AUTH_FAILED
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.CONFIGURED
        assert fake.headers[-1] == {"API-Key": "KEY-urlscan"}

    def test_server_error_is_unreachable(self, fake, db):
        _keys("urlscan")
        fake.add("https://urlscan.io/", FakeResponse(503))
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.UNREACHABLE

    def test_network_error_is_unreachable_with_timeout(self, monkeypatch, db):
        _keys("urlscan")
        seen = {}

        def refuse(url, **kwargs):
            seen.update(kwargs)
            raise requests.ConnectionError("refused")

        monkeypatch.setattr("requests.get", refuse)
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.UNREACHABLE
        assert seen["timeout"] == 5

    def test_success_is_cached_failure_is_not(self, fake, db):
        _keys("urlscan")
        fake.add("https://urlscan.io/", FakeResponse(401), FakeResponse(200), FakeResponse(401))
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.AUTH_FAILED
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.CONFIGURED
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.CONFIGURED  # cached: the third 401 is never fetched
        assert len(fake.calls) == 2

    def test_cache_failure_never_raises(self, fake, db):
        _keys("urlscan")
        with patch("django_siteintel.services.source_status.cache.get", side_effect=RuntimeError("down")):
            assert key_probe(URLSCAN_SOURCE) == SourceStatus.UNREACHABLE


@pytest.mark.usefixtures("live")
class TestKeysAccepted:
    def test_rows_only_for_failing_probes(self, fake, db):
        _keys("lighthouse", "urlscan")
        fake.add(PSI_PUBLIC_BASE_URL, FakeResponse(400, b"API_KEY_INVALID"))
        fake.add("https://urlscan.io/", FakeResponse(502))
        assert _rows(keys_accepted(databases=DB)) == {
            "lighthouse": ("siteintel.keys", "auth_failed", "high", KEYS_FIX_URL),
            "urlscan": ("siteintel.keys", "unreachable", "high", KEYS_FIX_URL),
        }

    def test_healthy_and_unconfigured_give_no_probe_rows(self, fake, db):
        _keys("lighthouse")
        fake.add(PSI_PUBLIC_BASE_URL, FakeResponse(400, b"{}"))
        assert keys_accepted(databases=DB) == []

    def test_without_databases_the_key_table_is_not_read(self, fake, db, django_assert_num_queries):
        _keys("urlscan")
        with django_assert_num_queries(0):
            assert keys_accepted() == []
        assert fake.calls == []

    def test_a_new_key_is_probed_again(self, fake, db):
        _keys("urlscan")
        fake.add("https://urlscan.io/", FakeResponse(200, b"{}"))
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.CONFIGURED
        ExternalApiKey.objects.filter(source="urlscan").update(key="TEST-other-key")
        fake.add("https://urlscan.io/", FakeResponse(401, b"{}"))
        assert key_probe(URLSCAN_SOURCE) == SourceStatus.AUTH_FAILED

    def test_registered_as_deploy_probe(self):
        from django.core.checks.registry import registry

        assert keys_accepted in registry.get_checks(include_deployment_checks=True)
        assert keys_accepted not in registry.get_checks()
        assert sources_configured in registry.get_checks()
