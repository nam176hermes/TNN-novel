from __future__ import annotations

import csv
import json
from contextlib import contextmanager
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
    assert unresolved.json()["detail"]["code"] == "unresolved_conflict"
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


@pytest.mark.asyncio
async def test_legacy_import_updates_only_supplied_fields_without_approving_or_erasing_metadata(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    term_id = put_glossary_term(
        glossary_api_db,
        book_id,
        "旧词",
        "cũ",
        category="realm",
        confidence=0.42,
        approved=0,
        review_status="NEEDS_REVIEW",
        mode="context",
        pinyin="jiu ci",
        term_type="concept",
        variants="旧語",
        notes_vi="giữ nguyên",
        priority=17,
        genre="xianxia",
        alternatives="cổ từ",
        gender="neutral",
        first_seen_chapter_id=31,
        first_seen_chapter_number=9,
        source_context="ngữ cảnh gốc",
    )
    with get_connection(glossary_api_db) as conn:
        conn.execute(
            "UPDATE glossary_terms SET occurrence_count = 23 WHERE id = ?", (term_id,)
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/glossary/import",
            json=[{"book_id": book_id, "source_term": "旧词", "target_term": "mới"}],
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"added": 0, "updated": 1, "errors": []}
    with get_connection(glossary_api_db) as conn:
        row = conn.execute(
            """
            SELECT target_term, category, confidence, approved, locked, review_status,
                   mode, pinyin, term_type, variants, notes_vi, priority, genre,
                   alternatives, gender, first_seen_chapter_id,
                   first_seen_chapter_number, source_context, occurrence_count,
                   archived_at
            FROM glossary_terms WHERE id = ?
            """,
            (term_id,),
        ).fetchone()
    assert tuple(row) == (
        "mới", "realm", 0.42, 0, 0, "NEEDS_REVIEW", "context", "jiu ci",
        "concept", "旧語", "giữ nguyên", 17, "xianxia", "cổ từ", "neutral", 31,
        9, "ngữ cảnh gốc", 23, "",
    )


@pytest.mark.asyncio
async def test_merge_digest_rejects_evidence_or_history_drift_and_preserves_provenance(
    glossary_api_db: Path,
) -> None:
    canonical_book = add_book(glossary_api_db, "Canonical")
    provenance_book = add_book(glossary_api_db, "Provenance")
    canonical_id = put_glossary_term(
        glossary_api_db, canonical_book, "same", "Một", approved=0, review_status="CONFLICT"
    )
    with get_connection(glossary_api_db) as conn:
        duplicate_id = int(
            conn.execute(
                """
                INSERT INTO glossary_terms
                    (book_id, source_term, source_key, target_term, approved, locked,
                     review_status, version, archived_at)
                VALUES (?, 'ｓａｍｅ', 'same', 'Hai', 0, 0, 'CONFLICT', 1, '')
                """,
                (canonical_book,),
            ).lastrowid
        )
        evidence_id = int(
            conn.execute(
                """
                INSERT INTO glossary_term_evidence
                    (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
                VALUES (?, ?, 9, 'review', 'occurrence', '{"sample":"before"}')
                """,
                (duplicate_id, provenance_book),
            ).lastrowid
        )
        history_id = int(
            conn.execute(
                """
                INSERT INTO glossary_history
                    (term_id, book_id, source_term, target_term, action, version)
                VALUES (?, ?, 'same', 'Hai', 'seed-provenance', 1)
                """,
                (duplicate_id, provenance_book),
            ).lastrowid
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        drift_preview = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": canonical_id, "duplicate_ids": [duplicate_id]},
            headers=headers,
        )
        with get_connection(glossary_api_db) as conn:
            conn.execute(
                "UPDATE glossary_term_evidence SET evidence_json = '{\"sample\":\"after\"}' WHERE id = ?",
                (evidence_id,),
            )
            conn.execute("UPDATE glossary_history SET actor = 'drift' WHERE id = ?", (history_id,))
            conn.commit()
        drift = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": canonical_id,
                "duplicate_ids": [duplicate_id],
                "digest": drift_preview.json()["digest"],
            },
            headers=headers,
        )
        fresh_preview = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": canonical_id, "duplicate_ids": [duplicate_id]},
            headers=headers,
        )
        applied = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": canonical_id,
                "duplicate_ids": [duplicate_id],
                "digest": fresh_preview.json()["digest"],
            },
            headers=headers,
        )
        blocked_restore = await client.post(
            f"/api/glossary/terms/{duplicate_id}/restore", headers=headers
        )
        archived_canonical = await client.delete(
            f"/api/glossary/terms/{canonical_id}", headers=headers
        )
        restored_duplicate = await client.post(
            f"/api/glossary/terms/{duplicate_id}/restore", headers=headers
        )

    assert drift.status_code == 409
    assert drift.json()["detail"]["code"] == "preview_mismatch"
    assert applied.status_code == 200
    assert blocked_restore.status_code == 409
    assert blocked_restore.json()["detail"] == {
        "code": "normalized_source_collision",
        "resolution": "archive_active_canonical_first",
    }
    assert archived_canonical.status_code == 200
    assert restored_duplicate.status_code == 200
    with get_connection(glossary_api_db) as conn:
        evidence = conn.execute(
            "SELECT term_id, book_id, chapter_id FROM glossary_term_evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        history = conn.execute(
            "SELECT term_id, book_id FROM glossary_history WHERE id = ?", (history_id,)
        ).fetchone()
    assert tuple(evidence) == (canonical_id, provenance_book, 9)
    assert tuple(history) == (canonical_id, provenance_book)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "lock"])
