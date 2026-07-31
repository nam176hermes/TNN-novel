from __future__ import annotations

import pytest

from app.ingestion import source_adapters
from app.observability import Observability


def _metric(snapshot: dict, name: str) -> list[dict]:
    return [entry for entry in snapshot["metrics"]["counters"] if entry["name"] == name]


def test_adapter_fetch_records_bounded_response_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    observability = Observability()
    monkeypatch.setattr(source_adapters, "default_observability", observability)
    monkeypatch.setattr(
        source_adapters,
        "fetch_public_html_result",
        lambda _url: source_adapters.FetchResult(
            html="<html><h1>Chương 1</h1><p>Đây là nội dung chương đủ dài để kiểm tra.</p></html>",
            requested_url="https://www.69shuba.com/book/1/chapter/1",
            final_url="https://www.69shuba.com/book/1/chapter/1",
            method=source_adapters.FetchMethod.DIRECT_HTTP,
            status_code=200,
            attempts=1,
            elapsed_ms=12,
            bytes_received=128,
            cookies_refreshed=False,
            cache_hit=False,
        ),
    )
    adapter = source_adapters.GenericHtmlSourceAdapter()

    chapter = adapter.fetch_chapter("https://www.69shuba.com/book/1/chapter/1")

    assert chapter.fetch_bytes_received == 128
    entries = _metric(observability.snapshot(), "fetch_requests_total")
    assert entries and entries[0]["labels"]["adapter_id"] == "generic_html"


def test_dom_parser_failure_records_adapter_version_without_html(monkeypatch: pytest.MonkeyPatch) -> None:
    observability = Observability()
    monkeypatch.setattr(source_adapters, "default_observability", observability)
    adapter = next(
        candidate
        for candidate in source_adapters.build_default_source_adapters()
        if isinstance(candidate, source_adapters.DomSourceAdapter) and candidate._regex_fallback is None
    )
    url = f"https://{adapter.domains[0]}/book/1/chapter/1"

    with pytest.raises(source_adapters.SourceAdapterError):
        adapter.chapter_from_html(
            url,
            "<html><body><h1>Kiểm tra trình duyệt</h1></body></html>",
        )

    entries = _metric(observability.snapshot(), "parse_failures_total")
    assert entries
    assert entries[0]["labels"]["adapter_id"] == adapter.adapter_id
    assert entries[0]["labels"]["adapter_version"] == adapter.adapter_version
