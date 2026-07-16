from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.ingestion.source_adapters import (
    DomSourceAdapter,
    FetchErrorCode,
    SourceAdapterError,
    build_default_source_adapters,
    get_source_registry,
)
from app.ingestion.text_normalization import source_hash


FIXTURES = Path(__file__).parent / "fixtures" / "source_adapters"


@dataclass(frozen=True)
class AdapterFixtureCase:
    adapter_id: str
    url: str
    chapter_url: str
    fixture_name: str
    title: str
    author: str
    chapter_number: int
    chapter_text_prefix: str


CASES = (
    AdapterFixtureCase(
        "biquge",
        "https://www.biquge.tw/book/1/",
        "https://www.biquge.tw/book/1/12.html",
        "biquge.html",
        "碧阁试读",
        "南风",
        12,
        "雨后的石阶泛着微光",
    ),
    AdapterFixtureCase(
        "uukanshu",
        "https://www.uukanshu.cc/book/1/",
        "https://www.uukanshu.cc/book/1/13.html",
        "uukanshu.html",
        "优看书试读",
        "北辰",
        13,
        "城门外的风吹过旌旗",
    ),
    AdapterFixtureCase(
        "17k",
        "https://www.17k.com/book/1.html",
        "https://www.17k.com/chapter/1/14.html",
        "17k.html",
        "十七章试读",
        "青禾",
        14,
        "晨钟响起时少年推开窗",
    ),
    AdapterFixtureCase(
        "52shuku",
        "https://www.52shuku.net/book/1/",
        "https://www.52shuku.net/book/1/15.html",
        "52shuku.html",
        "五二书库试读",
        "云岚",
        15,
        "药香从屋檐下缓缓散开",
    ),
    AdapterFixtureCase(
        "fanqienovel",
        "https://www.fanqienovel.com/page/1",
        "https://www.fanqienovel.com/reader/16",
        "fanqienovel.html",
        "番茄试读",
        "星河",
        16,
        "夜航船越过平静的江面",
    ),
    AdapterFixtureCase(
        "jjwxc",
        "https://www.jjwxc.net/onebook.php?novelid=1",
        "https://www.jjwxc.net/onebook.php?novelid=1&chapterid=17",
        "jjwxc.html",
        "晋江试读",
        "白露",
        17,
        "庭院里的桂花落在书页上",
    ),
    AdapterFixtureCase(
        "qidian",
        "https://www.qidian.com/book/1/",
        "https://www.qidian.com/chapter/1/18/",
        "qidian.html",
        "起点试读",
        "长夜",
        18,
        "远山尽头升起第一缕晨光",
    ),
    AdapterFixtureCase(
        "novel543",
        "https://www.novel543.com/book/1/",
        "https://www.novel543.com/book/1/19.html",
        "novel543.html",
        "小说五四三试读",
        "微雨",
        19,
        "渡口的灯笼映在水面上",
    ),
    AdapterFixtureCase(
        "hetushu",
        "https://www.hetushu.com/book/1/",
        "https://www.hetushu.com/book/1/chapter_20.html",
        "hetushu.html",
        "和图书试读",
        "松风",
        20,
        "藏书楼的木门在风中轻响",
    ),
    AdapterFixtureCase(
        "ixdzs8",
        "https://www.ixdzs8.com/book/1/",
        "https://www.ixdzs8.com/book/1/chapter_21.html",
        "ixdzs8.html",
        "爱下电子书试读",
        "临川",
        21,
        "雨丝落在青瓦上没有声音",
    ),
    AdapterFixtureCase(
        "xbanxia",
        "https://www.xbanxia.com/book/1/",
        "https://www.xbanxia.com/book/1/22.html",
        "xbanxia.html",
        "半夏试读",
        "归舟",
        22,
        "山谷的雾气慢慢漫过桥头",
    ),
    AdapterFixtureCase(
        "bookqq",
        "https://book.qq.com/book/1/",
        "https://book.qq.com/book/1/chapter/23",
        "bookqq.html",
        "腾讯书城试读",
        "墨池",
        23,
        "翻开的地图停在旧城北门",
    ),
)

