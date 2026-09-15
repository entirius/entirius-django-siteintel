# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Own fetch of the audited page through the SSRF guard; facts from a stdlib HTML parse."""

from html.parser import HTMLParser

import requests

from django_siteintel.enums import ErrorCode
from django_siteintel.models import Audit
from django_siteintel.security import BodyTooLarge, safe_get
from django_siteintel.sources.base import SourceError, SourceFetcher, fetch_options, source_error

FACT_KEYS = (
    "title",
    "meta_description",
    "inline_script_count",
    "images_without_alt",
    "image_count",
    "page_bytes",
    "redirect_count",
    "has_viewport_meta",
)


class HeuristicSource(SourceFetcher):
    name = "heuristic"

    def fetch_raw(self, audit: Audit) -> dict:
        try:
            fetched = safe_get(audit.url, **fetch_options())
        except BodyTooLarge as exc:
            return {**page_facts(exc.partial, exc.redirects), "truncated": True}
        except (ValueError, requests.RequestException) as exc:
            raise source_error(audit.url, exc) from None
        return {**page_facts(fetched.content, fetched.redirects), "truncated": False}

    def validate(self, raw: dict) -> None:
        missing = [key for key in FACT_KEYS if key not in raw]
        if missing:
            raise SourceError(ErrorCode.INVALID, f"facts missing: {', '.join(missing)}")

    def process(self, raw: dict) -> dict:
        return {key: raw[key] for key in FACT_KEYS}


def page_facts(content: bytes, redirects: int) -> dict:
    parser = _FactParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    return {
        "title": parser.title.strip() or None,
        "meta_description": parser.meta_description,
        "inline_script_count": parser.inline_scripts,
        "images_without_alt": parser.images_without_alt,
        "image_count": parser.images,
        "page_bytes": len(content),
        "redirect_count": redirects,
        "has_viewport_meta": parser.has_viewport,
    }


class _FactParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta_description, self.has_viewport = "", None, False
        self.inline_scripts = self.images = self.images_without_alt = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self._in_title = tag == "title"
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        elif tag == "img":
            self.images += 1
            self.images_without_alt += "alt" not in values
        elif tag == "meta":
            self._meta((values.get("name") or "").lower(), values.get("content"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data

    def _meta(self, name: str, content: str | None) -> None:
        if name == "description":
            self.meta_description = content
        self.has_viewport = self.has_viewport or name == "viewport"
