from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.database.db import get_managed_source, init_db, update_managed_source
from app.ingestion.source_adapters import SourceAdapterError
from app.ingestion.managed_sources import import_selected_catalog_sources, verify_managed_source
from app.ingestion.source_catalog import import_source_catalog_json
from app.ingestion.source_health import ManagedSourceTestResult


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _write_catalog(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _seed_catalog_entry(temp_db_path: Path, tmp_path: Path) -> str:
    catalog_path = tmp_path / "managed-sources.json"
    _write_catalog(
        catalog_path,
        [
            {
                "id": "1",
                "name": "69 Source",
                "url": "https://www.69shuba.com/book/1",
                "tags": "搜",
            }
        ],
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    summary = import_selected_catalog_sources(temp_db_path, ["yckceo:1"])
    assert summary.inserted == 1
    return summary.items[0]["id"]


def test_managed_source_tables_exist_after_init(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    managed_columns = _columns(temp_db_path, "managed_sources")
    test_columns = _columns(temp_db_path, "managed_source_tests")

    assert {
        "id",
        "catalog_entry_id",
        "base_url",
        "domain",
        "status",
        "trust_level",
        "last_test_status",
        "last_tested_at",
        "last_successful_fetch_at",
        "last_error",
        "rate_limit_requests_per_minute",
        "rate_limit_delay_ms",
        "max_concurrent_requests",
        "cooldown_after_error_seconds",
    }.issubset(managed_columns)
    assert {
        "id",
        "source_id",
        "status",
        "reason",
        "http_status",
        "final_url",
        "tested_at",
    }.issubset(test_columns)


def test_imported_source_defaults_to_review_not_verified(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    source_id = _seed_catalog_entry(temp_db_path, tmp_path)

    source = get_managed_source(temp_db_path, source_id)
    assert source is not None
    assert source["status"] == "NEEDS_REVIEW"
    assert source["trust_level"] == "MANUAL_ONLY"
    assert source["can_use_in_jobs"] is False


def test_verify_managed_source_requires_explicit_successful_test(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    source_id = _seed_catalog_entry(temp_db_path, tmp_path)

    with pytest.raises(SourceAdapterError, match="pass a safe fetch test"):
        verify_managed_source(temp_db_path, source_id)

    update_managed_source(
        temp_db_path,
        source_id,
        last_test_status="success",
        last_tested_at="2026-07-09T00:00:00+00:00",
        last_successful_fetch_at="2026-07-09T00:00:00+00:00",
        last_error="",
    )
    verified = verify_managed_source(temp_db_path, source_id)
    assert verified["status"] == "VERIFIED"
    assert verified["trust_level"] == "HIGH"
    assert verified["can_use_in_jobs"] is True


@pytest.mark.asyncio
async def test_managed_source_api_requires_auth(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mobile_api import auth as auth_mod
    from app.mobile_api.routers import sources as sources_router

    init_db(temp_db_path)
    monkeypatch.setattr(auth_mod, "auth_bypass_enabled", lambda: False)
    monkeypatch.setattr(sources_router, "get_db_path", lambda: temp_db_path)

    app = FastAPI()
    app.include_router(sources_router.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/sources")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_managed_source_api_import_test_and_verify_flow(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod
    from app.mobile_api.auth import get_current_user
    from app.mobile_api.routers import sources as sources_router

    init_db(temp_db_path)
    catalog_path = tmp_path / "sources.json"
    _write_catalog(
        catalog_path,
        [{"id": "1", "name": "69 Source", "url": "https://www.69shuba.com/book/1", "tags": "搜"}],
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    monkeypatch.setattr(sources_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)

    def fake_test_existing_managed_source(db_path: Path, source_id: str) -> dict:
        assert db_path == temp_db_path
        source = get_managed_source(temp_db_path, source_id)
        assert source is not None
        if source["status"] == "BLOCKED":
            raise SourceAdapterError("Blocked sources cannot be tested")
        payload = ManagedSourceTestResult(
            source_id=source_id,
            domain="www.69shuba.com",
            status="success",
            reason="ok",
            tested_at="2026-07-09T00:00:00+00:00",
            final_url="https://www.69shuba.com/book/1",
            http_status=200,
        ).to_dict()
        update_managed_source(
            temp_db_path,
            source_id,
            last_test_status="success",
            last_tested_at=payload["tested_at"],
            last_successful_fetch_at=payload["tested_at"],
            last_error="",
        )
        return payload

    monkeypatch.setattr(sources_router, "test_existing_managed_source", fake_test_existing_managed_source)

    app = FastAPI()
    app.include_router(sources_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"username": "admin", "user_id": "u1"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import_response = await client.post("/api/sources/import-catalog", json={"entry_ids": ["yckceo:1"]})
        assert import_response.status_code == 200
        source_id = import_response.json()["items"][0]["id"]

        before_verify = await client.post(f"/api/sources/{source_id}/verify")
        assert before_verify.status_code == 409

        test_response = await client.post(f"/api/sources/{source_id}/test")
        assert test_response.status_code == 200
        assert test_response.json()["status"] == "success"

        verify_response = await client.post(f"/api/sources/{source_id}/verify")
        assert verify_response.status_code == 200
        assert verify_response.json()["status"] == "VERIFIED"

        blocked_response = await client.post(f"/api/sources/{source_id}/status", json={"status": "BLOCKED"})
        assert blocked_response.status_code == 200
        assert blocked_response.json()["status"] == "BLOCKED"

        blocked_test = await client.post(f"/api/sources/{source_id}/test")
        assert blocked_test.status_code == 409
        assert "cannot be tested" in blocked_test.text
