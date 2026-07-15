from __future__ import annotations

import threading

import pytest


def _fake_cookie_jar():
    return type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()


def test_fetch_public_html_result_direct_http_contains_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchMethod

    html = "<html><body><h1>凡人修仙传</h1></body></html>"

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = None
        url = "https://www.69shuba.com/book/1/"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield html.encode("utf-8")

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(source_adapters, "raise_if_cooldown_page", lambda url, text: None)

    result = source_adapters.fetch_public_html_result("https://www.69shuba.com/book/1/")

    assert result.html == html
    assert result.requested_url == "https://www.69shuba.com/book/1/"
    assert result.final_url == "https://www.69shuba.com/book/1/"
    assert result.method is FetchMethod.DIRECT_HTTP
    assert result.status_code == 200
    assert result.attempts == 1
    assert result.bytes_received == len(html.encode("utf-8"))
    assert result.elapsed_ms >= 0
    assert result.cookies_refreshed is False
    assert result.cache_hit is False


def test_fetch_public_html_result_stealth_fallback_method_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchMethod

    class FakeBlockedResponse:
        status_code = 403
        headers = {"cf-mitigated": "challenge", "server": "cloudflare", "Content-Type": "text/html"}
        encoding = None
        apparent_encoding = None

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, *args, **kwargs):
            return FakeBlockedResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(
        source_adapters,
        "_try_stealth_fallback",
        lambda url, reason, timeout, requested_url, attempts, started_at: source_adapters.FetchResult(
            html="<html>fallback</html>",
            requested_url=requested_url,
            final_url=url,
            method=FetchMethod.STEALTH_BROWSER_HEADED,
            status_code=200,
            attempts=attempts + 1,
            elapsed_ms=1,
            bytes_received=len("<html>fallback</html>".encode("utf-8")),
            cookies_refreshed=True,
            cache_hit=False,
        ),
    )

    result = source_adapters.fetch_public_html_result("https://www.69shuba.com/book/58851.htm")

    assert result.html == "<html>fallback</html>"
    assert result.method is FetchMethod.STEALTH_BROWSER_HEADED
    assert result.attempts == 2
    assert result.cookies_refreshed is True


def test_fetch_error_mapping_has_code_retryable_and_safe_details() -> None:
    from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError

    error = SourceAdapterError(
        "Source timed out",
        code=FetchErrorCode.CONNECT_TIMEOUT,
        retryable=True,
        http_status=504,
        details={
            "url": "https://www.69shuba.com/book/1/",
            "Authorization": "Bearer secret",
            "cookie": "cf_clearance=secret",
        },
    )

    assert error.code is FetchErrorCode.CONNECT_TIMEOUT
    assert error.retryable is True
    assert error.http_status == 504
    assert error.safe_message == "Source timed out"
    assert error.details["url"] == "https://www.69shuba.com/book/1/"
    assert error.details["Authorization"] == "[redacted]"
    assert error.details["cookie"] == "[redacted]"


def test_concurrent_fetches_do_not_leak_method_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchMethod

    barrier = threading.Barrier(2)

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = None

        def __init__(self, html: str) -> None:
            self.html = html

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            barrier.wait(timeout=5)
            yield self.html.encode("utf-8")

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, url, *args, **kwargs):
            if "58851" in url:
                return FakeResponse("<html>first</html>")
            return FakeResponse("<html>second</html>")

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(source_adapters, "raise_if_cooldown_page", lambda url, text: None)

    results: dict[str, object] = {}

    def fetch(name: str, url: str) -> None:
        results[name] = source_adapters.fetch_public_html_result(url)

    t1 = threading.Thread(target=fetch, args=("first", "https://www.69shuba.com/book/58851.htm"))
    t2 = threading.Thread(target=fetch, args=("second", "https://www.69shuba.com/book/1/"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert results["first"].html == "<html>first</html>"
    assert results["second"].html == "<html>second</html>"
    assert results["first"].method is FetchMethod.DIRECT_HTTP
    assert results["second"].method is FetchMethod.DIRECT_HTTP


def test_fetch_public_html_compatibility_wrapper_returns_html(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters

    monkeypatch.setattr(
        source_adapters,
        "fetch_public_html_result",
        lambda *args, **kwargs: source_adapters.FetchResult(
            html="<html>compat</html>",
            requested_url="https://www.69shuba.com/book/1/",
            final_url="https://www.69shuba.com/book/1/",
            method=source_adapters.FetchMethod.DIRECT_HTTP,
            status_code=200,
            attempts=1,
            elapsed_ms=1,
            bytes_received=len("<html>compat</html>".encode("utf-8")),
            cookies_refreshed=False,
            cache_hit=False,
        ),
    )

    assert source_adapters.fetch_public_html("https://www.69shuba.com/book/1/") == "<html>compat</html>"
