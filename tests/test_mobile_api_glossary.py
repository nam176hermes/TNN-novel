from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, get_connection, init_db, put_glossary_term
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def glossary_api_db(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path)
    return temp_db_path


@pytest.mark.asyncio
async def test_glossary_api_updates_p2_metadata(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(glossary_api_db, book_id, "筑基", "Trúc Cơ", mode="translate")
    with get_connection(glossary_api_db) as conn:
        term_id = conn.execute("SELECT id FROM glossary_terms WHERE source_term = ?", ("筑基",)).fetchone()["id"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            f"/api/glossary/terms/{term_id}",
            json={
                "target_term": "Trúc Cơ kỳ",
                "term_type": "realm",
                "genre": "tien_hiep",
                "priority": 40,
                "locked": 1,
            },
            headers=headers,
        )

    assert response.status_code == 200
    with get_connection(glossary_api_db) as conn:
        term = conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()
    assert term["target_term"] == "Trúc Cơ kỳ"
    assert term["term_type"] == "realm"
    assert term["genre"] == "tien_hiep"
    assert term["priority"] == 40
    assert term["locked"] == 1


@pytest.mark.asyncio
async def test_glossary_api_locks_and_unlocks_terms(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(glossary_api_db, book_id, "灵石", "linh thạch", mode="translate")
    with get_connection(glossary_api_db) as conn:
        term_id = conn.execute("SELECT id FROM glossary_terms WHERE source_term = ?", ("灵石",)).fetchone()["id"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        lock_response = await client.post(f"/api/glossary/terms/{term_id}/lock", headers=headers)
        unlock_response = await client.post(f"/api/glossary/terms/{term_id}/unlock", headers=headers)
        missing_response = await client.post("/api/glossary/terms/999999/lock", headers=headers)

    assert lock_response.status_code == 200
    assert unlock_response.status_code == 200
    assert missing_response.status_code == 404
    with get_connection(glossary_api_db) as conn:
        locked = conn.execute("SELECT locked FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()["locked"]
    assert locked == 0


@pytest.mark.asyncio
async def test_glossary_api_hides_weak_terms_and_prioritizes_reviewable_terms(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(glossary_api_db, book_id, "他", "hắn", approved=0)
    put_glossary_term(glossary_api_db, book_id, "然后", "sau đó", approved=0)
    put_glossary_term(glossary_api_db, book_id, "无译词", "", approved=0)
    put_glossary_term(glossary_api_db, book_id, "灵石", "linh thạch", approved=0, term_type="term")
    put_glossary_term(glossary_api_db, book_id, "灵石", "linh thạch", approved=0, term_type="term")
    put_glossary_term(glossary_api_db, book_id, "青云宗", "Thanh Vân Tông", approved=0, term_type="sect")
    put_glossary_term(glossary_api_db, book_id, "筑基", "Trúc Cơ", approved=0, term_type="realm")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/glossary?book_id={book_id}&per_page=200&include_weak=0",
            headers=headers,
        )
        with_weak_response = await client.get(
            f"/api/glossary?book_id={book_id}&per_page=200&include_weak=1",
            headers=headers,
        )

    assert response.status_code == 200
    source_terms = [item["source_term"] for item in response.json()["items"]]
    assert source_terms == ["筑基", "青云宗", "灵石"]
    assert "他" not in source_terms
    assert "然后" not in source_terms
    assert "无译词" not in source_terms

    assert with_weak_response.status_code == 200
    source_terms_with_weak = [item["source_term"] for item in with_weak_response.json()["items"]]
    assert {"他", "然后", "无译词"}.issubset(set(source_terms_with_weak))


@pytest.mark.asyncio
async def test_glossary_export_includes_review_metadata(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(
        glossary_api_db,
        book_id,
        "筑基",
        "Trúc Cơ",
        approved=1,
        locked=1,
        review_status="APPROVED",
        source_context="第十章",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(f"/api/glossary/export?book_id={book_id}&format=json", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    term = payload["terms"][0]
    assert term["review_status"] == "LOCKED"
    assert term["locked"] == 1
    assert term["source_context"] == "第十章"


@pytest.mark.asyncio
async def test_glossary_api_maps_state_conflict_to_sanitized_409(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    term_id = put_glossary_term(glossary_api_db, book_id, "锁定", "khóa", locked=1)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        conflict = await client.post(f"/api/glossary/terms/{term_id}/reject", headers=headers)
        missing = await client.post("/api/glossary/terms/999999/approve", headers=headers)

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "locked_term"}}
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_glossary_import_history_keeps_authenticated_mutation_metadata(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    existing_id = put_glossary_term(glossary_api_db, book_id, "旧词", "cũ", approved=0)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        headers["X-Request-ID"] = "req-import"
        response = await client.post(
            "/api/glossary/import",
            json=[
                {"book_id": book_id, "source_term": "旧词", "target_term": "mới", "approved": 0},
                {"book_id": book_id, "source_term": "新词", "target_term": "từ mới", "approved": 0},
            ],
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"added": 1, "updated": 1, "errors": []}
    with get_connection(glossary_api_db) as conn:
        new_id = conn.execute(
            "SELECT id FROM glossary_terms WHERE book_id = ? AND source_term = '新词'",
            (book_id,),
        ).fetchone()["id"]
        history = conn.execute(
            """
            SELECT term_id, actor, request_id FROM glossary_history
            WHERE term_id IN (?, ?) ORDER BY id DESC LIMIT 2
            """,
            (existing_id, new_id),
        ).fetchall()
    assert {row["term_id"] for row in history} == {existing_id, new_id}
    assert all(row["actor"] == mobile_settings.admin_username for row in history)
    assert all(row["request_id"] == "req-import" for row in history)


@pytest.mark.asyncio
async def test_glossary_import_reports_later_conflict_after_committed_prefix(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    locked_id = put_glossary_term(glossary_api_db, book_id, "锁定", "khóa", locked=1)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/glossary/import",
            json=[
                {"book_id": book_id, "source_term": "先成功", "target_term": "thành công", "approved": 0},
                {"book_id": book_id, "source_term": "锁定", "target_term": "khóa", "approved": 0},
            ],
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "added": 1,
        "updated": 0,
        "errors": ["item 2: invalid_transition"],
    }
    with get_connection(glossary_api_db) as conn:
        committed = conn.execute(
            "SELECT version FROM glossary_terms WHERE book_id = ? AND source_term = '先成功'",
            (book_id,),
        ).fetchone()
        locked = conn.execute(
            "SELECT version, review_status, approved, locked FROM glossary_terms WHERE id = ?",
            (locked_id,),
        ).fetchone()
    assert committed is not None and committed["version"] == 1
    assert tuple(locked) == (1, "LOCKED", 1, 1)
