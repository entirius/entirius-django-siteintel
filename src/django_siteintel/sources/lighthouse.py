# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""PageSpeed Insights v5 — mobile and desktop Lighthouse runs of the audited URL."""

from urllib.parse import urlencode, urlparse

import requests

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode
from django_siteintel.models import Audit
from django_siteintel.security import safe_get
from django_siteintel.sources.base import (
    SourceError,
    SourceFetcher,
    api_key,
    fetch_options,
    is_not_found,
    parse_json,
    source_error,
)

STRATEGIES = ("mobile", "desktop")
UNAVAILABLE = "unavailable"
VITALS = ("first-contentful-paint", "largest-contentful-paint", "cumulative-layout-shift", "total-blocking-time")
VITALS_EXTRA = ("speed-index", "interactive")


class LighthouseSource(SourceFetcher):
    name = "lighthouse"

    def fetch_raw(self, audit: Audit) -> dict:
        raw = {strategy: self._fetch_strategy(audit, strategy) for strategy in STRATEGIES}
        if not any(raw.values()):
            raise SourceError(ErrorCode.RECORDING_MISSING, f"{audit.domain}: no recording for any strategy")
        return raw

    def validate(self, raw: dict) -> None:
        for strategy in STRATEGIES:
            run = raw.get(strategy)
            if run is not None and not isinstance(run.get("lighthouseResult"), dict):
                raise SourceError(ErrorCode.INVALID, f"{strategy}: lighthouseResult missing")

    def process(self, raw: dict) -> dict:
        return {"strategies": {s: _summary(raw[s]) if raw.get(s) else UNAVAILABLE for s in STRATEGIES}}

    def _fetch_strategy(self, audit: Audit, strategy: str) -> dict | None:
        url = _url(audit, strategy)
        try:
            fetched = safe_get(url, headers=_headers(), **fetch_options())
        except (ValueError, requests.RequestException) as exc:
            if _recording() and is_not_found(exc):
                return None
            raise source_error(url, exc) from None
        return parse_json(fetched, url)


def _base() -> str:
    return str(siteintel_settings.value("SITEINTEL_PSI_BASE_URL")).rstrip("/")


def _recording() -> bool:
    return siteintel_settings.recording_mode(_base(), siteintel_settings.PSI_PUBLIC_BASE_URL)


def _url(audit: Audit, strategy: str) -> str:
    if _recording():
        return f"{_base()}/{audit.domain}.{strategy}.json"
    params = {"url": audit.url, "strategy": strategy, "category": "performance"}
    return f"{_base()}/runPagespeed?{urlencode(params)}"


def _headers() -> dict:
    """The PSI key travels in a header: a `key=` query parameter would land in urllib3's DEBUG request log."""
    key = "" if _recording() else api_key(LighthouseSource.name)
    return {"X-Goog-Api-Key": key} if key else {}


def _summary(run: dict) -> dict:
    result = run["lighthouseResult"]
    audits = result.get("audits") or {}
    return {
        "final_url_host": urlparse(result.get("finalUrl") or "").hostname,
        "scores": {name: category.get("score") for name, category in (result.get("categories") or {}).items()},
        "vitals": {key: _metric(audits.get(key)) for key in (*VITALS, *VITALS_EXTRA) if key in audits},
        "field_data": (run.get("loadingExperience") or {}).get("overall_category"),
        "top_issues": _top_issues(audits),
    }


def _metric(item: dict) -> dict:
    return {"value": item.get("numericValue"), "display": item.get("displayValue"), "score": item.get("score")}


def _top_issues(audits: dict) -> list[dict]:
    """Lowest-scoring audits first; the cleaning service trims the list."""
    scored = [(key, item) for key, item in audits.items() if isinstance(item.get("score"), int | float)]
    failing = sorted((pair for pair in scored if pair[1]["score"] < 0.9), key=lambda pair: pair[1]["score"])
    return [{"id": key, "title": item.get("title"), "score": item["score"]} for key, item in failing]
