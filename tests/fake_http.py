# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""In-process HTTP double: `requests.get`/`requests.post` answered from a URL → response table."""

import json

import requests


class FakeResponse:
    def __init__(self, status_code: int = 200, body: bytes | dict = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = json.dumps(body).encode() if isinstance(body, dict) else body
        self.headers = headers or {}

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return json.loads(self.content)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass


class FakeHttp:
    """Routes by URL prefix; unknown URLs answer 404. `calls` / `headers` record every request's URL and headers."""

    def __init__(self):
        self.routes: dict[str, list[FakeResponse]] = {}
        self.calls: list[str] = []
        self.headers: list[dict] = []

    def add(self, url_prefix: str, *responses: FakeResponse) -> None:
        """Responses are served in order; the last one repeats."""
        self.routes[url_prefix] = list(responses)

    def request(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(url)
        self.headers.append(kwargs.get("headers") or {})
        for prefix, responses in self.routes.items():
            if url.startswith(prefix):
                return responses.pop(0) if len(responses) > 1 else responses[0]
        return FakeResponse(404)
