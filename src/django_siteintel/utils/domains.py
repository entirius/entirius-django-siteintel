# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Registrable-domain normalisation without a public-suffix download.

eTLD+1 = the last two host labels, or three when the last two form a known multi-part public suffix
(`shop.com.pl`). Hosts without a dot (`fixtures`) and IP literals are their own key.
"""

import ipaddress
from urllib.parse import urlparse

MAX_URL_LENGTH = 2048  # `Audit.url` column size, checked after the scheme is added
MULTI_PART_SUFFIXES = frozenset(
    {"com.pl", "net.pl", "org.pl", "co.uk", "org.uk", "com.au", "co.jp", "com.br", "co.nz", "com.tr", "co.za"}
)


def normalise_domain(domain_or_url: str) -> tuple[str, str]:
    """(registrable domain, url with scheme) — raises `ValueError` on input without a usable host."""
    raw = (domain_or_url or "").strip()
    url = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or len(url) > MAX_URL_LENGTH:
        raise ValueError("not a domain or http(s) URL")
    return registrable_domain(parsed.hostname), url


def registrable_domain(host: str) -> str:
    host = host.lower().rstrip(".")
    if _is_ip(host) or "." not in host:
        return host
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2 or any(" " in label for label in labels):
        raise ValueError("not a domain or http(s) URL")
    size = 3 if ".".join(labels[-2:]) in MULTI_PART_SUFFIXES and len(labels) > 2 else 2
    return ".".join(labels[-size:])


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
