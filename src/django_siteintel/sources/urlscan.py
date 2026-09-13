# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""urlscan.io — submit a scan, then poll for the result (countdown re-dispatch, never sleep)."""

import requests

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode
from django_siteintel.models import Audit
from django_siteintel.security import safe_get, safe_post
from django_siteintel.sources.base import (
    SourceError,
    SourceFetcher,
    api_key,
    fetch_options,
    is_not_found,
    parse_json,
    source_error,
)

PAGE_FIELDS = ("url", "domain", "ip", "country", "server", "status", "title", "tlsIssuer", "tlsValidDays")
STATS_FIELDS = ("malicious", "secure_percentage", "total_links", "uniq_countries")


class UrlscanSource(SourceFetcher):
    name = "urlscan"
    polls = True

    def fetch_raw(self, audit: Audit) -> dict:
        url = _base() + (f"/{audit.domain}.submit.json" if _recording() else "/scan/")
        try:
            submit = parse_json(safe_get(url, **fetch_options()), url) if _recording() else _submit(url, audit)
        except (ValueError, requests.RequestException) as exc:
            error = source_error(url, exc)
            if _recording() and is_not_found(exc):
                error.code = ErrorCode.RECORDING_MISSING
            raise error from None
        if not isinstance(submit.get("uuid"), str):
            raise SourceError(ErrorCode.INVALID, "submit: uuid missing")
        return {"submit": submit}

    def fetch_result(self, audit: Audit, uuid: str) -> dict | None:
        url = _base() + (f"/{audit.domain}.result.json" if _recording() else f"/result/{uuid}/")
        try:
            return parse_json(safe_get(url, **fetch_options()), url)
        except (ValueError, requests.RequestException) as exc:
            if is_not_found(exc):
                return None
            raise source_error(url, exc) from None

    def validate(self, raw: dict) -> None:
        if not isinstance((raw.get("result") or {}).get("page"), dict):
            raise SourceError(ErrorCode.INVALID, "result: page missing")

    def process(self, raw: dict) -> dict:
        result = raw["result"]
        data = result.get("data") or {}
        return {
            "page": {key: result["page"].get(key) for key in PAGE_FIELDS},
            "verdict": {k: (result.get("verdicts") or {}).get("overall", {}).get(k) for k in ("malicious", "score")},
            "stats": {key: (result.get("stats") or {}).get(key) for key in STATS_FIELDS},
            "request_count": len(data.get("requests") or []),
            "cookie_count": len(data.get("cookies") or []),
            "console_message_count": len(data.get("console") or []),
        }


def _submit(url: str, audit: Audit) -> dict:
    options = fetch_options()
    payload = {"url": audit.url, "visibility": "unlisted"}
    return parse_json(safe_post(url, payload, {"API-Key": api_key(UrlscanSource.name)}, **options), url)


def _base() -> str:
    return str(siteintel_settings.value("SITEINTEL_URLSCAN_BASE_URL")).rstrip("/")


def _recording() -> bool:
    return siteintel_settings.recording_mode(_base(), siteintel_settings.URLSCAN_PUBLIC_BASE_URL)
