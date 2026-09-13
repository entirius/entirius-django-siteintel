# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Module settings — read at call time so host settings and override_settings always win. Defaults live here."""

from django.conf import settings

QUEUE_DEFAULT = "siteintel_default"
PSI_PUBLIC_BASE_URL = "https://www.googleapis.com/pagespeedonline/v5"
URLSCAN_PUBLIC_BASE_URL = "https://urlscan.io/api/v1"

_DEFAULTS: dict[str, object] = {
    "SITEINTEL_PSI_BASE_URL": PSI_PUBLIC_BASE_URL,
    "SITEINTEL_URLSCAN_BASE_URL": URLSCAN_PUBLIC_BASE_URL,
    "SITEINTEL_ALLOWED_HOSTS": [],
    "SITEINTEL_FETCH_TIMEOUT_S": 20,
    "SITEINTEL_MAX_PAGE_BYTES": 5 * 1024 * 1024,
    "SITEINTEL_EXPIRE_DAYS": 90,
    "SITEINTEL_URLSCAN_POLL_BUDGET_S": 60,
    "SITEINTEL_URLSCAN_POLL_INTERVAL_S": 10,
    "SITEINTEL_PROCESSED_MAX_BYTES": 64 * 1024,
}


def value(name: str):
    """Host setting `name`, else its module default."""
    return getattr(settings, name, _DEFAULTS[name])


def block_private_hosts() -> bool:
    """SSRF guard master switch; False only in a dev harness whose fixtures live on a private network."""
    return bool(getattr(settings, "SITEINTEL_BLOCK_PRIVATE_HOSTS", True))


def recording_mode(base_url: str, public_url: str) -> bool:
    """A base URL other than the public API serves recordings as `{base}/{domain}.{strategy}.json`."""
    return base_url.rstrip("/") != public_url
