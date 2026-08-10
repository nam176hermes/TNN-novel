from __future__ import annotations

import pytest

from app.ingestion.source_adapters import (
    GenericHtmlSourceAdapter,
    SelectorSourceAdapter,
    SourceAdapterError,
    SourceBlockedError,
    get_source_registry,
    list_source_capabilities,
    raise_if_cooldown_page,
    validate_public_http_url,
)
from app.ingestion.source_policies import chapter_url_matches_source_book, get_source_policy, is_allowed_source_url


def test_generic_html_adapter_extracts_preview_and_chapters() -> None:
    adapter = GenericHtmlSourceAdapter()
    html = """
    <html>
      <head>
        <title>凡人修仙传 - Example</title>
        <meta name="author" content="忘语">
        <meta name="description" content="修仙小说">
      </head>
      <body>
        <h1>凡人修仙传</h1>
        <a href="/book/1/chapter/1">第一章 山边小村</a>
        <a href="/book/1/chapter/2">第二章 青牛镇</a>
        <a href="/book/1/catalog">目录</a>
      </body>
    </html>
    """

    preview = adapter.preview_from_html("https://www.69shuba.com/book/1/", html)

    assert preview.title == "凡人修仙传"
    assert preview.author == "忘语"
    assert preview.description == "修仙小说"
    assert [chapter.chapter_number for chapter in preview.chapters] == [1, 2]
    assert preview.chapters[0].url == "https://www.69shuba.com/book/1/chapter/1"


def test_generic_html_adapter_extracts_chapter_content() -> None:
    adapter = GenericHtmlSourceAdapter()
    html = """
    <html>
      <body>
        <nav>上一章 返回目录 下一章</nav>
        <h1>第一章 山边小村</h1>
        <div id="content">
          <p>张铁睁开双眼，发现自己躺在一间破旧的茅草屋里。</p>
          <p>他揉了揉眼睛，确信自己不是在梦中。</p>
          <p>丹田之内一阵刺痛传来，他不由得闷哼一声。</p>
        </div>
      </body>
    </html>
    """

    chapter = adapter.chapter_from_html("https://www.69shuba.com/book/1/chapter/1", html)

    assert chapter.chapter_number == 1
    assert chapter.title == "第一章 山边小村"
    assert "张铁睁开双眼" in chapter.text
    assert "返回目录" not in chapter.text


def test_validate_public_http_url_rejects_private_targets() -> None:
    with pytest.raises(SourceAdapterError):
        validate_public_http_url("http://127.0.0.1/book")

    with pytest.raises(SourceAdapterError):
        validate_public_http_url("file:///tmp/book.html")


def test_private_ipv4_ipv6_cgnat_and_link_local_targets_never_reach_browser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import source_adapters

    blocked_addresses = (
        "127.0.0.1",
        "10.0.0.8",
        "100.64.0.9",
        "169.254.169.254",
        "::1",
        "fd00::8",
        "fe80::1",
    )
    browser_calls: list[str] = []

    class BlockedResponse:
        status_code = 403
        headers = {"server": "cloudflare", "Content-Type": "text/html"}

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = type(
                "Cookies",
                (),
                {"get_dict": lambda _self: {}, "set": lambda _self, *_args, **_kwargs: None},
            )()

        def get(self, *_args, **_kwargs):
            return BlockedResponse()

    def browser_fallback(url: str, *_args, **_kwargs) -> str:
        browser_calls.append(url)
        return "<html><h1>browser must not receive blocked targets</h1></html>"

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(source_adapters, "apply_cookies_to_session", lambda *_args: None)
    monkeypatch.setattr(source_adapters, "_call_stealth_fallback", browser_fallback)

    for address in blocked_addresses:
        with pytest.raises(SourceAdapterError) as caught:
            source_adapters.fetch_public_html_result(
                "https://www.69shuba.com/book/1/",
                resolver=lambda _hostname, _port, resolved=address: (resolved,),
            )
        assert caught.value.code is source_adapters.FetchErrorCode.PRIVATE_NETWORK_BLOCKED

    assert browser_calls == []


def test_public_to_private_redirect_is_rejected_before_browser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import source_adapters

    browser_calls: list[str] = []

    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://edge.69shuba.com/book/1/"}

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = type(
                "Cookies",
                (),
                {"get_dict": lambda _self: {}, "set": lambda _self, *_args, **_kwargs: None},
            )()

        def get(self, *_args, **_kwargs):
            return RedirectResponse()

    def resolver(hostname: str, _port: int) -> tuple[str, ...]:
        return ("10.10.0.7",) if hostname == "edge.69shuba.com" else ("93.184.216.34",)

    def browser_fallback(url: str, *_args, **_kwargs) -> str:
        browser_calls.append(url)
        return "<html><h1>browser must not receive redirect targets</h1></html>"

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(source_adapters, "apply_cookies_to_session", lambda *_args: None)
    monkeypatch.setattr(source_adapters, "_call_stealth_fallback", browser_fallback)

    with pytest.raises(SourceAdapterError) as caught:
        source_adapters.fetch_public_html_result(
            "https://www.69shuba.com/book/1/",
            resolver=resolver,
        )

    assert caught.value.code is source_adapters.FetchErrorCode.PRIVATE_NETWORK_BLOCKED
    assert browser_calls == []


