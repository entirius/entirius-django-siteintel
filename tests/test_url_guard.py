# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import socket

import pytest

from django_siteintel.enums import ErrorCode, ReportStatus
from django_siteintel.models import Audit, Report
from django_siteintel.security import BodyTooLarge, safe_get
from django_siteintel.services import report_service
from django_siteintel.sources.base import SourceError
from tests.fake_http import FakeHttp, FakeResponse

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    """shop.example → public IP; internal.example → 10.0.0.1."""
    table = {"shop.example": PUBLIC_IP, "internal.example": "10.0.0.1", "10.0.0.1": "10.0.0.1"}

    def resolve(host, *_args):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture
def fake(monkeypatch, dns) -> FakeHttp:
    http = FakeHttp()
    monkeypatch.setattr("requests.get", http.request)
    return http


def _audit(url: str) -> Report:
    audit = Audit.objects.create(
        domain="shop.example", url=url, channel_idx="c", requested_by="t", expires_at="2099-01-01T00:00:00Z"
    )
    return Report.objects.create(audit=audit, source="heuristic")


def test_S05_private_host_and_redirect_to_10x_refused_per_hop(fake, db):
    fake.add("https://shop.example/go", FakeResponse(302, headers={"Location": "http://10.0.0.1/admin"}))

    with pytest.raises(ValueError, match="internal host"):
        safe_get("https://internal.example/", timeout=1, cap=100)
    with pytest.raises(ValueError, match="internal host"):
        safe_get("https://shop.example/go", timeout=1, cap=100)
    assert fake.calls == ["https://shop.example/go"]  # the 10.x hop was never connected

    report = _audit("https://shop.example/go")
    with pytest.raises(SourceError) as caught:
        report_service.run(report)
    report_service.fail(report, caught.value)
    report.refresh_from_db()
    assert (report.status, report.error_code) == (ReportStatus.FAILED, ErrorCode.SSRF)
    assert report.error_detail == "shop.example: ValueError"


def test_S06_page_over_cap_partial_truncated(fake, db, settings):
    settings.SITEINTEL_MAX_PAGE_BYTES = 1024
    page = b"<html><head><title>Big</title></head><body>" + b"<img src=x>" * 5000 + b"</body></html>"
    fake.add("https://shop.example/", FakeResponse(200, page))

    with pytest.raises(BodyTooLarge) as caught:
        safe_get("https://shop.example/", timeout=1, cap=1024)
    assert len(caught.value.partial) == 1024

    report = _audit("https://shop.example/")
    assert report_service.run(report) is True
    report.refresh_from_db()
    assert (report.status, report.error_code) == (ReportStatus.PARTIAL, ErrorCode.TRUNCATED)
    assert report.processed["page_bytes"] == 1024
    assert report.processed["title"] == "Big"
    assert 0 < report.processed["images_without_alt"] < 5000


def test_guard_armed_by_default(settings):
    assert settings.SITEINTEL_BLOCK_PRIVATE_HOSTS is True
