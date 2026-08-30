from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from app.database.db import (
    add_book,
    approve_glossary_term,
    auto_approve_glossary,
    delete_glossary_term,
    get_connection,
    init_db,
    list_glossary,
    glossary_stats,
    load_glossary,
    load_locked_glossary_terms,
    put_glossary_term,
    reject_glossary_term,
    set_glossary_term_locked,
    update_glossary_term,
)
from app.database.glossary_history import ensure_history_table
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app


LEGACY_GLOSSARY_SCHEMA = """
CREATE TABLE glossary_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER DEFAULT 0,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT 'term',
    confidence REAL DEFAULT 1.0,
    approved INTEGER DEFAULT 1,
    mode TEXT DEFAULT '',
    pinyin TEXT DEFAULT '',
    notes_vi TEXT DEFAULT '',
    variants TEXT DEFAULT '',
    occurrence_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    locked INTEGER DEFAULT 0,
    genre TEXT DEFAULT '',
    term_type TEXT DEFAULT 'term',
    alternatives TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    first_seen_chapter_id INTEGER DEFAULT 0,
    first_seen_chapter_number INTEGER DEFAULT 0,
    review_status TEXT DEFAULT '',
    source_context TEXT DEFAULT '',
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT '',
    UNIQUE(book_id, source_term)
);
CREATE TABLE glossary_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER DEFAULT 0,
    source_term TEXT NOT NULL,
    target_term TEXT DEFAULT '',
    action TEXT NOT NULL,
    old_target TEXT DEFAULT '',
    old_mode TEXT DEFAULT '',
    new_mode TEXT DEFAULT '',
    user TEXT DEFAULT '',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _legacy_term(
    conn: sqlite3.Connection,
    source: str,
    target: str,
    status: str,
    approved: int,
    locked: int,
    *,
    mode: str = "translate",
) -> None:
    conn.execute(
        """
        INSERT INTO glossary_terms
            (book_id, source_term, target_term, review_status, approved, locked, mode)
        VALUES (7, ?, ?, ?, ?, ?, ?)
        """,
        (source, target, status, approved, locked, mode),
    )


def _state(conn: sqlite3.Connection, source: str) -> tuple[str, int, int]:
    row = conn.execute(
        "SELECT review_status, approved, locked FROM glossary_terms WHERE source_term = ?",
        (source,),
    ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1]), int(row[2])


def _assert_conflict(exc: pytest.ExceptionInfo[Exception], code: str) -> None:
    assert type(exc.value).__name__ == "GlossaryStateConflict"
    assert getattr(exc.value, "code", "") == code


def test_phase1_migration_is_additive_idempotent_and_repairs_legacy_states(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_GLOSSARY_SCHEMA)
        _legacy_term(conn, "valid conflict", "một", "CONFLICT", 0, 0)
        _legacy_term(conn, "invalid conflict", "hai", "CONFLICT", 1, 0)
        _legacy_term(conn, "invalid tuple", "ba", "APPROVED", 0, 0)
        _legacy_term(conn, "active blank", "\u3000", "APPROVED", 1, 0)
        _legacy_term(conn, "locked", "bốn", "LOCKED", 1, 1)
        _legacy_term(conn, "rejected blank", " ", "REJECTED", -1, 0)
        _legacy_term(conn, "pending blank", " ", "NEEDS_REVIEW", 0, 0)
        _legacy_term(conn, "blank legacy mode", "năm", "APPROVED", 1, 0, mode="")
        _legacy_term(conn, "Ａ\u3000Beta", "one", "APPROVED", 1, 0)
        _legacy_term(conn, "a beta", "two", "APPROVED", 1, 0)
        conn.execute(
            """
            INSERT INTO glossary_history (book_id, source_term, target_term, action)
            VALUES (7, 'locked', 'bốn', 'add')
            """
        )

    init_db(db_path)
    init_db(db_path)

    with get_connection(db_path) as conn:
        term_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)")}
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_history)")}
        evidence_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_term_evidence)")}
        assert {"source_key", "version", "archived_at"} <= term_columns
        assert {"term_id", "before_json", "after_json", "actor", "request_id", "version"} <= history_columns
        assert {"id", "term_id", "book_id", "chapter_id", "extractor", "evidence_type"} <= evidence_columns
        assert _state(conn, "valid conflict") == ("CONFLICT", 0, 0)
        assert _state(conn, "invalid conflict") == ("CONFLICT", 0, 0)
        assert _state(conn, "invalid tuple") == ("CONFLICT", 0, 0)
        assert _state(conn, "active blank") == ("CONFLICT", 0, 0)
        assert _state(conn, "locked") == ("LOCKED", 1, 1)
        assert _state(conn, "rejected blank") == ("REJECTED", -1, 0)
        assert _state(conn, "pending blank") == ("NEEDS_REVIEW", 0, 0)
        blank_mode = conn.execute(
            "SELECT mode FROM glossary_terms WHERE source_term = 'blank legacy mode'"
        ).fetchone()[0]
        assert blank_mode == ""
        normalized = conn.execute(
            "SELECT source_key FROM glossary_terms WHERE source_term IN ('Ａ\u3000Beta', 'a beta') ORDER BY id"
        ).fetchall()
        assert [row[0] for row in normalized] == ["a beta", "a beta"]
        assert conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM glossary_history").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("status", "approved", "locked", "expected"),
    [
        ("NEEDS_REVIEW", 0, 0, ("NEEDS_REVIEW", 0, 0)),
        ("APPROVED", 1, 0, ("APPROVED", 1, 0)),
        ("REJECTED", -1, 0, ("REJECTED", -1, 0)),
        ("LOCKED", 1, 1, ("LOCKED", 1, 1)),
        ("CONFLICT", 0, 0, ("CONFLICT", 0, 0)),
        ("NEEDS_REVIEW", 1, 0, ("CONFLICT", 0, 0)),
        ("APPROVED", 1, 1, ("CONFLICT", 0, 0)),
        ("REJECTED", -1, 1, ("CONFLICT", 0, 0)),
        ("LOCKED", 0, 1, ("CONFLICT", 0, 0)),
        ("CONFLICT", 0, 1, ("CONFLICT", 0, 0)),
        ("APPROVED", 1.5, 0, ("CONFLICT", 0, 0)),
        (" APPROVED ", 1, 0, ("CONFLICT", 0, 0)),
        ("unknown", 0, 0, ("CONFLICT", 0, 0)),
    ],
)
def test_migration_enforces_the_canonical_state_truth_table(
    tmp_path: Path,
    status: str,
    approved: int | float,
    locked: int,
    expected: tuple[str, int, int],
) -> None:
    db_path = tmp_path / "truth-table.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_GLOSSARY_SCHEMA)
        _legacy_term(conn, "state", "target", status, approved, locked)

    init_db(db_path)

    with get_connection(db_path) as conn:
        assert _state(conn, "state") == expected


def test_migration_marks_normalized_active_target_group_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "normalized-conflict.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_GLOSSARY_SCHEMA)
        _legacy_term(conn, "Ａ Beta", "one", "APPROVED", 1, 0)
        _legacy_term(conn, "a beta", "two", "APPROVED", 1, 0)

    init_db(db_path)
    init_db(db_path)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT review_status, approved, locked FROM glossary_terms ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [("CONFLICT", 0, 0), ("CONFLICT", 0, 0)]


def test_source_key_normalizes_latin_compatibility_whitespace_and_preserves_han(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    first_id = put_glossary_term(temp_db_path, 3, "  甲Ａ\u3000Beta  ", "một")
    second_id = put_glossary_term(temp_db_path, 3, "甲a beta", "hai")

    assert first_id == second_id
    with get_connection(temp_db_path) as conn:
        rows = conn.execute(
            "SELECT id, source_term, source_key, target_term FROM glossary_terms WHERE book_id = 3"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["source_key"] == "甲a beta"
    assert rows[0]["target_term"] == "hai"


def test_all_mutations_use_canonical_transitions_and_full_atomic_history(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(
        temp_db_path,
        4,
        "灵石",
        "linh thạch",
        approved=0,
        review_status="NEEDS_REVIEW",
        mode="translate",
    )
    assert isinstance(term_id, int) and term_id > 0
    assert approve_glossary_term(temp_db_path, term_id)
    assert update_glossary_term(temp_db_path, term_id, target_term="linh thạch mới", notes_vi="reviewed")
    assert set_glossary_term_locked(temp_db_path, term_id, True)
    assert set_glossary_term_locked(temp_db_path, term_id, False)
    assert reject_glossary_term(temp_db_path, term_id)
    assert delete_glossary_term(temp_db_path, term_id)

    from app.database.glossary_repository import GlossaryRepository

    assert GlossaryRepository(temp_db_path).restore(term_id, actor="operator", request_id="req-restore")

    with get_connection(temp_db_path) as conn:
        term = conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()
        history = conn.execute(
            "SELECT * FROM glossary_history WHERE term_id = ? ORDER BY id", (term_id,)
        ).fetchall()
    assert (term["review_status"], term["approved"], term["locked"]) == ("REJECTED", -1, 0)
    assert term["archived_at"] == ""
    assert term["version"] == 8
    assert [row["action"] for row in history] == [
        "add",
        "approve",
        "update",
        "lock",
        "unlock",
        "reject",
        "archive",
        "restore",
    ]
    for expected_version, row in enumerate(history, start=1):
        before = json.loads(row["before_json"])
        after = json.loads(row["after_json"])
        assert row["version"] == expected_version
        assert after["id"] == term_id
        assert after["version"] == expected_version
        if expected_version == 1:
            assert before == {}
        else:
            assert before["version"] == expected_version - 1
    assert history[-1]["actor"] == "operator"
    assert history[-1]["request_id"] == "req-restore"


def test_rejecting_locked_and_approving_blank_terms_are_typed_conflicts(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    locked_id = put_glossary_term(temp_db_path, 5, "锁定", "khóa", locked=1, approved=1)
    blank_id = put_glossary_term(
        temp_db_path,
        5,
        "空白",
        "",
        approved=0,
        review_status="NEEDS_REVIEW",
    )

    with pytest.raises(Exception) as locked_exc:
        reject_glossary_term(temp_db_path, locked_id)
    _assert_conflict(locked_exc, "locked_term")

    with pytest.raises(Exception) as blank_exc:
        approve_glossary_term(temp_db_path, blank_id)
    _assert_conflict(blank_exc, "target_required")


def test_creating_an_active_blank_term_records_conflict_state(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    put_glossary_term(temp_db_path, 5, "空目标", "\u3000", approved=1)

    with get_connection(temp_db_path) as conn:
        assert _state(conn, "空目标") == ("CONFLICT", 0, 0)


def test_lock_approves_and_unlock_keeps_the_term_approved(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(
        temp_db_path,
        6,
        "待审",
        "chờ duyệt",
        approved=0,
        review_status="NEEDS_REVIEW",
    )

    assert set_glossary_term_locked(temp_db_path, term_id, True)
    with get_connection(temp_db_path) as conn:
        assert _state(conn, "待审") == ("LOCKED", 1, 1)

    assert set_glossary_term_locked(temp_db_path, term_id, False)
    with get_connection(temp_db_path) as conn:
        assert _state(conn, "待审") == ("APPROVED", 1, 0)


def test_generic_update_cannot_reject_a_locked_term(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 6, "锁", "khóa", locked=1)

    with pytest.raises(Exception) as exc:
        update_glossary_term(temp_db_path, term_id, review_status="REJECTED")

    _assert_conflict(exc, "locked_term")


def test_generic_update_approval_requires_a_nonblank_target(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 6, "空", "", approved=0)

    with pytest.raises(Exception) as exc:
        update_glossary_term(temp_db_path, term_id, approved=1)

    _assert_conflict(exc, "target_required")


@pytest.mark.parametrize(
    "updates",
    [
        {"approved": 0},
        {"review_status": "NEEDS_REVIEW"},
    ],
)
def test_generic_update_cannot_downgrade_a_locked_term(
    temp_db_path: Path,
    updates: dict[str, object],
) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 6, "锁定状态", "khóa", locked=1)

    with pytest.raises(Exception) as exc:
        update_glossary_term(temp_db_path, term_id, **updates)

    _assert_conflict(exc, "invalid_transition")


def test_unlock_only_transitions_a_valid_locked_term(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    pending_id = put_glossary_term(temp_db_path, 6, "待审解锁", "chờ", approved=0)
    locked_id = put_glossary_term(temp_db_path, 6, "损坏锁", "khóa", locked=1)
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE glossary_terms SET target_term = '' WHERE id = ?", (locked_id,))
        conn.commit()

    assert not set_glossary_term_locked(temp_db_path, pending_id, False)
    with pytest.raises(Exception) as exc:
        set_glossary_term_locked(temp_db_path, locked_id, False)

    _assert_conflict(exc, "target_required")
    with get_connection(temp_db_path) as conn:
        assert _state(conn, "待审解锁") == ("NEEDS_REVIEW", 0, 0)
        assert _state(conn, "损坏锁") == ("LOCKED", 1, 1)


def test_generic_unlock_rejects_an_already_approved_term(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 6, "已批准", "đã duyệt")

    with pytest.raises(Exception) as exc:
        update_glossary_term(temp_db_path, term_id, locked=0)

    _assert_conflict(exc, "invalid_transition")


def test_existing_pending_blank_upsert_cannot_become_approved(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 6, "空白更新", "", approved=0)

    assert put_glossary_term(temp_db_path, 6, "空白更新", "", approved=1) == term_id

    with get_connection(temp_db_path) as conn:
        assert _state(conn, "空白更新") == ("CONFLICT", 0, 0)


def test_approve_and_lock_refuse_unresolved_same_scope_normalized_target_conflict(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked, review_status, version)
            VALUES
                (9, 'Ａ Beta', 'a beta', 'một', 0, 0, 'CONFLICT', 1),
                (9, 'a beta', 'a beta', 'hai', 0, 0, 'CONFLICT', 1)
            """
        )
        ids = [row[0] for row in conn.execute("SELECT id FROM glossary_terms WHERE book_id = 9 ORDER BY id")]
        conn.commit()

    for mutation in (
        lambda: approve_glossary_term(temp_db_path, ids[0]),
        lambda: set_glossary_term_locked(temp_db_path, ids[0], True),
    ):
        with pytest.raises(Exception) as exc:
            mutation()
        _assert_conflict(exc, "normalized_target_conflict")