def test_source_policy_allows_known_cn_novel_domains() -> None:
    assert is_allowed_source_url("https://www.69shuba.com/book/123/")
    assert is_allowed_source_url("https://www.biquge.tw/book/456/")
    assert is_allowed_source_url("https://www.22biqu.com/biqu123/")
    assert is_allowed_source_url("https://uukanshu.cc/book/123/")
    assert is_allowed_source_url("https://www.17k.com/book/123.html")
    # New sources added from excerpo integration
    assert is_allowed_source_url("https://www.69shumi.net/book/123")
    assert is_allowed_source_url("https://www.qidian.com/book/123")
    assert is_allowed_source_url("https://www.jjwxc.net/onebook.php?novelid=123")
    assert is_allowed_source_url("https://fanqienovel.com/page/123456")
    assert is_allowed_source_url("https://www.pixiv.net/novel/series/12345")
    assert is_allowed_source_url("https://ncode.syosetu.com/n1234ab/")
    assert is_allowed_source_url("https://kakuyomu.jp/works/12345678901234567890")


def test_source_policy_rejects_unknown_public_domain() -> None:
    assert not is_allowed_source_url("https://example-news-site.com/book/123")
    assert not is_allowed_source_url("https://www.random-novel-site.org/book/123")
    assert not is_allowed_source_url("https://novel-xyz-read.net/chapter/456")
    assert not is_allowed_source_url("https://www.fictionpress-read.com/story/123")


def test_source_policy_returns_polite_defaults() -> None:
    policy = get_source_policy("https://www.69shuba.com/book/123/")
    assert policy is not None
    assert policy.source_id == "69shuba"
    assert policy.max_concurrency == 1
    assert policy.delay_seconds >= 5
    assert policy.retry_limit >= 1


def test_source_capabilities_map_policies_to_available_adapters() -> None:
    capabilities = {source["source_id"]: source for source in list_source_capabilities()}

    assert capabilities["69shuba"]["adapter_id"] == "69shuba"
    assert capabilities["69shuba"]["extraction"] == "selector"
    assert capabilities["22biqu"]["adapter_id"] == "biquge"
    assert capabilities["22biqu"]["domains"] == ["22biqu.com"]
    assert capabilities["kakuyomu"]["adapter_id"] == "kakuyomu"
    assert capabilities["kakuyomu"]["extraction"] == "selector"


def test_validate_public_http_url_rejects_non_allowlisted_domains() -> None:
    with pytest.raises(SourceAdapterError, match="Unsupported source domain"):
        validate_public_http_url("https://example.com/book/1")


def test_chapter_url_same_book_validation_rejects_loose_numeric_matches() -> None:
    assert not chapter_url_matches_source_book(
        "https://www.69shuba.com/book/123/",
        "https://www.69shuba.com/book/999/chapter/123",
    )
    assert not chapter_url_matches_source_book(
        "https://www.69shuba.com/book-123/",
        "https://www.69shuba.com/other-123/chapter/1",
    )
    assert not chapter_url_matches_source_book(
        "https://www.69shuba.com/book",
        "https://www.69shuba.com/book/123/chapter/1",
    )


def test_chapter_url_same_book_validation_accepts_canonical_source_paths() -> None:
    assert chapter_url_matches_source_book(
        "https://www.69shuba.com/book/123/",
        "https://www.69shuba.com/book/123/chapter/1",
    )
    assert chapter_url_matches_source_book(
        "https://www.17k.com/book/123.html",
        "https://www.17k.com/chapter/123/456.html",
    )


def test_selector_adapter_extracts_preview_and_chapters() -> None:
    html = """
    <html><body>
      <h1 class="book-title">凡人修仙传</h1>
      <span class="author">作者：忘语</span>
      <div class="intro">一个凡人的修仙故事。</div>
      <div id="list">
        <dd><a href="/book/1/1.html">第1章 山边小村</a></dd>
        <dd><a href="/book/1/2.html">第2章 青牛镇</a></dd>
      </div>
    </body></html>
    """
    adapter = SelectorSourceAdapter(
        adapter_id="test_selector",
        label="Test Selector",
        domains=("69shuba.com",),
        title_patterns=(r'<h1 class="book-title">(.*?)</h1>',),
        author_patterns=(r'<span class="author">作者：(.*?)</span>',),
        description_patterns=(r'<div class="intro">(.*?)</div>',),
        chapter_link_patterns=(r'<a href="([^"]+)">(第\d+章[^<]+)</a>',),
        content_patterns=(r'<div id="content">(.*?)</div>',),
    )

    preview = adapter.preview_from_html("https://www.69shuba.com/book/1/", html)
    assert preview.adapter_id == "test_selector"
    assert preview.title == "凡人修仙传"
    assert preview.author == "忘语"
    assert preview.description == "一个凡人的修仙故事。"
    assert len(preview.chapters) == 2
    assert preview.chapters[0].url == "https://www.69shuba.com/book/1/1.html"
    assert preview.policy == {
        "source_id": "69shuba",
        "label": "69shuba",
        "delay_seconds": 8,
        "max_concurrency": 1,
        "retry_limit": 2,
    }


