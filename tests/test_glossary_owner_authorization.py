from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx
import pytest

from app.database.db import add_book, get_connection, init_db, put_glossary_term
from app.mobile_api.auth import get_current_user
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.services.glossary_service import GlossaryService


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@contextmanager
def _as_user(user_id: str, username: str) -> Iterator[None]:
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user_id,
        "username": username,
    }
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def owner_glossary_db(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    init_db(temp_db_path)
    monkeypatch.setattr(
        "app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path
    )
    book_a = add_book(temp_db_path, "Owner A", owner_user_id="user-a")
    book_b = add_book(temp_db_path, "Owner B", owner_user_id="user-b")
    term_a = put_glossary_term(
        temp_db_path, book_a, "甲词", "từ a", approved=0, review_status="NEEDS_REVIEW"
    )
    term_b = put_glossary_term(
        temp_db_path, book_b, "乙词", "từ b", approved=0, review_status="NEEDS_REVIEW"
    )
    global_term = put_glossary_term(
        temp_db_path, 0, "全局词", "toàn cục", approved=1, review_status="APPROVED"
    )
    return {
        "book_a": book_a,
        "book_b": book_b,
        "term_a": term_a,
        "term_b": term_b,
        "global_term": global_term,
    }


@pytest.mark.asyncio
async def test_glossary_reads_are_owner_scoped_and_global_enumeration_is_admin_only(
    owner_glossary_db: dict[str, int],
) -> None:
    ids = owner_glossary_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        with _as_user("user-a", "reader-a"):
            owned = await client.get(
                f"/api/glossary?book_id={ids['book_a']}&scope=book", headers=headers
            )
            effective = await client.get(
                f"/api/glossary?book_id={ids['book_a']}&scope=effective", headers=headers
            )
            inherited = await client.get(
                f"/api/glossary/search?q=全局&book_id={ids['book_a']}", headers=headers
            )
            foreign = await client.get(
                f"/api/glossary?book_id={ids['book_b']}&scope=book", headers=headers
            )
            missing = await client.get(
                "/api/glossary?book_id=987654321&scope=book", headers=headers
            )
            direct_all = await client.get("/api/glossary?scope=all", headers=headers)
            direct_global = await client.get("/api/glossary?scope=global", headers=headers)
            direct_global_export = await client.get(
                "/api/glossary/export?scope=global&format=json", headers=headers
            )
            owned_detail = await client.get(
                f"/api/glossary/terms/{ids['term_a']}", headers=headers
            )
            foreign_detail = await client.get(
                f"/api/glossary/terms/{ids['term_b']}", headers=headers
            )
            global_detail = await client.get(
                f"/api/glossary/terms/{ids['global_term']}", headers=headers
            )
            foreign_conflicts = await client.get(
                f"/api/glossary/conflicts?book_id={ids['book_b']}", headers=headers
            )
            foreign_export = await client.get(
                f"/api/glossary/export?scope=book&book_id={ids['book_b']}", headers=headers
            )

        with _as_user("admin-id", mobile_settings.admin_username):
            admin_all = await client.get("/api/glossary?scope=all", headers=headers)
            admin_global = await client.get("/api/glossary?scope=global", headers=headers)
            admin_global_export = await client.get(
                "/api/glossary/export?scope=global&format=json", headers=headers
            )

    assert owned.status_code == effective.status_code == inherited.status_code == owned_detail.status_code == 200
    assert {item["source_term"] for item in owned.json()["items"]} == {"甲词"}
    assert {item["source_term"] for item in effective.json()["items"]} == {"全局词"}
    assert any(item["source_term"] == "全局词" for item in inherited.json()["results"])
    assert {"evidence", "history"}.issubset(owned_detail.json())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert [
        direct_all.status_code,
        direct_global.status_code,
        direct_global_export.status_code,
        foreign_detail.status_code,
        global_detail.status_code,
        foreign_conflicts.status_code,
        foreign_export.status_code,
    ] == [404, 404, 404, 404, 404, 404, 404]
    assert admin_all.status_code == admin_global.status_code == admin_global_export.status_code == 200


@pytest.mark.asyncio
async def test_glossary_single_term_mutations_check_owner_before_domain_state(
    owner_glossary_db: dict[str, int],
) -> None:
    ids = owner_glossary_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        with _as_user("user-a", "reader-a"):
            owned_create = await client.post(
                "/api/glossary/terms",
                json={"book_id": ids["book_a"], "source_term": "自有", "target_term": "sở hữu"},
                headers=headers,
            )
            foreign_create = await client.post(
                "/api/glossary/terms",
                json={"book_id": ids["book_b"], "source_term": "越权", "target_term": "sai"},
                headers=headers,
            )
            global_create = await client.post(
                "/api/glossary/terms",
                json={"book_id": 0, "source_term": "全局新增", "target_term": "global"},
                headers=headers,
            )
            responses = [
                await client.patch(
                    f"/api/glossary/terms/{ids['global_term']}",
                    json={"target_term": "forbidden global change"},
                    headers=headers,
                ),
                await client.patch(
                    f"/api/glossary/terms/{ids['term_b']}",
                    json={"target_term": "changed"},
                    headers=headers,
                ),
                await client.post(f"/api/glossary/terms/{ids['term_b']}/lock", headers=headers),
                await client.post(f"/api/glossary/terms/{ids['term_b']}/unlock", headers=headers),
                await client.post(f"/api/glossary/terms/{ids['term_b']}/approve", headers=headers),
                await client.post(f"/api/glossary/terms/{ids['term_b']}/reject", headers=headers),
                await client.delete(f"/api/glossary/terms/{ids['term_b']}", headers=headers),
                await client.post(f"/api/glossary/terms/{ids['term_b']}/restore", headers=headers),
            ]

        with _as_user("admin-id", mobile_settings.admin_username):
            admin_global_create = await client.post(
                "/api/glossary/terms",
                json={"book_id": 0, "source_term": "管理员全局", "target_term": "admin global"},
                headers=headers,
            )
            admin_global_update = await client.patch(
                f"/api/glossary/terms/{ids['global_term']}",
                json={"target_term": "global admin update"},
                headers=headers,
            )

    assert owned_create.status_code == 201
    assert foreign_create.status_code == global_create.status_code == 404
    assert all(response.status_code == 404 for response in responses)
    assert admin_global_create.status_code == 201
    assert admin_global_update.status_code == 200
    with get_connection(GlossaryService().db_path) as conn:
        foreign = conn.execute(
            "SELECT target_term, locked, approved, review_status, archived_at FROM glossary_terms WHERE id = ?",
            (ids["term_b"],),
        ).fetchone()
        leaked = conn.execute(
            "SELECT COUNT(*) FROM glossary_terms WHERE source_term IN ('越权', '全局新增')"
        ).fetchone()[0]
    assert tuple(foreign) == ("từ b", 0, 0, "NEEDS_REVIEW", "")
    assert leaked == 0


@pytest.mark.asyncio
async def test_mixed_owner_bulk_and_merge_fail_atomically_before_writes(
    owner_glossary_db: dict[str, int],
) -> None:
    ids = owner_glossary_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        with _as_user("user-a", "reader-a"):
            bulk = await client.post(
                "/api/glossary/terms/bulk",
                json={
                    "action": "approve",
                    "terms": [
                        {"id": ids["term_a"], "expected_version": 1},
                        {"id": ids["term_b"], "expected_version": 1},
                    ],
                },
                headers=headers,
            )
            merge_preview = await client.post(
                "/api/glossary/conflicts/merge/preview",
                json={"canonical_id": ids["term_a"], "duplicate_ids": [ids["term_b"]]},
                headers=headers,
            )
            merge_apply = await client.post(
                "/api/glossary/conflicts/merge/apply",
                json={
                    "canonical_id": ids["term_a"],
                    "duplicate_ids": [ids["term_b"]],
                    "digest": "0" * 64,
                },
                headers=headers,
            )

    assert bulk.status_code == merge_preview.status_code == merge_apply.status_code == 404
    with get_connection(GlossaryService().db_path) as conn:
        terms = conn.execute(
            "SELECT id, approved, review_status, archived_at FROM glossary_terms WHERE id IN (?, ?) ORDER BY id",
            (ids["term_a"], ids["term_b"]),
        ).fetchall()
    assert [tuple(row) for row in terms] == [
        (ids["term_a"], 0, "NEEDS_REVIEW", ""),
        (ids["term_b"], 0, "NEEDS_REVIEW", ""),
    ]


@pytest.mark.asyncio
async def test_mixed_owner_import_preview_apply_and_legacy_import_fail_before_writes(
    owner_glossary_db: dict[str, int],
) -> None:
    ids = owner_glossary_db
    items = [
        {"book_id": ids["book_a"], "source_term": "导入甲", "target_term": "nhập a"},
        {"book_id": ids["book_b"], "source_term": "导入乙", "target_term": "nhập b"},
    ]
    digest = GlossaryService().preview_import(items, "skip_conflicts")["digest"]
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        with _as_user("user-a", "reader-a"):
            preview = await client.post(
                "/api/glossary/import/preview",
                json={"items": items, "conflict_policy": "skip_conflicts"},
                headers=headers,
            )
            apply = await client.post(
                "/api/glossary/import/apply",
                json={
                    "items": items,
                    "conflict_policy": "skip_conflicts",
                    "digest": digest,
                },
                headers=headers,
            )
            legacy = await client.post("/api/glossary/import", json=items, headers=headers)
            global_preview = await client.post(
                "/api/glossary/import/preview",
                json={
                    "scope": {"type": "global", "book_id": 0},
                    "items": [{"book_id": 0, "source_term": "全局导入", "target_term": "global"}],
                },
                headers=headers,
            )
            all_scope_preview = await client.post(
                "/api/glossary/import/preview",
                json={
                    "scope": {"type": "all", "book_id": 0},
                    "items": [
                        {
                            "book_id": ids["book_a"],
                            "source_term": "全范围导入",
                            "target_term": "all scope",
                        }
                    ],
                },
                headers=headers,
            )

    assert preview.status_code == apply.status_code == legacy.status_code == 404
    assert global_preview.status_code == all_scope_preview.status_code == 404
    with get_connection(GlossaryService().db_path) as conn:
        added = conn.execute(
            "SELECT COUNT(*) FROM glossary_terms "
            "WHERE source_term IN ('导入甲', '导入乙', '全局导入', '全范围导入')"
        ).fetchone()[0]
    assert added == 0