def test_normalized_legacy_collision_refuses_upsert_and_restore(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked, review_status, archived_at, version)
            VALUES
                (10, 'Ａ Beta', 'a beta', 'một', 1, 0, 'APPROVED', '', 1),
                (10, 'a beta', 'a beta', 'một', 1, 0, 'APPROVED', '2026-01-01T00:00:00+00:00', 1)
            """
        )
        archived_id = conn.execute(
            "SELECT id FROM glossary_terms WHERE archived_at != ''"
        ).fetchone()[0]
        conn.commit()

    with pytest.raises(Exception) as upsert_exc:
        put_glossary_term(temp_db_path, 10, "a beta", "ba")
    _assert_conflict(upsert_exc, "normalized_source_collision")

    from app.database.glossary_repository import GlossaryRepository

    with pytest.raises(Exception) as restore_exc:
        GlossaryRepository(temp_db_path).restore(archived_id)
    _assert_conflict(restore_exc, "normalized_source_collision")


def test_history_setup_never_commits_callers_transaction(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 11, "事务", "giao dịch")

    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE glossary_terms SET target_term = 'must rollback' WHERE id = ?", (term_id,))
        ensure_history_table(conn)
        conn.rollback()

    with get_connection(temp_db_path) as conn:
        target = conn.execute("SELECT target_term FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()[0]
    assert target == "giao dịch"


def test_history_failure_rolls_back_term_mutation(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 12, "原子", "nguyên tử")
    with get_connection(temp_db_path) as conn:
        before = dict(conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone())
        conn.execute(
            """
            CREATE TRIGGER reject_glossary_update_history
            BEFORE INSERT ON glossary_history
            WHEN NEW.action = 'update'
            BEGIN
                SELECT RAISE(ABORT, 'history rejected');
            END
            """
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="history rejected"):
        update_glossary_term(temp_db_path, term_id, target_term="must not persist")

    with get_connection(temp_db_path) as conn:
        after = dict(conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone())
    assert after == before


def test_history_snapshots_capture_bounded_metadata_and_private_content_digests(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    secret = "private-context-" + "x" * 5000
    book_id = add_book(temp_db_path, "Private audit", owner_user_id="audit-owner")
    term_id = put_glossary_term(
        temp_db_path,
        book_id,
        "隐私",
        "riêng tư",
        category="concept",
        confidence=0.75,
        mode="context",
        notes_vi=secret,
        variants=secret + "-variants",
        alternatives=secret,
        source_context=secret,
        priority=7,
        term_type="concept",
        genre="tien_hiep",
        gender="neutral",
    )
    update_glossary_term(
        temp_db_path,
        term_id,
        category="title",
        mode="translate",
        priority=11,
        term_type="title",
        gender="unknown",
    )

    with get_connection(temp_db_path) as conn:
        rows = conn.execute(
            "SELECT source_term, target_term, before_json, after_json "
            "FROM glossary_history WHERE term_id = ? ORDER BY id",
            (term_id,),
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert secret not in row["before_json"]
        assert secret not in row["after_json"]
        assert len(row["before_json"]) < 4096
        assert len(row["after_json"]) < 4096
        assert row["source_term"] == "隐私"
        assert row["target_term"] == "riêng tư"

    before = json.loads(rows[-1]["before_json"])
    after = json.loads(rows[-1]["after_json"])
    assert before["category"] == "concept"
    assert after["category"] == "title"
    assert before["confidence"] == 0.75
    assert after["confidence"] == 0.75
    assert before["mode"] == "context"
    assert after["mode"] == "translate"
    assert before["priority"] == 7
    assert after["priority"] == 11
    assert before["term_type"] == "concept"
    assert after["term_type"] == "title"
    assert before["gender"] == "neutral"
    assert after["gender"] == "unknown"
    assert after["scope"] == "book"
    assert after["owner_user_id"] == "audit-owner"
    assert after["book_id"] == book_id
    assert after["evidence_count"] == 0
    assert after["status"] == "APPROVED"
    assert after["archived"] is False
    assert after["approved"] == 1
    assert after["locked"] == 0
    assert after["version"] == before["version"] + 1
    assert after["created_at"]
    assert after["updated_at"]
    assert after["last_seen"]

    for field in (
        "source_term",
        "target_term",
        "variants",
        "notes_vi",
        "source_context",
        "alternatives",
    ):
        descriptor = after["content"][field]
        assert descriptor["present"] is True
        assert descriptor["length"] > 0
        assert len(descriptor["sha256"]) == 64
        assert descriptor["sha256"] not in {
            "隐私",
            "riêng tư",
            secret,
            secret + "-variants",
        }
        assert after["content"][field] == before["content"][field]


def test_archive_hides_old_readers_restore_api_recovers_and_locked_tuple_stays_compatible(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Archive API")
    term_id = put_glossary_term(temp_db_path, book_id, "灵根", "linh căn", approved=1, locked=1)
    assert load_glossary(temp_db_path, book_id)["灵根"] == "linh căn"
    locked = next(
        row for row in load_locked_glossary_terms(temp_db_path, book_id) if row["id"] == term_id
    )
    assert (locked["review_status"], locked["approved"], locked["locked"]) == ("LOCKED", 1, 1)

    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path)

    async def exercise_api() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/auth/login",
                json={
                    "username": mobile_settings.admin_username,
                    "password": mobile_settings.admin_password,
                },
            )
            headers = {
                "Authorization": f"Bearer {login.json()['access_token']}",
                "X-Request-ID": "req-archive-restore",
            }
            archived = await client.delete(f"/api/glossary/terms/{term_id}", headers=headers)
            restored = await client.post(f"/api/glossary/terms/{term_id}/restore", headers=headers)
            return archived, restored

    archived, restored = __import__("asyncio").run(exercise_api())
    assert archived.status_code == 200
    assert archived.json() == {"message": "Term deleted"}
    assert restored.status_code == 200
    assert restored.json() == {"message": "Term restored"}
    with get_connection(temp_db_path) as conn:
        row = conn.execute(
            "SELECT archived_at, review_status, approved, locked FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        history = conn.execute(
            "SELECT actor, request_id FROM glossary_history WHERE term_id = ? ORDER BY id DESC LIMIT 2",
            (term_id,),
        ).fetchall()
    assert tuple(row) == ("", "LOCKED", 1, 1)
    assert [entry["request_id"] for entry in history] == ["req-archive-restore", "req-archive-restore"]
    assert all(entry["actor"] == mobile_settings.admin_username for entry in history)
    assert list_glossary(temp_db_path, book_id)


def test_api_update_history_carries_actor_and_request_id(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Update history API")
    term_id = put_glossary_term(temp_db_path, book_id, "元婴", "Nguyên Anh", approved=0)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path)

    async def exercise_api() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/auth/login",
                json={
                    "username": mobile_settings.admin_username,
                    "password": mobile_settings.admin_password,
                },
            )
            return await client.patch(
                f"/api/glossary/terms/{term_id}",
                json={"notes_vi": "reviewed"},
                headers={
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "X-Request-ID": "req-update",
                },
            )

    response = __import__("asyncio").run(exercise_api())

    assert response.status_code == 200
    with get_connection(temp_db_path) as conn:
        history = conn.execute(
            "SELECT actor, request_id FROM glossary_history WHERE term_id = ? ORDER BY id DESC LIMIT 1",
            (term_id,),
        ).fetchone()
    assert tuple(history) == (mobile_settings.admin_username, "req-update")


def test_archived_terms_stay_out_of_legacy_stats_and_auto_approval(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    term_id = put_glossary_term(temp_db_path, 15, "归档", "lưu trữ", approved=0)
    put_glossary_term(temp_db_path, 15, "归档", "lưu trữ", approved=0)
    put_glossary_term(temp_db_path, 15, "归档", "lưu trữ", approved=0)
    assert delete_glossary_term(temp_db_path, term_id)

    assert glossary_stats(temp_db_path, 15)["total"] == 0
    assert auto_approve_glossary(temp_db_path, min_occurrences=3, book_id=15) == 0

    from app.database.glossary_repository import GlossaryRepository

    assert GlossaryRepository(temp_db_path).restore(term_id)
    with get_connection(temp_db_path) as conn:
        assert _state(conn, "归档") == ("NEEDS_REVIEW", 0, 0)
