from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from app.ingestion.source_adapters import (
    DomSourceAdapter,
    FetchErrorCode,
    SourceAdapterError,
    get_source_registry,
)


FIXTURES = Path(__file__).parent / "fixtures" / "69shuba"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _adapter(url: str = "https://www.69shuba.com/book/1/") -> DomSourceAdapter:
    adapter = get_source_registry().get_for_url(url)
    assert isinstance(adapter, DomSourceAdapter)
    return adapter


@pytest.mark.parametrize(
    ("url", "adapter_id"),
    [
        ("https://www.69shuba.com/book/1/", "69shuba"),
        ("https://www.69shuba.cx/book/1/", "69shuba"),
        ("https://www.69shux.com/book/1/", "69shuba"),
        ("https://www.69shumi.com/book/1/", "69shumi"),
        ("https://www.69shumi.net/book/1/", "69shumi"),
    ],
)
def test_69shuba_family_uses_versioned_dom_adapter(url: str, adapter_id: str) -> None:
    adapter = _adapter(url)

    assert adapter.adapter_id == adapter_id
    assert adapter.adapter_version
    assert adapter.domain_policy(url)
    assert adapter.canonicalize_url(url).startswith(url.rstrip("/"))


def test_dom_preview_extracts_metadata_and_relative_absolute_links() -> None:
    adapter = _adapter()

    preview = adapter.preview_from_html(
        "https://www.69shuba.com/book/1/",
        _fixture("preview_normal.html"),
    )

    assert preview.title == "凡人修仙传 & 外传"
    assert preview.author == "忘语"
    assert preview.description == "一个凡人的修仙故事 & 山海见闻。"
    assert preview.cover_url == "https://www.69shuba.com/static/cover.jpg"
    assert preview.adapter_version == "69shuba-dom-v1"
    assert preview.parser_method == "dom"
    assert [(chapter.chapter_number, chapter.title, chapter.url) for chapter in preview.chapters] == [
        (1, "第一章 山边小村", "https://www.69shuba.com/book/1/1.html"),
        (2, "第二章 青牛镇 & 风云", "https://www.69shuba.com/book/1/2.html"),
    ]


def test_dom_preview_uses_selector_fallbacks_when_primary_layout_is_missing() -> None:
    preview = _adapter("https://www.69shuba.cx/book/2/").preview_from_html(
        "https://www.69shuba.cx/book/2/",
        _fixture("preview_selector_fallback.html"),
    )

    assert preview.title == "凡人修仙传（备用布局）"
    assert preview.author == "忘语"
    assert [chapter.chapter_number for chapter in preview.chapters] == [10, 11]


@pytest.mark.parametrize("domain", ["69shumi.com", "69shumi.net"])
def test_69shumi_dom_config_parses_preview_and_chapter(domain: str) -> None:
    adapter = _adapter(f"https://www.{domain}/book/7/")
    preview = adapter.preview_from_html(
        f"https://www.{domain}/book/7/",
        _fixture("preview_69shumi.html"),
    )
    chapter = adapter.chapter_from_html(
        f"https://www.{domain}/book/7/31.html",
        _fixture("chapter_69shumi.html"),
    )

    assert preview.title == "仙途旧梦"
    assert preview.author == "林海"
    assert preview.chapters[0].chapter_number == 31
    assert chapter.chapter_number == 31
    assert chapter.text.startswith("山路尽头灯火渐明")


def test_chapter_title_selector_wins_over_book_title() -> None:
    chapter = _adapter().chapter_from_html(
        "https://www.69shuba.com/book/1/32.html",
        """
        <html><body><h1 class="book-title">凡人修仙传</h1>
        <h1 class="chapter-title">第三十二章 夜归</h1><div id="content">
        <p>夜色落在山路上，归来的人放慢脚步听着松涛。</p>
        <p>远处灯火仍亮，他知道故人还在等待。</p></div></body></html>
        """,
    )

    assert chapter.title == "第三十二章 夜归"
    assert chapter.chapter_number == 32


def test_removed_content_subtree_cannot_win_primary_selector() -> None:
    chapter = _adapter().chapter_from_html(
        "https://www.69shuba.com/book/1/33.html",
        """
        <html><body><h1>第三十三章 真正内容</h1>
        <div class="advertisement"><div id="content">广告</div></div>
        <div class="chapter-content"><p>真正的章节从这里开始，山风吹过安静的庭院。</p>
        <p>檐下的人抬起头，看见云层后露出的月光。</p></div></body></html>
        """,
    )

    assert chapter.text.startswith("真正的章节从这里开始")


def test_unsafe_cover_scheme_is_discarded() -> None:
    preview = _adapter().preview_from_html(
        "https://www.69shuba.com/book/8/",
        """
        <html><head><meta property="og:image" content="javascript:alert(1)"></head>
        <body><h1 class="book-title">安全封面</h1><div id="list">
        <a href="/book/8/1.html">第一章 开始</a></div></body></html>
        """,
    )

    assert preview.cover_url == ""


def test_dom_chapter_normalizes_entities_unicode_and_removes_junk() -> None:
    chapter = _adapter().chapter_from_html(
        "https://www.69shuba.com/book/1/12.html",
        _fixture("chapter_normal.html"),
    )

    assert chapter.chapter_number == 12
    assert chapter.title == "第十二章 山雨欲来"
    assert chapter.text == (
        "韩立凝神望向山谷，风声从远处传来。\n\n"
        "青石路上落满细雨，他仍缓步向前。\n\n"
        "“今日之后，”老人说道，“莫要回头。” Café"
    )
    assert "上一章" not in chapter.text
    assert "advertisement" not in chapter.text
    assert "privatePayload" not in chapter.text
    assert "private-style-marker" not in chapter.text
    assert chapter.content_hash == hashlib.sha256(chapter.text.encode("utf-8")).hexdigest()
    assert chapter.adapter_version == "69shuba-dom-v1"
    assert chapter.parser_method == "dom"


