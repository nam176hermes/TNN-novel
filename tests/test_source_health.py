from __future__ import annotations

import socket
from typing import Any

import pytest
import requests

from app.ingestion.source_health import check_source_health


class FakeResponse:
    def __init__(self, *, status_code: int = 200, url: str = "https://www.69shuba.com/book/1", body: bytes = b"<html>ok</html>") -> None:
        self.status_code = status_code
        self.url = url
        self._body = body

    def iter_content(self, chunk_size: int = 1024):
        del chunk_size
        yield self._body


def _entry(url: str, *, supported: bool = True) -> dict[str, Any]:
    return {
        "id": "catalog-1",
        "name": "Catalog Source",
        "url": url,
        "domain": "www.69shuba.com",
        "supported": supported,
        "supported_status": "supported" if supported else "unsupported",
        "supported_source_id": "69shuba" if supported else "",
    }


def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def test_source_health_blocks_localhost_without_network() -> None:
    called = False

    def requester(*args, **kwargs):  # pragma: no cover - should never be called
        nonlocal called
        called = True
        return FakeResponse()

    result = check_source_health(_entry("http://127.0.0.1/source"), request_get=requester)

    assert result.status == "blocked"
    assert result.reason == "private_network_not_allowed"
    assert called is False


def test_source_health_blocks_file_scheme_without_network() -> None:
    result = check_source_health(_entry("file:///etc/passwd"), request_get=lambda *args, **kwargs: FakeResponse())

    assert result.status == "blocked"
    assert result.reason == "unsupported_url_scheme"


def test_source_health_blocks_private_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
    )

    result = check_source_health(_entry("https://www.69shuba.com/book/1"), request_get=lambda *args, **kwargs: FakeResponse())

    assert result.status == "blocked"
    assert result.reason == "private_network_not_allowed"


def test_source_health_returns_unsupported_without_network() -> None:
    called = False

    def requester(*args, **kwargs):  # pragma: no cover - should never be called
        nonlocal called
        called = True
        return FakeResponse()

    result = check_source_health(_entry("https://example.com/source", supported=False), request_get=requester)

    assert result.status == "unsupported"
    assert result.reason == "unsupported_source_policy"
    assert called is False


def test_source_health_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    def timeout_requester(*args, **kwargs):
        raise requests.Timeout("slow")

    result = check_source_health(_entry("https://www.69shuba.com/book/1"), request_get=timeout_requester)

    assert result.status == "timeout"
    assert result.reason == "request_timeout"


def test_source_health_reaches_safe_supported_source_with_limited_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    seen: dict[str, Any] = {}

    def requester(url: str, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return FakeResponse(status_code=200, url=url)

    result = check_source_health(_entry("https://www.69shuba.com/book/1"), request_get=requester)

    assert result.status == "reachable"
    assert result.http_status == 200
    assert result.final_url == "https://www.69shuba.com/book/1"
    assert seen["kwargs"]["allow_redirects"] is False
    assert seen["kwargs"]["timeout"] <= 6
    headers = seen["kwargs"]["headers"]
    assert "Authorization" not in headers
    assert "Cookie" not in headers
