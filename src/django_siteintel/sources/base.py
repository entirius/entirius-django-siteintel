# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Source contract: fetch (network) → validate → process (pure). `SourceError` is the only failure the runner maps."""

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlparse

import requests

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode
from django_siteintel.models import ExternalApiKey
from django_siteintel.security import Fetched

if TYPE_CHECKING:
    from django_siteintel.models import Audit


class SourceError(Exception):
    """`code` is an `ErrorCode`; `detail` is host + error class — never a body, a key or a URL carrying it."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SourceFetcher(ABC):
    name: ClassVar[str]
    # Polling sources return the submission from `fetch_raw` and deliver the result through `fetch_result`.
    polls: ClassVar[bool] = False

    @abstractmethod
    def fetch_raw(self, audit: "Audit") -> dict: ...

    @abstractmethod
    def validate(self, raw: dict) -> None: ...

    @abstractmethod
    def process(self, raw: dict) -> dict: ...

    def fetch_result(self, audit: "Audit", uuid: str) -> dict | None:
        """Polling sources only: the finished result, or None while it is not ready."""
        raise NotImplementedError


def source_error(url: str, exc: Exception) -> SourceError:
    """Map a guard / requests failure to a `SourceError` whose detail carries only host and error class."""
    detail = f"{urlparse(url).hostname or '-'}: {type(exc).__name__}"
    message = str(exc)
    if "internal host" in message:
        return SourceError(ErrorCode.SSRF, detail)
    if "exceeds the cap" in message:
        return SourceError(ErrorCode.TRUNCATED, detail)
    return SourceError(ErrorCode.UPSTREAM, detail)


def is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    return isinstance(exc, requests.HTTPError) and response is not None and response.status_code == 404


def parse_json(fetched: Fetched, url: str) -> dict:
    try:
        data = json.loads(fetched.content)
    except ValueError as exc:
        raise SourceError(ErrorCode.INVALID, f"{urlparse(url).hostname or '-'}: {type(exc).__name__}") from None
    if not isinstance(data, dict):
        raise SourceError(ErrorCode.INVALID, f"{urlparse(url).hostname or '-'}: not a JSON object")
    return data


def fetch_options() -> dict:
    """`safe_get` keyword arguments shared by every source."""
    return {
        "timeout": siteintel_settings.value("SITEINTEL_FETCH_TIMEOUT_S"),
        "cap": siteintel_settings.value("SITEINTEL_MAX_PAGE_BYTES"),
        "allowed_hosts": siteintel_settings.value("SITEINTEL_ALLOWED_HOSTS"),
    }


def api_key(source: str) -> str:
    return ExternalApiKey.objects.filter(source=source, is_active=True).values_list("key", flat=True).first() or ""
