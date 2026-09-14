# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SSRF guard for every outbound fetch: PageSpeed Insights, urlscan.io and the audited page itself.

Copied from `django_lookup.security.url_guard` (a sibling copy, never a shared import — siteintel must not
depend on a catalog module), reading `SITEINTEL_BLOCK_PRIVATE_HOSTS` through `block_private_hosts()`.
Additions: `safe_post` (the urlscan submission, capped like a GET) and, for the heuristic source, `Fetched.redirects` counts the hops followed, and the cap error
`BodyTooLarge` keeps the bytes received so a truncated page can still be analysed (S-06).

`SITEINTEL_BLOCK_PRIVATE_HOSTS = False` drops the IP check wholesale (zeno dev, where the fixtures container
is private); `SITEINTEL_ALLOWED_HOSTS` punches a hole for named hosts only.
"""

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

from django_siteintel.settings import block_private_hosts

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 3
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_CHUNK = 65536


@dataclass(frozen=True)
class Fetched:
    content: bytes
    content_type: str
    redirects: int = 0


class BodyTooLarge(ValueError):
    """The body passed the cap; `partial` holds the first `cap` bytes received."""

    def __init__(self, cap: int, partial: bytes, redirects: int = 0):
        super().__init__(f"response body exceeds the cap of {cap} bytes")
        self.partial = partial
        self.redirects = redirects


def _is_internal_ip(host: str) -> bool:
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    return any(_internal(sockaddr[0]) for *_rest, sockaddr in addr_info)


def _internal(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def assert_safe_url(url: str, allowed_hosts: Iterable[str] = ()) -> None:
    """Raise `ValueError` when the URL is not safe to fetch server-side."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL missing hostname")
    if parsed.hostname in set(allowed_hosts) or not block_private_hosts():
        return
    if _is_internal_ip(parsed.hostname):
        raise ValueError(f"internal host blocked: {parsed.hostname}")


def safe_get(
    url: str, timeout: float, cap: int, allowed_hosts: Iterable[str] = (), headers: dict | None = None
) -> Fetched:
    """GET with the host re-validated on every redirect hop and the body streamed up to `cap` bytes.

    Redirects are never auto-followed: `allow_redirects=True` would connect to each hop before
    `assert_safe_url` ever saw it, which is exactly the SSRF this guard exists to stop.
    """
    current_url = url
    for hop in range(MAX_REDIRECTS + 1):
        assert_safe_url(current_url, allowed_hosts=allowed_hosts)
        same_host = urlparse(current_url).hostname == urlparse(url).hostname  # headers never follow to another host
        response = requests.get(
            current_url, headers=headers if same_host else None, timeout=timeout, stream=True, allow_redirects=False
        )
        if response.status_code in _REDIRECT_STATUS_CODES:
            current_url = urljoin(current_url, _location(response))
            continue
        with response:
            response.raise_for_status()
            content = _body(response, cap, hop)
            return Fetched(content=content, content_type=response.headers.get("Content-Type", ""), redirects=hop)
    raise ValueError(f"too many redirects (> {MAX_REDIRECTS}) fetching {url}")


def safe_post(
    url: str, payload: dict, headers: dict, timeout: float, cap: int, allowed_hosts: Iterable[str] = ()
) -> Fetched:
    """POST JSON to a validated host; redirects are refused and the body is capped like `safe_get`."""
    assert_safe_url(url, allowed_hosts=allowed_hosts)
    response = requests.post(url, json=payload, headers=headers, timeout=timeout, stream=True, allow_redirects=False)
    with response:
        if response.status_code in _REDIRECT_STATUS_CODES:
            raise ValueError("redirect refused on POST")
        response.raise_for_status()
        return Fetched(content=_body(response, cap, 0), content_type=response.headers.get("Content-Type", ""))


def _location(response: requests.Response) -> str:
    location = response.headers.get("Location")
    response.close()
    if not location:
        raise ValueError("redirect response missing Location header")
    return location


def _body(response: requests.Response, cap: int, redirects: int) -> bytes:
    body = bytearray()
    for chunk in response.iter_content(chunk_size=_CHUNK):
        body.extend(chunk)
        if len(body) > cap:
            raise BodyTooLarge(cap, bytes(body[:cap]), redirects)
    return bytes(body)
