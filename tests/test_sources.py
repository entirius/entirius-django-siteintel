# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import json

import pytest

from django_siteintel.enums import ErrorCode
from django_siteintel.models import Audit, ExternalApiKey
from django_siteintel.services.cleaning_service import clean_snapshot
from django_siteintel.sources.base import SourceError
from django_siteintel.sources.heuristic import page_facts
from django_siteintel.sources.lighthouse import LighthouseSource
from django_siteintel.sources.registry import discover_sources
from django_siteintel.sources.urlscan import UrlscanSource
from tests.conftest import DOMAIN, PSI, psi_run
from tests.fake_http import FakeResponse

GOOD = (
    b"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'><title>Good Shop</title>"
    b"<meta name='description' content='Socks'></head><body><h1>Socks</h1><img src='a' alt='Red'>"
    b"<img src='b' alt='Blue'><script>ready()</script></body></html>"
)
SLOW = (
    b"<html><head><title>Slow Shop</title><style>" + b".c{margin:0}" * 25000 + b"</style></head><body>"
    + b"<script>x()</script>" * 6 + b"<img src='p.jpg'>" * 20 + b"</body></html>"
)  # fmt: skip
BROKEN = (
    b"<html><body><div><h1>Broken<p>Our <b>best <i>offers</b><table><tr><td>x<script>window.checkout.init();</script>"
)


def _audit(domain: str = DOMAIN) -> Audit:
    return Audit(
        domain=domain, url=f"https://{domain}", channel_idx="c", requested_by="t", expires_at="2099-01-01T00:00:00Z"
    )


def test_entry_points_resolve_three_sources():
    assert sorted(discover_sources()) == ["heuristic", "lighthouse", "urlscan"]


def test_S07_cleaning_strips_base64_trims_lists_under_64kb():
    psi = psi_run()
    psi["lighthouseResult"]["audits"].update({f"a{n}": {"score": 0.1, "title": "x" * 200} for n in range(5000)})
    psi["lighthouseResult"]["blob"] = "A" * 10_000
    psi["lighthouseResult"]["screenshot-thumbnails"] = {"items": ["data:image/png;base64,AAAA"]}
    source = LighthouseSource()
    raw = {"mobile": None, "desktop": psi}

    processed = clean_snapshot(source.process(raw))
    cleaned_raw = clean_snapshot(
        {
            "nested": [{"deep": [[[[["too deep"]]]]]}],
            "items": [{"img": "data:x", "n": n} for n in range(5000)],
            "blob": "A" * 600,
        }
    )

    text = json.dumps(processed) + json.dumps(cleaned_raw)
    assert "base64" not in text and "AAAAAAAAAA" not in text and "screenshot" not in text
    assert len(processed["strategies"]["desktop"]["top_issues"]) == 3
    assert processed["strategies"]["mobile"] == "unavailable"
    assert len(json.dumps(processed)) < 64 * 1024
    assert cleaned_raw == {"nested": [{"deep": [[[]]]}], "items": [{"n": 0}, {"n": 1}, {"n": 2}]}


def test_S07_still_too_large_is_invalid(settings):
    settings.SITEINTEL_PROCESSED_MAX_BYTES = 100
    with pytest.raises(SourceError) as caught:
        clean_snapshot({"text": "word " * 100})
    assert caught.value.code == ErrorCode.INVALID


def test_S08_heuristic_differs_per_synthetic_site():
    good, slow, broken = (page_facts(html, redirects=0) for html in (GOOD, SLOW, BROKEN))

    assert good | {"page_bytes": 0} == {
        "title": "Good Shop",
        "meta_description": "Socks",
        "inline_script_count": 1,
        "images_without_alt": 0,
        "image_count": 2,
        "page_bytes": 0,
        "redirect_count": 0,
        "has_viewport_meta": True,
    }
    assert (slow["inline_script_count"], slow["images_without_alt"]) == (6, 20)
    assert slow["page_bytes"] > 300_000
    assert (broken["title"], broken["meta_description"], broken["has_viewport_meta"]) == (None, None, False)
    assert broken["inline_script_count"] == 1
    assert len({json.dumps(facts, sort_keys=True) for facts in (good, slow, broken)}) == 3


def test_lighthouse_recording_mode_missing_strategy_unavailable(http):
    http.add(f"{PSI}/{DOMAIN}.desktop.json", FakeResponse(200, psi_run(0.43)))
    source = LighthouseSource()

    raw = source.fetch_raw(_audit())
    processed = source.process(raw)

    assert processed["strategies"]["mobile"] == "unavailable"
    assert processed["strategies"]["desktop"]["scores"] == {"performance": 0.43}


def test_lighthouse_no_recording_at_all(http):
    with pytest.raises(SourceError) as caught:
        LighthouseSource().fetch_raw(_audit())
    assert caught.value.code == ErrorCode.RECORDING_MISSING


def test_lighthouse_live_mode_key_never_in_error_detail(http, db, settings):
    settings.SITEINTEL_PSI_BASE_URL = "https://www.googleapis.com/pagespeedonline/v5"
    settings.SITEINTEL_ALLOWED_HOSTS = ["www.googleapis.com"]
    ExternalApiKey.objects.create(source="lighthouse", key="TEST-secret-key")
    http.add("https://www.googleapis.com/", FakeResponse(429))

    with pytest.raises(SourceError) as caught:
        LighthouseSource().fetch_raw(_audit())

    assert caught.value.code == ErrorCode.UPSTREAM
    assert (
        "key" not in str(caught.value) and "strategy=mobile" in http.calls[0] and "key=TEST-secret-key" in http.calls[0]
    )


def test_urlscan_live_submit_and_result_404_not_ready(http, db, settings):
    settings.SITEINTEL_URLSCAN_BASE_URL = "https://urlscan.io/api/v1"
    settings.SITEINTEL_ALLOWED_HOSTS = ["urlscan.io"]
    http.add("https://urlscan.io/api/v1/scan/", FakeResponse(200, {"uuid": "abc"}))
    source = UrlscanSource()

    assert source.fetch_raw(_audit()) == {"submit": {"uuid": "abc"}}
    assert source.fetch_result(_audit(), "abc") is None
    assert http.calls[-1] == "https://urlscan.io/api/v1/result/abc/"
