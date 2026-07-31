from __future__ import annotations

import pytest


def _fake_cookie_jar():
    return type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()


def _resolver(mapping: dict[str, list[str]]):
    def resolve(hostname: str, port: int) -> list[str]:
        return mapping.get(hostname, ["93.184.216.34"])

    return resolve


class RedirectResponse:
    status_code = 302
    encoding = None
    apparent_encoding = None

    def __init__(self, location: str) -> None:
        self.headers = {"Location": location}


class HtmlResponse:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    encoding = None
    apparent_encoding = None

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield from self._chunks


def test_fetch_blocks_redirect_from_public_to_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, url, *args, **kwargs):
            assert kwargs["allow_redirects"] is False
            return RedirectResponse("https://private.example/book/1")

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceAdapterError) as exc:
        source_adapters.fetch_public_html_result(
            "https://www.69shuba.com/book/1/",
            resolver=_resolver({"www.69shuba.com": ["93.184.216.34"], "private.example": ["10.0.0.2"]}),
        )

    assert exc.value.code is FetchErrorCode.PRIVATE_NETWORK_BLOCKED


def test_fetch_blocks_redirect_to_domain_outside_original_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, *args, **kwargs):
            return RedirectResponse("https://www.biquge.tw/book/1/")

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceAdapterError) as exc:
        source_adapters.fetch_public_html_result(
            "https://www.69shuba.com/book/1/",
            resolver=_resolver({"www.69shuba.com": ["93.184.216.34"], "www.biquge.tw": ["93.184.216.35"]}),
        )

    assert exc.value.code is FetchErrorCode.SOURCE_NOT_ALLOWED


def test_fetch_stops_when_response_exceeds_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, *args, **kwargs):
            return HtmlResponse([b"a" * 4, b"b" * 4])

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceAdapterError) as exc:
        source_adapters.fetch_public_html_result(
            "https://www.69shuba.com/book/1/",
            resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}),
            max_response_bytes=5,
        )

    assert exc.value.code is FetchErrorCode.CONTENT_INVALID
    assert exc.value.http_status == 413


def test_fetch_too_many_redirects_has_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters
    from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = _fake_cookie_jar()

        def get(self, *args, **kwargs):
            return RedirectResponse("https://www.69shuba.com/book/1/")

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceAdapterError) as exc:
        source_adapters.fetch_public_html_result(
            "https://www.69shuba.com/book/1/",
            resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}),
            max_redirects=1,
        )

    assert exc.value.code is FetchErrorCode.SOURCE_UNAVAILABLE
    assert "redirect" in exc.value.safe_message.lower()


@pytest.mark.asyncio
async def test_stealth_browser_validates_top_level_url_before_page_goto(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.security.url_policy import UrlPolicyViolation
    from app.utils import stealth_browser

    def deny_url(*args, **kwargs):
        raise UrlPolicyViolation("blocked before browser", code="private_network_blocked")

    monkeypatch.setattr(stealth_browser, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(stealth_browser, "validate_fetch_url", deny_url)

    browser = stealth_browser.StealthBrowser()

    with pytest.raises(UrlPolicyViolation):
        await browser.fetch_with_stealth("http://127.0.0.1/admin")