EXPECTED_DEDICATED_DOMAINS = {
    "69shuba.com",
    "69shuba.cx",
    "69shux.com",
    "69shumi.com",
    "69shumi.net",
    "biquge.tw",
    "22biqu.com",
    "uukanshu.cc",
    "17k.com",
    "52shuku.net",
    "fanqienovel.com",
    "jjwxc.net",
    "qidian.com",
    "novel543.com",
    "hetushu.com",
    "ixdzs.com",
    "ixdzs8.com",
    "xbanxia.cc",
    "xbanxia.com",
    "book.qq.com",
}


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_every_dedicated_registry_adapter_uses_the_dom_contract() -> None:
    adapters = [adapter for adapter in build_default_source_adapters() if getattr(adapter, "domains", ())]

    assert all(isinstance(adapter, DomSourceAdapter) for adapter in adapters)
    assert {domain for adapter in adapters for domain in adapter.domains} == EXPECTED_DEDICATED_DOMAINS
    fallback_ids = {adapter.adapter_id for adapter in adapters if adapter._regex_fallback is not None}
    assert fallback_ids == {"69shuba", "69shumi"}


@pytest.mark.parametrize("domain", sorted(EXPECTED_DEDICATED_DOMAINS))
def test_every_dedicated_domain_resolves_to_a_versioned_dom_adapter(domain: str) -> None:
    adapter = get_source_registry().get_for_url(f"https://www.{domain}/book/1/")

    assert isinstance(adapter, DomSourceAdapter)
    assert adapter.adapter_version.endswith("-dom-v1")
    assert adapter.domain_policy(f"https://www.{domain}/book/1/")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.adapter_id)
def test_registered_adapter_fixture_obeys_versioned_dom_contract(case: AdapterFixtureCase) -> None:
    adapter = get_source_registry().get_for_url(case.url)
    assert isinstance(adapter, DomSourceAdapter)

    html = _fixture(case.fixture_name)
    preview = adapter.preview_from_html(case.url, html)
    chapter = adapter.chapter_from_html(case.chapter_url, html)

    assert adapter.adapter_id == case.adapter_id
    assert adapter.adapter_version.endswith("-dom-v1")
    assert adapter.domain_policy(case.url)
    assert preview.title == case.title
    assert preview.author == case.author
    assert len(preview.chapters) == 2
    assert all(chapter_item.url.startswith(f"https://{case.url.split('/')[2]}") for chapter_item in preview.chapters)
    assert preview.parser_method == "dom"
    assert chapter.title == f"第{case.chapter_number}章 试读"
    assert chapter.chapter_number == case.chapter_number
    assert chapter.text.startswith(case.chapter_text_prefix)
    assert "上一章" not in chapter.text
    assert "广告" not in chapter.text
    assert chapter.content_hash == source_hash(chapter.text)
    assert chapter.parser_method == "dom"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.adapter_id)
def test_registered_adapter_maps_status_200_challenge_to_typed_error(case: AdapterFixtureCase) -> None:
    adapter = get_source_registry().get_for_url(case.url)

    with pytest.raises(SourceAdapterError) as raised:
        adapter.chapter_from_html(
            case.chapter_url,
            "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>",
        )

    assert raised.value.code is FetchErrorCode.USER_VERIFICATION_REQUIRED
    assert not raised.value.retryable


def test_dom_adapter_without_fixture_proven_regex_fallback_returns_typed_parse_error() -> None:
    adapter = get_source_registry().get_for_url("https://www.17k.com/book/1.html")
    assert isinstance(adapter, DomSourceAdapter)

    with pytest.raises(SourceAdapterError) as raised:
        adapter.chapter_from_html(
            "https://www.17k.com/chapter/1/2.html",
            "<html><body><h1>第2章 缺少正文</h1></body></html>",
        )

    assert raised.value.code is FetchErrorCode.PARSE_FAILED
