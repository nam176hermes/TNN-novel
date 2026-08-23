from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, get_connection, init_db, put_glossary_term
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
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


def _version(db_path: Path, term_id: int) -> int:
    with get_connection(db_path) as conn:
        return int(conn.execute("SELECT version FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()[0])


@pytest.mark.asyncio
async def test_bulk_review_rejects_every_write_on_blank_stale_missing_and_locked_rows(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    ready_id = put_glossary_term(
        glossary_api_db, book_id, "可用", "dùng được", approved=0, review_status="NEEDS_REVIEW"
    )
    blank_id = put_glossary_term(
        glossary_api_db, book_id, "空白", "", approved=0, review_status="NEEDS_REVIEW"
    )
    locked_id = put_glossary_term(glossary_api_db, book_id, "锁定", "khóa", locked=1)
    conflict_id = put_glossary_term(
        glossary_api_db, book_id, "Ａ conflict", "một", approved=0, review_status="CONFLICT"
    )
    with get_connection(glossary_api_db) as conn:
        conn.execute(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked,
                 review_status, version, archived_at)
            VALUES (?, 'a conflict', 'a conflict', 'hai', 0, 0, 'CONFLICT', 1, '')
            """,
            (book_id,),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        blank = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "approve",
                "terms": [
                    {"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)},
                    {"id": blank_id, "expected_version": _version(glossary_api_db, blank_id)},
                ],
            },
            headers=headers,
        )
        missing = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "archive",
                "terms": [
                    {"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)},
                    {"id": 999_999, "expected_version": 1},
                ],
            },
            headers=headers,
        )
        locked = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "reject",
                "terms": [
                    {"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)},
                    {"id": locked_id, "expected_version": _version(glossary_api_db, locked_id)},
                ],
            },
            headers=headers,
        )
        stale = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "approve",
                "terms": [{"id": ready_id, "expected_version": 0}],
            },
            headers=headers,
        )
        unresolved = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "approve",
                "terms": [
                    {"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)},
                    {"id": conflict_id, "expected_version": _version(glossary_api_db, conflict_id)},
                ],
            },
            headers=headers,
        )

        success = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "approve",
                "terms": [{"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)}],
            },
            headers=headers,
        )

    assert blank.status_code == 409 and blank.json()["detail"]["code"] == "target_required"
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "term_not_found"
    assert locked.status_code == 409 and locked.json()["detail"]["code"] == "locked_term"
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
    assert unresolved.status_code == 409
    assert unresolved.json()["detail"]["code"] == "normalized_target_conflict"
    assert success.status_code == 200
    assert success.json()["updated"] == 1

    with get_connection(glossary_api_db) as conn:
        rows = conn.execute(
            "SELECT id, review_status, archived_at FROM glossary_terms WHERE id IN (?, ?, ?) ORDER BY id",
            (ready_id, blank_id, locked_id),
        ).fetchall()
        actions = conn.execute(
            "SELECT action FROM glossary_history WHERE term_id = ? ORDER BY id", (ready_id,)
        ).fetchall()
    assert [(row["id"], row["review_status"], bool(row["archived_at"])) for row in rows] == [
        (ready_id, "APPROVED", False),
        (blank_id, "NEEDS_REVIEW", False),
        (locked_id, "LOCKED", False),
    ]
    assert [row["action"] for row in actions].count("approve") == 1


@pytest.mark.asyncio
async def test_conflict_merge_requires_preview_moves_evidence_count_and_history_and_archives_duplicates(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    canonical_id = put_glossary_term(
        glossary_api_db, book_id, "Ａ  B", "Một", approved=0, review_status="CONFLICT"
    )
    with get_connection(glossary_api_db) as conn:
        duplicate_id = int(
            conn.execute(
                """
                INSERT INTO glossary_terms
                    (book_id, source_term, source_key, target_term, approved, locked,
                     review_status, occurrence_count, version, archived_at)
                VALUES (?, 'a b', 'a b', 'Hai', 0, 0, 'CONFLICT', 4, 3, '')
                """,
                (book_id,),
            ).lastrowid
        )
        conn.executemany(
            """
            INSERT INTO glossary_term_evidence
                (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
            VALUES (?, ?, 1, 'test', 'occurrence', '{}')
            """,
            ((canonical_id, book_id), (duplicate_id, book_id)),
        )
        conn.execute(
            """
            INSERT INTO glossary_history
                (term_id, book_id, source_term, target_term, action, version)
            VALUES (?, ?, 'a b', 'Hai', 'seed-duplicate', 3)
            """,
            (duplicate_id, book_id),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        conflicts = await client.get(
            f"/api/glossary/conflicts?book_id={book_id}&page=1&per_page=1", headers=headers
        )
        missing_preview = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": canonical_id,
                "duplicate_ids": [duplicate_id],
                "digest": "not-a-preview",
            },
            headers=headers,
        )
        preview = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": canonical_id, "duplicate_ids": [duplicate_id]},
            headers=headers,
        )
        applied = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": canonical_id,
                "duplicate_ids": [duplicate_id],
                "digest": preview.json()["digest"],
            },
            headers=headers,
        )

    assert conflicts.status_code == 200
    assert conflicts.json()["total"] >= 1
    assert "normalized_duplicate" in conflicts.json()["items"][0]["types"]
    assert missing_preview.status_code == 409
    assert missing_preview.json()["detail"]["code"] == "preview_mismatch"
    assert preview.status_code == 200
    assert preview.json()["evidence_count"] == 2
    assert applied.status_code == 200

    with get_connection(glossary_api_db) as conn:
        canonical = conn.execute(
            "SELECT occurrence_count, archived_at FROM glossary_terms WHERE id = ?", (canonical_id,)
        ).fetchone()
        duplicate = conn.execute(
            "SELECT archived_at FROM glossary_terms WHERE id = ?", (duplicate_id,)
        ).fetchone()
        evidence_ids = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT term_id FROM glossary_term_evidence WHERE term_id IN (?, ?)",
                (canonical_id, duplicate_id),
            )
        }
        moved_history = conn.execute(
            "SELECT term_id FROM glossary_history WHERE action = 'seed-duplicate'"
        ).fetchone()
    assert canonical["occurrence_count"] == 5
    assert not canonical["archived_at"]
    assert duplicate["archived_at"]
    assert evidence_ids == {canonical_id}
    assert moved_history["term_id"] == canonical_id

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        archived = await client.delete(f"/api/glossary/terms/{canonical_id}", headers=headers)
        restored = await client.post(f"/api/glossary/terms/{duplicate_id}/restore", headers=headers)
    assert archived.status_code == 200
    assert restored.status_code == 200


@pytest.mark.asyncio
async def test_import_preview_apply_rechecks_digest_in_one_transaction_and_returns_typed_errors(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    existing_id = put_glossary_term(
        glossary_api_db, book_id, "旧词", "cũ", approved=0, review_status="NEEDS_REVIEW"
    )
    items = [
        {
            "book_id": book_id,
            "source_term": "旧词",
            "target_term": "mới",
            "mode": "context",
            "term_type": "concept",
            "variants": "旧語",
            "notes_vi": "ghi chú",
            "priority": 7,
            "approved": 1,
            "review_status": "APPROVED",
        },
        {
            "book_id": book_id,
            "source_term": "新词",
            "target_term": "từ mới",
            "mode": "transliterate",
            "term_type": "character",
            "variants": "新語",
            "notes_vi": "mới",
            "priority": 9,
            "approved": -1,
            "review_status": "REJECTED",
        },
    ]

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        preview = await client.post(
            "/api/glossary/import/preview",
            json={"items": items},
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["summary"] == {"added": 1, "updated": 1, "skipped": 0}

        changed = await client.patch(
            f"/api/glossary/terms/{existing_id}",
            json={"notes_vi": "drift", "expected_version": _version(glossary_api_db, existing_id)},
            headers=headers,
        )
        assert changed.status_code == 200
        drift = await client.post(
            "/api/glossary/import/apply",
            json={"items": items, "digest": preview.json()["digest"], "conflict_policy": "skip_conflicts"},
            headers=headers,
        )
        invalid = await client.post(
            "/api/glossary/import/preview",
            json={"items": [{"book_id": book_id, "target_term": "missing source"}]},
            headers=headers,
        )
        invalid_number = await client.post(
            "/api/glossary/import/preview",
            json={
                "items": [
                    {
                        "book_id": book_id,
                        "source_term": "坏数字",
                        "target_term": "số lỗi",
                        "confidence": "private exception text",
                    }
                ]
            },
            headers=headers,
        )

        fresh_preview = await client.post(
            "/api/glossary/import/preview", json={"items": items}, headers=headers
        )
        applied = await client.post(
            "/api/glossary/import/apply",
            json={
                "items": items,
                "digest": fresh_preview.json()["digest"],
                "conflict_policy": "skip_conflicts",
            },
            headers=headers,
        )

    assert drift.status_code == 409
    assert drift.json()["detail"]["code"] == "import_drift"
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {
        "code": "validation_failed",
        "errors": [{"item": 1, "field": "source_term", "code": "required"}],
    }
    assert invalid_number.status_code == 422
    assert invalid_number.json()["detail"] == {
        "code": "validation_failed",
        "errors": [{"item": 1, "field": "item", "code": "invalid_number"}],
    }
    assert applied.status_code == 200
    assert applied.json() == {"added": 1, "updated": 1, "skipped": 0, "errors": []}
    with get_connection(glossary_api_db) as conn:
        rows = conn.execute(
            """
            SELECT source_term, target_term, review_status, approved, locked, mode,
                   term_type, variants, notes_vi, priority
            FROM glossary_terms WHERE book_id = ? ORDER BY source_term
            """,
            (book_id,),
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("新词", "từ mới", "REJECTED", -1, 0, "transliterate", "character", "新語", "mới", 9),
        ("旧词", "mới", "APPROVED", 1, 0, "context", "concept", "旧語", "ghi chú", 7),
    ]


@pytest.mark.asyncio
async def test_import_limits_legacy_atomic_adapter_and_json_csv_round_trip_metadata(
    glossary_api_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    locked_id = put_glossary_term(glossary_api_db, book_id, "锁定", "khóa", locked=1)
    active_id = put_glossary_term(
        glossary_api_db,
        book_id,
        "活动",
        "hoạt động",
        approved=1,
        review_status="APPROVED",
        mode="context",
        term_type="concept",
        variants="活跃",
        notes_vi="ghi chú",
        priority=11,
    )
    archived_id = put_glossary_term(
        glossary_api_db,
        book_id,
        "归档",
        "lưu trữ",
        approved=-1,
        review_status="REJECTED",
        mode="transliterate",
        term_type="character",
        variants="封存",
        notes_vi="đã lưu",
        priority=4,
    )
    with get_connection(glossary_api_db) as conn:
        conn.execute("UPDATE glossary_terms SET archived_at = '2026-08-23T00:00:00Z' WHERE id = ?", (archived_id,))
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        too_many = await client.post(
            "/api/glossary/import/preview",
            json={"items": [{"source_term": f"t-{index}", "target_term": "x"} for index in range(5001)]},
            headers=headers,
        )
        too_large = await client.post(
            "/api/glossary/import/preview",
            content=json.dumps({"items": [{"source_term": "big", "target_term": "x", "notes_vi": "a" * (5 * 1024 * 1024)}]}),
            headers={**headers, "Content-Type": "application/json"},
        )
        legacy = await client.post(
            "/api/glossary/import",
            json=[
                {"book_id": book_id, "source_term": "先成功", "target_term": "thành công", "approved": 0},
                {"book_id": book_id, "source_term": "锁定", "target_term": "đổi", "approved": 0},
            ],
            headers=headers,
        )
        exported_json = await client.get(
            f"/api/glossary/export?book_id={book_id}&format=json&scope=book", headers=headers
        )
        exported_csv = await client.get(
            f"/api/glossary/export?book_id={book_id}&format=csv&scope=book", headers=headers
        )

    assert too_many.status_code == 422
    assert too_many.json()["detail"]["code"] == "row_limit_exceeded"
    assert too_large.status_code == 413
    assert too_large.json()["detail"]["code"] == "payload_too_large"
    assert legacy.status_code == 200
    assert legacy.json()["added"] == 0
    assert legacy.json()["errors"] == ["item 2: invalid_transition"]
    with get_connection(glossary_api_db) as conn:
        assert conn.execute("SELECT 1 FROM glossary_terms WHERE source_term = '先成功'").fetchone() is None
        assert conn.execute("SELECT version FROM glossary_terms WHERE id = ?", (locked_id,)).fetchone()[0] == 1

    payload = exported_json.json()
    assert payload["schema_version"] == 1
    assert payload["scope"] == {"type": "book", "book_id": book_id}
    assert payload["total"] == 3
    by_id = {term["id"]: term for term in payload["terms"]}
    assert by_id[active_id] | {
        "mode": "context",
        "term_type": "concept",
        "variants": "活跃",
        "notes_vi": "ghi chú",
        "priority": 11,
        "archived": False,
    } == by_id[active_id]
    assert by_id[archived_id]["archived"] is True
    csv_text = exported_csv.text
    assert csv_text.startswith("schema_version,scope,scope_book_id,")
    assert "archived" in csv_text.splitlines()[0]

    round_trip_db = tmp_path / "round-trip.sqlite"
    init_db(round_trip_db)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: round_trip_db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        preview = await client.post(
            "/api/glossary/import/preview", json={"items": payload["terms"]}, headers=headers
        )
        assert preview.status_code == 200
        imported = await client.post(
            "/api/glossary/import/apply",
            json={"items": payload["terms"], "digest": preview.json()["digest"]},
            headers=headers,
        )
    assert imported.status_code == 200
    assert imported.json()["added"] == 3
    with get_connection(round_trip_db) as conn:
        round_trip_rows = conn.execute(
            """
            SELECT source_term, target_term, review_status, approved, locked, mode,
                   term_type, variants, notes_vi, priority, archived_at
            FROM glossary_terms ORDER BY source_term
            """
        ).fetchall()
    assert [tuple(row) for row in round_trip_rows] == [
        ("归档", "lưu trữ", "REJECTED", -1, 0, "transliterate", "character", "封存", "đã lưu", 4, "2026-08-23T00:00:00Z"),
        ("活动", "hoạt động", "APPROVED", 1, 0, "context", "concept", "活跃", "ghi chú", 11, ""),
        ("锁定", "khóa", "LOCKED", 1, 1, "translate", "term", "", "", 0, ""),
    ]


@pytest.mark.asyncio
async def test_archived_queue_exposes_restorable_terms(glossary_api_db: Path) -> None:
    book_id = add_book(glossary_api_db, "Book")
    term_id = put_glossary_term(glossary_api_db, book_id, "归档项", "", approved=0)
    with get_connection(glossary_api_db) as conn:
        conn.execute(
            "UPDATE glossary_terms SET archived_at = '2026-08-23T00:00:00Z' WHERE id = ?",
            (term_id,),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.get(
            f"/api/glossary?book_id={book_id}&scope=book&archived=true",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == term_id
    assert response.json()["items"][0]["archived"] is True
