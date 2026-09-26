# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Per-source configuration state for the health checks — bounded, cached, never raises.

``recording_host`` reads settings only, ``has_key`` one row. ``key_probe`` makes one authenticated call to the
public API, so it runs only on an explicit request (munin's "Check again", ``check --deploy``).
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

import requests
from django.core.cache import cache

from django_siteintel import settings as siteintel_settings
from django_siteintel.sources.base import api_key

logger = logging.getLogger(__name__)

CACHE_KEY = "django_siteintel.key_probe:{source}:{fingerprint}"  # per key: a new key is probed again
CACHE_TTL_S = 60
PROBE_TIMEOUT_S = 5
# Google answers a rejected key with 400 + this reason, the same status as a missing `url` argument.
PSI_KEY_INVALID = b"API_KEY_INVALID"


class SourceStatus(StrEnum):
    CONFIGURED = "configured"
    RECORDING = "recording"
    UNCONFIGURED = "unconfigured"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"


@dataclass(frozen=True)
class KeyedSource:
    name: str
    setting: str
    public_url: str
    probe_url: str
    key_header: str
    accepted: frozenset[int]  # probe statuses that prove the key was accepted


SOURCES = (
    # No `url` argument: Google checks the key first, then refuses the request with 400 — no Lighthouse run.
    KeyedSource(
        "lighthouse",
        "SITEINTEL_PSI_BASE_URL",
        siteintel_settings.PSI_PUBLIC_BASE_URL,
        f"{siteintel_settings.PSI_PUBLIC_BASE_URL}/runPagespeed",
        "X-Goog-Api-Key",
        frozenset({200, 400, 429}),
    ),
    KeyedSource(
        "urlscan",
        "SITEINTEL_URLSCAN_BASE_URL",
        siteintel_settings.URLSCAN_PUBLIC_BASE_URL,
        "https://urlscan.io/user/quotas/",
        "API-Key",
        frozenset({200, 429}),
    ),
)


def recording_host(source: KeyedSource) -> str:
    """Host serving recorded answers, or ``""`` when the source talks to the public API."""
    base = str(siteintel_settings.value(source.setting))
    if not siteintel_settings.recording_mode(base, source.public_url):
        return ""
    return urlparse(base).hostname or base


def has_key(source: KeyedSource) -> bool:
    return bool(api_key(source.name))


def key_probe(source: KeyedSource) -> SourceStatus:
    """One cached authenticated call; ``recording`` / ``unconfigured`` without calling anything."""
    if recording_host(source):
        return SourceStatus.RECORDING
    try:
        key = api_key(source.name)
        return _cached_probe(source, key) if key else SourceStatus.UNCONFIGURED
    except Exception as exc:  # noqa: BLE001 — DB or cache backend failure; a probe must not raise
        logger.warning("Key probe of %s failed: %s", source.name, type(exc).__name__)
        return SourceStatus.UNREACHABLE


def _cached_probe(source: KeyedSource, key: str) -> SourceStatus:
    cache_key = CACHE_KEY.format(source=source.name, fingerprint=hashlib.sha256(key.encode()).hexdigest()[:12])
    if cache.get(cache_key) is not None:
        return SourceStatus.CONFIGURED
    result = _probe(source, key)
    if result == SourceStatus.CONFIGURED:  # a failure is never cached: "Check again" after a fix must call again
        cache.set(cache_key, result.value, CACHE_TTL_S)
    return result


def _probe(source: KeyedSource, key: str) -> SourceStatus:
    try:
        response = requests.get(
            source.probe_url, headers={source.key_header: key}, timeout=PROBE_TIMEOUT_S, allow_redirects=False
        )
    except requests.RequestException as exc:
        logger.info("%s unreachable: %s", source.name, type(exc).__name__)
        return SourceStatus.UNREACHABLE
    if response.status_code in (401, 403) or PSI_KEY_INVALID in response.content:
        return SourceStatus.AUTH_FAILED
    if response.status_code in source.accepted:
        return SourceStatus.CONFIGURED
    logger.info("%s probe answered %s", source.name, response.status_code)
    return SourceStatus.UNREACHABLE
