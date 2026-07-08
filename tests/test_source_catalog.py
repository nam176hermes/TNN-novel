from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.database.db import init_db, list_operational_events, list_source_catalog_entries
from app.ingestion.source_catalog import (
    import_source_catalog_json,
    normalize_catalog_tags,
    normalize_catalog_url,
    normalize_source_catalog_entry,
)


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _write_catalog(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_source_catalog_table_exists_after_init(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    columns = _columns(temp_db_path, "source_catalog_entries")
    health_columns = _columns(temp_db_path, "source_catalog_health_checks")

    assert {
        "id",
        "external_id",
        "catalog_source",
        "name",
        "url",
        "domain",
        "tags_json",
        "supported_status",
        "supported_source_id",
        "invalid_reason",
        "last_check_status",
        "last_check_at",
        "last_check_error",
        "last_check_http_status",
        "last_check_final_url",
    }.issubset(columns)
    assert {
        "id",
        "catalog_entry_id",
        "status",
        "reason",
        "http_status",
        "final_url",
        "checked_at",
    }.issubset(health_columns)


def test_source_catalog_normalizes_yckceo_tags_and_supported_domain() -> None:
    entry = normalize_source_catalog_entry(
        {
            "id": "7497",
            "name": "🍅番茄小说源",
            "url": "https://www.69shuba.com/book/1",
            "version": "3.X",
            "tags": "发 搜 图 声",
            "author": "collector",
            "downloads": "1251",
            "time": "5小时前",
        }
    )

    assert entry["id"] == "yckceo:7497"
    assert entry["domain"] == "www.69shuba.com"
    assert json.loads(entry["tags_json"]) == ["explore", "search", "manga", "audio"]
    assert entry["supported_status"] == "supported"
    assert entry["supported_source_id"] == "69shuba"
    assert entry["downloads"] == 1251


def test_source_catalog_preserves_unknown_tags_safely() -> None:
    tags, unknown = normalize_catalog_tags("发 custom-tag ��户: ljy911028")

    assert tags == ["explore"]
    assert "custom-tag" in unknown
    assert "��户:" in unknown


def test_source_catalog_marks_invalid_and_unsupported_urls() -> None:
    assert normalize_catalog_url("ftp://example.com/source.json")[2] == "unsupported_url_scheme"
    assert normalize_catalog_url("http://127.0.0.1/source.json")[2] == "private_network_not_allowed"

    unsupported = normalize_source_catalog_entry(
        {"id": "x1", "name": "Example", "url": "https://example.com/source.json", "tags": "搜"}
    )
    missing = normalize_source_catalog_entry({"id": "x2", "name": "Missing URL", "url": "", "tags": "搜"})

    assert unsupported["supported_status"] == "unsupported"
    assert unsupported["invalid_reason"] == ""
    assert missing["supported_status"] == "invalid_url"
    assert missing["invalid_reason"] == "missing_url"


def test_source_catalog_import_is_idempotent_and_filterable(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    catalog_path = tmp_path / "yckceo_sources.json"
    _write_catalog(
        catalog_path,
        [
            {
                "id": "1",
                "name": "69 Source",
                "url": "https://www.69shuba.com/book/1",
                "tags": "搜",
                "downloads": 10,
            },
            {
                "id": "2",
                "name": "Other Source",
                "url": "https://example.com/source",
                "tags": "发",
                "downloads": 5,
            },
        ],
    )

    first = import_source_catalog_json(temp_db_path, catalog_path)
    second = import_source_catalog_json(temp_db_path, catalog_path)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 2
    all_rows = list_source_catalog_entries(temp_db_path, per_page=10)
    assert all_rows["total"] == 2
    supported = list_source_catalog_entries(temp_db_path, supported=True)
    unsupported = list_source_catalog_entries(temp_db_path, supported=False)
    search = list_source_catalog_entries(temp_db_path, query="69 source")
    tag = list_source_catalog_entries(temp_db_path, tag="explore")
    domain = list_source_catalog_entries(temp_db_path, domain="www.69shuba.com")

    assert supported["total"] == 1
    assert supported["items"][0]["supported_source_id"] == "69shuba"
    assert unsupported["total"] == 1
    assert search["total"] == 1
    assert tag["items"][0]["name"] == "Other Source"
    assert domain["total"] == 1


def test_source_catalog_cli_imports_local_file(temp_db_path: Path, tmp_path: Path) -> None:
    from app.ingestion import source_catalog_cli

    catalog_path = tmp_path / "sources.json"
    _write_catalog(
        catalog_path,
        [{"id": "cli-1", "name": "CLI Source", "url": "https://example.com/source", "tags": "搜"}],
    )

    exit_code = source_catalog_cli.main([str(catalog_path), "--db-path", str(temp_db_path)])

    assert exit_code == 0
    rows = list_source_catalog_entries(temp_db_path, query="CLI Source")
    assert rows["total"] == 1


@pytest.mark.asyncio
async def test_source_catalog_api_returns_paginated_filters(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.routers import source_catalog as source_catalog_router

    catalog_path = temp_db_path.with_suffix(".sources.json")
    _write_catalog(
        catalog_path,
        [
            {"id": "1", "name": "69 Source", "url": "https://www.69shuba.com/book/1", "tags": "搜"},
            {"id": "2", "name": "Example Source", "url": "https://example.com/source", "tags": "发"},
        ],
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    monkeypatch.setattr(source_catalog_router, "get_db_path", lambda: temp_db_path)
    app = FastAPI()
    app.include_router(source_catalog_router.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/source-catalog",
            params={"supported": "true", "tag": "search", "page_size": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page_size"] == 1
    assert payload["items"][0]["name"] == "69 Source"
    assert payload["entries"][0]["name"] == "69 Source"
    assert payload["items"][0]["supported"] is True


@pytest.mark.asyncio
async def test_source_catalog_check_api_records_health_and_audit(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion.source_health import SourceHealthResult
    from app.mobile_api import audit as audit_mod
    from app.mobile_api.routers import source_catalog as source_catalog_router

    catalog_path = tmp_path / "sources.json"
    _write_catalog(
        catalog_path,
        [{"id": "1", "name": "69 Source", "url": "https://www.69shuba.com/book/1", "tags": "搜"}],
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    row = list_source_catalog_entries(temp_db_path, query="69 Source")["items"][0]
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(source_catalog_router, "get_db_path", lambda: temp_db_path)

    def fake_check(entry: dict) -> SourceHealthResult:
        assert entry["id"] == row["id"]
        return SourceHealthResult(
            catalog_entry_id=row["id"],
            domain="www.69shuba.com",
            status="reachable",
            reason="ok",
            checked_at="2026-07-07T00:00:00+00:00",
            final_url="https://www.69shuba.com/book/1",
            http_status=200,
        )

    monkeypatch.setattr(source_catalog_router, "check_source_health", fake_check)
    app = FastAPI()
    app.include_router(source_catalog_router.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/source-catalog/{row['id']}/check")
        catalog_response = await client.get("/api/source-catalog", params={"query": "69 Source"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reachable"
    assert payload["http_status"] == 200
    assert payload["final_url"] == "https://www.69shuba.com/book/1"

    checked_entry = catalog_response.json()["items"][0]
    assert checked_entry["last_check_status"] == "reachable"
    assert checked_entry["last_check_http_status"] == 200
    assert checked_entry["last_check_final_url"] == "https://www.69shuba.com/book/1"

    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "source_catalog_health_check")
    serialized = json.dumps(event, ensure_ascii=False)
    assert event["details"]["catalog_entry_id"] == row["id"]
    assert event["details"]["domain"] == "www.69shuba.com"
    assert event["details"]["status"] == "reachable"
    assert "<html" not in serialized
    assert "Authorization" not in serialized
