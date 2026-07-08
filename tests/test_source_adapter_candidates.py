from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
from fastapi import FastAPI

from app.database.db import init_db, list_source_catalog_entries
from app.ingestion.source_catalog import import_source_catalog_json
from app.ingestion.source_adapters import SourceAdapterError
from app.ingestion.parser_candidates import create_parser_candidate
from app.mobile_api.schemas import URLImportChapter, URLImportStart


class FakeResponse:
    def __init__(self, *, status_code: int = 200, url: str = "https://example.com/book/1", body: bytes = b"") -> None:
        self.status_code = status_code
        self.url = url
        self._body = body

    def iter_content(self, chunk_size: int = 1024):
        del chunk_size
        yield self._body


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _write_catalog(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def test_source_adapter_candidates_table_exists_after_init(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    columns = _columns(temp_db_path, "source_adapter_candidates")

    assert {
        "id",
        "catalog_entry_id",
        "domain",
        "sample_url",
        "detected_title",
        "detected_chapter_list",
        "parser_confidence",
        "failure_reason",
        "status",
        "created_at",
        "updated_at",
        "reviewed_at",
        "reviewed_by",
    }.issubset(columns)


def test_create_parser_candidate_detects_title_chapters_and_high_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    html = """
    <html>
      <head><title>Example Novel - Catalog</title></head>
      <body>
        <h1>Example Novel</h1>
        <div id="chapter-list">
          <a href="/book/1/chapter-1">Chapter 1 Start</a>
          <a href="/book/1/chapter-2">Chapter 2 Continue</a>
          <a href="/book/1/chapter-3">Chapter 3 End</a>
        </div>
        <article id="content">This is a long chapter content container with enough text to look useful.</article>
        <a href="/book/1/chapter-2">Next chapter</a>
      </body>
    </html>
    """.encode()

    def requester(url: str, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] <= 6
        assert "Authorization" not in kwargs["headers"]
        assert "Cookie" not in kwargs["headers"]
        return FakeResponse(url=url, body=html)

    candidate = create_parser_candidate(
        {
            "id": "catalog-1",
            "name": "Example",
            "url": "https://example.com/book/1",
            "domain": "example.com",
        },
        request_get=requester,
    )

    assert candidate["catalog_entry_id"] == "catalog-1"
    assert candidate["detected_title"] == "Example Novel"
    assert candidate["parser_confidence"] == "high"
    assert candidate["status"] == "needs_review"
    assert len(candidate["detected_chapter_list"]) >= 3
    assert candidate["failure_reason"] == ""


def test_create_parser_candidate_stores_failed_reason_for_ssrf() -> None:
    called = False

    def requester(*args, **kwargs):  # pragma: no cover - should never be called
        nonlocal called
        called = True
        return FakeResponse()

    candidate = create_parser_candidate(
        {"id": "catalog-local", "url": "http://127.0.0.1/private", "domain": "127.0.0.1"},
        request_get=requester,
    )

    assert candidate["parser_confidence"] == "failed"
    assert candidate["status"] == "draft"
    assert candidate["failure_reason"] == "private_network_not_allowed"
    assert called is False


@pytest.mark.asyncio
async def test_parser_candidate_api_creates_and_lists_candidates(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import parser_candidates as candidate_service
    from app.mobile_api.routers import source_adapter_candidates as candidates_router
    from app.mobile_api.routers import source_catalog as source_catalog_router

    catalog_path = tmp_path / "sources.json"
    _write_catalog(
        catalog_path,
        [{"id": "1", "name": "Example Source", "url": "https://example.com/book/1", "tags": "搜"}],
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    row = list_source_catalog_entries(temp_db_path, query="Example Source")["items"][0]
    monkeypatch.setattr(source_catalog_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(candidates_router, "get_db_path", lambda: temp_db_path)

    def fake_create(entry: dict, sample_url: str = "", request_get=requests.get) -> dict:
        del sample_url, request_get
        return {
            "catalog_entry_id": entry["id"],
            "domain": "example.com",
            "sample_url": entry["url"],
            "detected_title": "Example Source",
            "detected_chapter_list": [{"title": "Chapter 1", "url": "https://example.com/book/1/c1"}],
            "parser_confidence": "medium",
            "failure_reason": "",
            "status": "needs_review",
        }

    monkeypatch.setattr(candidate_service, "create_parser_candidate", fake_create)
    monkeypatch.setattr(source_catalog_router, "create_parser_candidate", fake_create)
    app = FastAPI()
    app.include_router(source_catalog_router.router)
    app.include_router(candidates_router.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(f"/api/source-catalog/{row['id']}/parser-candidate")
        listed = await client.get("/api/source-adapter-candidates")

    assert created.status_code == 200
    candidate = created.json()
    assert candidate["catalog_entry_id"] == row["id"]
    assert candidate["parser_confidence"] == "medium"
    assert candidate["status"] == "needs_review"
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == candidate["id"]
    assert listed.json()["items"][0]["status"] != "promoted"


def test_parser_candidate_does_not_weaken_unsupported_import_policy() -> None:
    from app.mobile_api.routers.import_routes import _validated_url_import_payload

    payload = URLImportStart(
        url="https://unsupported.example/book/1",
        title="Unsupported",
        chapters=[
            URLImportChapter(
                chapter_number=1,
                title="Chapter 1",
                url="https://unsupported.example/book/1/chapter-1",
            )
        ],
    )

    with pytest.raises(SourceAdapterError, match="Unsupported source domain"):
        _validated_url_import_payload(payload)