def test_dom_chapter_uses_secondary_content_selector() -> None:
    chapter = _adapter().chapter_from_html(
        "https://www.69shuba.com/book/1/20.html",
        _fixture("chapter_selector_fallback.html"),
    )

    assert chapter.chapter_number == 20
    assert chapter.text.startswith("林中雾气渐浓")
    assert "\n\n" in chapter.text


def test_regex_fallback_is_telemetry_visible_without_page_content(caplog: pytest.LogCaptureFixture) -> None:
    adapter = _adapter()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.source_adapters"):
        chapter = adapter.chapter_from_html(
            "https://www.69shuba.com/book/1/21.html",
            _fixture("chapter_regex_fallback.html"),
        )

    assert chapter.chapter_number == 21
    assert chapter.text.startswith("晨光穿过云层")
    assert chapter.parser_method == "regex_fallback"
    assert any("dom_parser_fallback" in record.message for record in caplog.records)
    assert all("晨光穿过云层" not in record.message for record in caplog.records)


def test_preview_regex_fallback_preserves_compatibility_and_telemetry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.ingestion.source_adapters"):
        preview = _adapter().preview_from_html(
            "https://www.69shuba.com/book/9/",
            _fixture("preview_regex_fallback.html"),
        )

    assert [chapter.chapter_number for chapter in preview.chapters] == [1, 2]
    assert preview.parser_method == "regex_fallback"
    assert any("target=preview" in record.message for record in caplog.records)


def test_preview_semantic_mismatch_uses_regex_fallback() -> None:
    preview = _adapter().preview_from_html(
        "https://www.69shuba.com/book/10/",
        _fixture("preview_semantic_fallback.html"),
    )

    assert [chapter.chapter_number for chapter in preview.chapters] == [1, 2]
    assert preview.parser_method == "regex_fallback"


def test_public_content_validator_maps_internal_errors_to_typed_contract() -> None:
    with pytest.raises(SourceAdapterError) as raised:
        _adapter().validate_content("   ")

    assert raised.value.code is FetchErrorCode.CONTENT_INVALID
    assert not raised.value.retryable


@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("not_found.html", FetchErrorCode.CONTENT_NOT_FOUND),
        ("challenge_200.html", FetchErrorCode.USER_VERIFICATION_REQUIRED),
        ("chapter_gateway_502.html", FetchErrorCode.SOURCE_UNAVAILABLE),
        ("chapter_error_500.html", FetchErrorCode.SOURCE_UNAVAILABLE),
        ("chapter_error_522.html", FetchErrorCode.SOURCE_UNAVAILABLE),
        ("chapter_forbidden_403.html", FetchErrorCode.SOURCE_UNAVAILABLE),
        ("chapter_empty.html", FetchErrorCode.CONTENT_INVALID),
        ("chapter_too_short.html", FetchErrorCode.CONTENT_INVALID),
        ("chapter_list_as_content.html", FetchErrorCode.CONTENT_INVALID),
        ("chapter_plain_list.html", FetchErrorCode.CONTENT_INVALID),
        ("chapter_boilerplate.html", FetchErrorCode.CONTENT_INVALID),
        ("chapter_regex_boilerplate.html", FetchErrorCode.CONTENT_INVALID),
    ],
)
def test_dom_content_validator_rejects_invalid_pages(
    fixture_name: str,
    expected_code: FetchErrorCode,
) -> None:
    with pytest.raises(SourceAdapterError) as raised:
        _adapter().chapter_from_html(
            "https://www.69shuba.com/book/1/99.html",
            _fixture(fixture_name),
        )

    assert raised.value.code is expected_code
    assert raised.value.retryable is (expected_code is FetchErrorCode.SOURCE_UNAVAILABLE)


def test_chapter_number_404_is_not_misclassified_as_not_found() -> None:
    chapter = _adapter().chapter_from_html(
        "https://www.69shuba.com/book/1/404.html",
        """
        <html><head><title>第404章 山中来信 - 69书吧</title></head><body>
          <h1>第404章 山中来信</h1><div id="content">
            <p>山中来信辗转数月，终于在清晨送到了韩立手中。</p>
            <p>他拆开封口，逐字读完，又将信纸妥善收进袖中。</p>
          </div>
        </body></html>
        """,
    )

    assert chapter.chapter_number == 404
    assert chapter.text.startswith("山中来信")


def test_deep_dom_is_a_typed_parse_failure_not_recursion_error() -> None:
    html = "<html><body><h1>第一章 深层页面</h1><div id='content'>" + "<div>" * 1_500
    html += "正文内容足够长，且不应导致解析线程出现未捕获的递归错误。"
    html += "</div>" * 1_500 + "</div></body></html>"

    with pytest.raises(SourceAdapterError) as raised:
        _adapter().parse_chapter("https://www.69shuba.com/book/1/1.html", html)

    assert raised.value.code is FetchErrorCode.PARSE_FAILED


def test_dom_adapter_rejects_cross_domain_canonicalization() -> None:
    adapter = _adapter()

    with pytest.raises(SourceAdapterError) as raised:
        adapter.canonicalize_url("https://www.biquge.tw/book/1/")

    assert raised.value.code is FetchErrorCode.SOURCE_NOT_ALLOWED
