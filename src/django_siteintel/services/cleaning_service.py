# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Port of the prototype "Remove Trash": strip base64 blobs and screenshots, trim lists, cap nesting and size."""

import json

from django_siteintel import settings as siteintel_settings
from django_siteintel.enums import ErrorCode
from django_siteintel.sources.base import SourceError

MAX_DEPTH = 6
LIST_CAP = 3
MAX_BARE_STRING = 512
_TRASH_KEY_PARTS = ("screenshot", "thumbnail")
_DROP = object()


def clean_snapshot(snapshot: dict) -> dict:
    """Cleaned copy under `SITEINTEL_PROCESSED_MAX_BYTES`; lists trimmed to 3, then to 1, then `invalid`."""
    limit = siteintel_settings.value("SITEINTEL_PROCESSED_MAX_BYTES")
    for list_cap in (LIST_CAP, 1):
        cleaned = _clean(snapshot, depth=0, list_cap=list_cap)
        if len(json.dumps(cleaned)) < limit:
            return cleaned
    raise SourceError(ErrorCode.INVALID, "processed snapshot too large")


def strip_nul(value):
    """Copy of a JSON value without NUL characters in any string or key — Postgres jsonb rejects U+0000."""
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    return value.replace("\x00", "") if isinstance(value, str) else value


def _clean(value, depth: int, list_cap: int):
    if isinstance(value, dict | list) and depth >= MAX_DEPTH:
        return _DROP
    if isinstance(value, dict):
        items = ((k, _clean(v, depth + 1, list_cap)) for k, v in value.items() if not _is_trash_key(k))
        return {k: v for k, v in items if v is not _DROP}
    if isinstance(value, list):
        items = (_clean(v, depth + 1, list_cap) for v in value)
        return [v for v in items if v is not _DROP][:list_cap]
    return _DROP if isinstance(value, str) and _is_blob(value) else value


def _is_trash_key(key: str) -> bool:
    return any(part in str(key).lower() for part in _TRASH_KEY_PARTS)


def _is_blob(text: str) -> bool:
    return text.startswith("data:") or (len(text) > MAX_BARE_STRING and not any(c.isspace() for c in text))