async def test_bulk_approve_and_lock_reject_standalone_conflict_rows_atomically(
    glossary_api_db: Path,
    action: str,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    ready_id = put_glossary_term(
        glossary_api_db, book_id, f"ready-{action}", "sẵn", approved=0, review_status="NEEDS_REVIEW"
    )
    conflict_id = put_glossary_term(
        glossary_api_db, book_id, f"conflict-{action}", "xung đột", approved=0, review_status="CONFLICT"
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": action,
                "terms": [
                    {"id": ready_id, "expected_version": _version(glossary_api_db, ready_id)},
                    {"id": conflict_id, "expected_version": _version(glossary_api_db, conflict_id)},
                ],
            },
            headers=headers,
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "unresolved_conflict"
    with get_connection(glossary_api_db) as conn:
        rows = conn.execute(
            "SELECT review_status, version FROM glossary_terms WHERE id IN (?, ?) ORDER BY id",
            (ready_id, conflict_id),
        ).fetchall()
    assert [tuple(row) for row in rows] == [("NEEDS_REVIEW", 1), ("CONFLICT", 1)]


@pytest.mark.asyncio
async def test_exported_json_envelope_and_csv_are_direct_preview_and_apply_inputs(
    glossary_api_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(
        glossary_api_db, book_id, "round trip", "khứ hồi", approved=0,
        review_status="NEEDS_REVIEW", mode="context", variants="round-trip", notes_vi="note",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        exported_json = await client.get(
            f"/api/glossary/export?book_id={book_id}&format=json&scope=book", headers=headers
        )
        exported_csv = await client.get(
            f"/api/glossary/export?book_id={book_id}&format=csv&scope=book", headers=headers
        )

    json_db = tmp_path / "json-direct.sqlite"
    init_db(json_db)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: json_db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        json_preview = await client.post(
            "/api/glossary/import/preview", content=exported_json.content,
            headers={**headers, "Content-Type": "application/json"},
        )
        json_apply_payload = {**exported_json.json(), "digest": json_preview.json()["digest"]}
        json_apply = await client.post(
            "/api/glossary/import/apply", json=json_apply_payload, headers=headers
        )

    csv_db = tmp_path / "csv-direct.sqlite"
    init_db(csv_db)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: csv_db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        csv_preview = await client.post(
            "/api/glossary/import/preview?conflict_policy=reject_conflicts",
            content=exported_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )
        csv_apply = await client.post(
            f"/api/glossary/import/apply?digest={csv_preview.json()['digest']}&conflict_policy=reject_conflicts",
            content=exported_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )

    assert json_preview.status_code == 200
    assert json_apply.status_code == 200
    assert csv_preview.status_code == 200
    assert csv_preview.json()["conflict_policy"] == "reject_conflicts"
    assert csv_apply.status_code == 200
    with get_connection(csv_db) as conn:
        row = conn.execute(
            "SELECT review_status, approved, mode, variants, notes_vi FROM glossary_terms"
        ).fetchone()
    assert tuple(row) == ("NEEDS_REVIEW", 0, "context", "round-trip", "note")


@pytest.mark.asyncio
async def test_endpoint_exports_round_trip_blank_targets_and_empty_scopes_without_reshaping(
    glossary_api_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    put_glossary_term(
        glossary_api_db, book_id, "待译", "", approved=0, review_status="NEEDS_REVIEW"
    )
    archived_id = put_glossary_term(
        glossary_api_db, book_id, "旧待译", "", approved=0, review_status="CONFLICT"
    )
    empty_book_id = add_book(glossary_api_db, "Empty")
    with get_connection(glossary_api_db) as conn:
        conn.execute(
            "UPDATE glossary_terms SET archived_at = '2026-08-23T00:00:00Z', "
            "approved = 1, review_status = 'APPROVED' WHERE id = ?",
            (archived_id,),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        blank_csv = await client.get(
            f"/api/glossary/export?book_id={book_id}&format=csv&scope=book", headers=headers
        )
        empty_json = await client.get(
            f"/api/glossary/export?book_id={empty_book_id}&format=json&scope=book",
            headers=headers,
        )
        empty_csv = await client.get(
            f"/api/glossary/export?book_id={empty_book_id}&format=csv&scope=book",
            headers=headers,
        )
        empty_json_preview = await client.post(
            "/api/glossary/import/preview", content=empty_json.content,
            headers={**headers, "Content-Type": "application/json"},
        )
        empty_json_apply = await client.post(
            "/api/glossary/import/apply",
            json={**empty_json.json(), "digest": empty_json_preview.json()["digest"]},
            headers=headers,
        )
        empty_csv_preview = await client.post(
            "/api/glossary/import/preview", content=empty_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )
        empty_csv_apply = await client.post(
            f"/api/glossary/import/apply?digest={empty_csv_preview.json().get('digest', '0' * 64)}",
            content=empty_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )

    expected_header = [
        "schema_version", "scope", "scope_book_id", "id", "book_id", "source_term",
        "target_term", "category", "confidence", "approved", "locked", "review_status",
        "mode", "pinyin", "notes_vi", "variants", "occurrence_count", "priority",
        "genre", "term_type", "alternatives", "gender", "first_seen_chapter_id",
        "first_seen_chapter_number", "source_context", "archived_at", "version", "archived",
    ]
    empty_rows = list(csv.reader(empty_csv.text.splitlines()))
    assert empty_rows[0] == expected_header
    assert empty_rows[1][:3] == ["1", "book", str(empty_book_id)]
    assert all(value == "" for value in empty_rows[1][3:])
    assert empty_json_preview.status_code == 200
    assert empty_json_preview.json()["summary"] == {"added": 0, "updated": 0, "skipped": 0}
    assert empty_json_apply.status_code == 200
    assert empty_json_apply.json() == {"added": 0, "updated": 0, "skipped": 0, "errors": []}
    assert empty_csv_preview.status_code == 200
    assert empty_csv_preview.json()["summary"] == {"added": 0, "updated": 0, "skipped": 0}
    assert empty_csv_apply.status_code == 200
    assert empty_csv_apply.json() == {"added": 0, "updated": 0, "skipped": 0, "errors": []}

    destination = tmp_path / "blank-target-round-trip.sqlite"
    init_db(destination)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: destination)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        preview = await client.post(
            "/api/glossary/import/preview", content=blank_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )
        applied = await client.post(
            f"/api/glossary/import/apply?digest={preview.json().get('digest', '0' * 64)}",
            content=blank_csv.content,
            headers={**headers, "Content-Type": "text/csv"},
        )

    assert preview.status_code == 200
    assert applied.status_code == 200
    with get_connection(destination) as conn:
        rows = conn.execute(
            "SELECT source_term, target_term, review_status, approved, archived_at "
            "FROM glossary_terms ORDER BY source_term"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("待译", "", "NEEDS_REVIEW", 0, ""),
        ("旧待译", "", "APPROVED", 1, "2026-08-23T00:00:00Z"),
    ]


@pytest.mark.asyncio
async def test_import_rejects_malformed_csv_and_scope_mismatch_with_typed_422(
    glossary_api_db: Path,
) -> None:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        malformed_csv = await client.post(
            "/api/glossary/import/preview",
            content=(
                "schema_version,scope,scope_book_id,source_term,target_term,book_id\n"
                "1,book,42,extra,cột,42,surplus\n"
            ),
            headers={**headers, "Content-Type": "text/csv"},
        )
        json_scope_mismatch = await client.post(
            "/api/glossary/import/preview",
            json={
                "schema_version": 1,
                "scope": {"type": "book", "book_id": 42},
                "terms": [{"book_id": 43, "source_term": "scope", "target_term": "phạm vi"}],
            },
            headers=headers,
        )
        csv_scope_mismatch = await client.post(
            "/api/glossary/import/preview",
            content=(
                "schema_version,scope,scope_book_id,source_term,target_term,book_id\n"
                "1,global,0,scope,phạm vi,42\n"
            ),
            headers={**headers, "Content-Type": "text/csv"},
        )

    assert malformed_csv.status_code == 422
    assert malformed_csv.json()["detail"] == {"code": "invalid_csv"}
    assert json_scope_mismatch.status_code == 422
    assert json_scope_mismatch.json()["detail"] == {"code": "scope_mismatch"}
    assert csv_scope_mismatch.status_code == 422
    assert csv_scope_mismatch.json()["detail"] == {"code": "scope_mismatch"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("item", "field", "code"),
    [
        ({"approved": True}, "approved", "invalid_type"),
        ({"locked": False}, "locked", "invalid_type"),
        ({"id": True}, "id", "invalid_type"),
        ({"priority": 2**63}, "priority", "out_of_range"),
        ({"version": 2**63}, "version", "out_of_range"),
        ({"occurrence_count": -(2**63) - 1}, "occurrence_count", "out_of_range"),
        ({"approved": -1, "locked": 1}, "item", "invalid_state"),
        ({"review_status": "APPROVED", "approved": 1, "locked": 1}, "item", "invalid_state"),
    ],
)
async def test_import_rejects_noncanonical_or_non_sqlite_values_with_typed_422(
    glossary_api_db: Path,
    item: dict,
    field: str,
    code: str,
) -> None:
    payload = {"source_term": "invalid", "target_term": "không hợp lệ", **item}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        preview = await client.post(
            "/api/glossary/import/preview", json={"items": [payload]}, headers=headers
        )

    assert preview.status_code == 422
    assert preview.json()["detail"] == {
        "code": "validation_failed",
        "errors": [{"item": 1, "field": field, "code": code}],
    }


@pytest.mark.asyncio
async def test_conflict_query_uses_sql_pagination_and_never_calls_unbounded_legacy_helper(
    glossary_api_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database import glossary_repository as repository_module
    from app.database.glossary_repository import GlossaryRepository

    book_id = add_book(glossary_api_db, "Book")
    with get_connection(glossary_api_db) as conn:
        for index in range(8):
            for suffix in ("a", "b"):
                conn.execute(
                    """
                    INSERT INTO glossary_terms
                        (book_id, source_term, source_key, target_term, approved, review_status, version)
                    VALUES (?, ?, ?, ?, 0, 'CONFLICT', 1)
                    """,
                    (book_id, f"source-{index}-{suffix}", f"key-{index}", suffix),
                )
        conn.commit()

    statements: list[str] = []
    real_get_connection = repository_module.get_connection

    @contextmanager
    def traced_connection(path: Path):
        with real_get_connection(path) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(repository_module, "get_connection", traced_connection)
    result = GlossaryRepository(glossary_api_db).query_conflicts(
        book_id=book_id, page=2, per_page=3
    )
    assert len(result["items"]) == 3
    assert result["total"] == 8
    normalized_sql = [" ".join(statement.split()).upper() for statement in statements]
    assert any("LIMIT 3 OFFSET 3" in statement for statement in normalized_sql)
    assert any("LIMIT 200" in statement for statement in normalized_sql)
    assert not any("GROUP_CONCAT(ID)" in statement for statement in normalized_sql)
    assert not any(
        "SELECT G.*" in statement
        and "LIMIT" not in statement
        and "WHERE G.ID IN" not in statement
        for statement in normalized_sql
    )

    def fail_unbounded(*_args, **_kwargs):
        raise AssertionError("unbounded legacy conflict helper called")

    monkeypatch.setattr(
        "app.mobile_api.services.glossary_service.GlossaryService.get_conflicts",
        fail_unbounded,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.get(
            f"/api/glossary/conflicts?book_id={book_id}&page=1&per_page=3", headers=headers
        )
    assert response.status_code == 200
    assert len(response.json()["conflicts"]) <= 3


@pytest.mark.asyncio
async def test_large_conflict_group_is_resolved_in_stable_mergeable_200_member_batches(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    with get_connection(glossary_api_db) as conn:
        conn.executemany(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked,
                 review_status, version, archived_at)
            VALUES (?, ?, 'same-key', ?, 0, 0, 'CONFLICT', 1, '')
            """,
            [(book_id, f"unique-{index:03d}", f"target-{index:03d}") for index in range(250)],
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        first_page = await client.get(
            f"/api/glossary/conflicts?book_id={book_id}&page=1&per_page=1&include_legacy=false",
            headers=headers,
        )
        first_group = first_page.json()["items"][0]
        first_ids = [member["id"] for member in first_group["members"]]
        first_canonical = first_group.get("canonical_id", first_ids[0])
        first_preview = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": first_canonical, "duplicate_ids": first_ids[1:]},
            headers=headers,
        )
        first_apply = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": first_canonical,
                "duplicate_ids": first_ids[1:],
                "digest": first_preview.json().get("digest", "0" * 64),
            },
            headers=headers,
        )
        second_page = await client.get(
            f"/api/glossary/conflicts?book_id={book_id}&page=1&per_page=1&include_legacy=false",
            headers=headers,
        )
        second_group = second_page.json()["items"][0]
        second_ids = [member["id"] for member in second_group["members"]]
        second_canonical = second_group.get("canonical_id", second_ids[0])
        second_preview = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": second_canonical, "duplicate_ids": second_ids[1:]},
            headers=headers,
        )
        second_apply = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": second_canonical,
                "duplicate_ids": second_ids[1:],
                "digest": second_preview.json().get("digest", "0" * 64),
            },
            headers=headers,
        )
        resolved = await client.get(
            f"/api/glossary/conflicts?book_id={book_id}&page=1&per_page=1&include_legacy=false",
            headers=headers,
        )

    assert first_page.status_code == 200
    assert first_group.get("member_total") == 250
    assert first_group.get("members_truncated") is True
    assert len(first_ids) == 200
    assert first_group.get("canonical_id") == first_ids[0]
    assert first_preview.status_code == 200
    assert first_apply.status_code == 200
    assert first_apply.json()["merged"] == 199
    assert second_group["id"] == first_group["id"]
    assert second_group.get("canonical_id") == first_group.get("canonical_id")
    assert second_group.get("member_total") == 51
    assert second_group.get("members_truncated") is False
    assert len(second_ids) == 51
    assert second_ids[0] == first_ids[0]
    assert second_preview.status_code == 200
    assert second_apply.status_code == 200
    assert second_apply.json()["merged"] == 50
    assert resolved.status_code == 200
    assert resolved.json()["items"] == []


def test_legacy_conflict_truncation_uses_member_rows_not_distinct_target_count(
    glossary_api_db: Path,
) -> None:
    rows = []
    for index in range(25):
        book_id = add_book(glossary_api_db, f"Book {index}")
        rows.append((book_id, f"target-{index % 2}"))
    with get_connection(glossary_api_db) as conn:
        conn.executemany(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked,
                 review_status, version, term_type)
            VALUES (?, 'shared-source', 'shared-source', ?, 0, 0, 'NEEDS_REVIEW', 1, 'other')
            """,
            rows,
        )
        conn.commit()

    from app.database.glossary_repository import GlossaryRepository

    conflict = GlossaryRepository(glossary_api_db).query_legacy_conflicts(
        limit=1, member_limit=20
    )[0]
    assert len(conflict["targets"]) == 20
    assert conflict["truncated"] is True