def test_selector_adapter_parses_large_chinese_chapter_numbers() -> None:
    html = """
    <html><body>
      <h1>凡人修仙传</h1>
      <a href="/book/1/120.html">第一百二十章 风起</a>
      <a href="/book/1/123.html">第一百二十三章 云涌</a>
    </body></html>
    """
    adapter = SelectorSourceAdapter(
        adapter_id="test_selector",
        label="Test Selector",
        domains=("69shuba.com",),
        title_patterns=(r"<h1[^>]*>(.*?)</h1>",),
        chapter_link_patterns=(r'<a href="([^"]+)">(第[^<]+章[^<]+)</a>',),
        content_patterns=(r'<div id="content">(.*?)</div>',),
    )

    preview = adapter.preview_from_html("https://www.69shuba.com/book/1/", html)

    assert [chapter.chapter_number for chapter in preview.chapters] == [120, 123]


def test_selector_adapter_preserves_paragraph_breaks_in_chapter_content() -> None:
    html = """
    <html><body>
      <h1>第一百二十三章 云涌</h1>
      <div id="content">
        <p>张铁睁开双眼，发现窗外风声渐急。</p>
        <p>他走到门前，看见云雾从山谷深处涌来。</p>
      </div>
    </body></html>
    """
    adapter = SelectorSourceAdapter(
        adapter_id="test_selector",
        label="Test Selector",
        domains=("69shuba.com",),
        title_patterns=(r"<h1[^>]*>(.*?)</h1>",),
        chapter_link_patterns=(r'<a href="([^"]+)">(第[^<]+章[^<]+)</a>',),
        content_patterns=(r'<div id="content">(.*?)</div>',),
    )

    chapter = adapter.chapter_from_html("https://www.69shuba.com/book/1/123.html", html)

    assert chapter.chapter_number == 123
    assert "张铁睁开双眼，发现窗外风声渐急。\n\n他走到门前，看见云雾从山谷深处涌来。" in chapter.text


def test_registry_uses_site_adapters_before_generic() -> None:
    registry = get_source_registry()
    assert registry.get_for_url("https://www.69shuba.com/book/123/").adapter_id == "69shuba"
    assert registry.get_for_url("https://www.biquge.tw/book/123/").adapter_id == "biquge"
    assert registry.get_for_url("https://www.17k.com/book/123.html").adapter_id == "17k"


def test_raise_if_cooldown_page_detects_chinese_anti_spam_message() -> None:
    with pytest.raises(SourceAdapterError, match="Source cooldown"):
        raise_if_cooldown_page("https://www.69shuba.com/book/1/", "访问过于频繁，请稍后再试")


def test_fetch_public_html_rejects_redirect_to_different_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters

    class FakeResponse:
        status_code = 302
        headers = {"Location": "https://www.biquge.tw/book/1/"}

    class FakeSession:
        def __init__(self):
            self.cookies = type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceAdapterError, match="redirect changed"):
        source_adapters.fetch_public_html("https://www.69shuba.com/book/1/")


def test_fetch_public_html_reports_cloudflare_challenge_as_blocked_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import source_adapters

    class FakeResponse:
        status_code = 403
        headers = {"cf-mitigated": "challenge", "server": "cloudflare", "Content-Type": "text/html"}

        def raise_for_status(self) -> None:
            raise AssertionError("blocked responses should be handled before raise_for_status")

    class FakeSession:
        def __init__(self):
            self.cookies = type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    with pytest.raises(SourceBlockedError, match="Cloudflare challenge"):
        source_adapters.fetch_public_html(
            "https://www.69shuba.com/book/58851.htm",
            allow_browser_fallback=False,
        )


def test_fetch_public_html_decodes_gbk_meta_charset(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import source_adapters

    html = '<html><head><meta charset="gb2312"></head><body><h1>凡人修仙传</h1></body></html>'

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield html.encode("gb18030")

    class FakeSession:
        def __init__(self):
            self.cookies = type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    assert "凡人修仙传" in source_adapters.fetch_public_html("https://www.69shuba.com/book/1/")


def test_fetch_public_html_prefers_apparent_gbk_over_latin1_response_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import source_adapters

    html = "<html><body><h1>凡人修仙传</h1></body></html>"

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = "ISO-8859-1"
        apparent_encoding = "GB2312"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield html.encode("gb18030")

    class FakeSession:
        def __init__(self):
            self.cookies = type("C", (), {"get_dict": lambda s: {}, "set": lambda s, *a, **kw: None})()
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)

    assert "凡人修仙传" in source_adapters.fetch_public_html("https://www.69shuba.com/book/1/")
