from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection
from app.database.glossary_history import ensure_history_table


CANONICAL_STATES = {
    "NEEDS_REVIEW": (0, 0),
    "APPROVED": (1, 0),
    "REJECTED": (-1, 0),
    "LOCKED": (1, 1),
    "CONFLICT": (0, 0),
}


class GlossaryStateConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize_source_key(value: str) -> str:
    collapsed = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    return "".join(
        character.lower() if "LATIN" in unicodedata.name(character, "") else character
        for character in collapsed
    )


def _target_is_blank(value: object) -> bool:
    return not "".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _canonical_state(approved: object, locked: object, review_status: object) -> tuple[str, int, int]:
    status = review_status if isinstance(review_status, str) else ""
    expected = CANONICAL_STATES.get(status)
    if (
        expected is not None
        and type(approved) is int
        and type(locked) is int
        and (approved, locked) == expected
    ):
        return status, approved, locked
    return "CONFLICT", 0, 0


def _requested_state(approved: object, locked: object, review_status: object) -> tuple[str, int, int]:
    status = str(review_status or "").strip().upper()
    if int(locked or 0) == 1 or status == "LOCKED":
        return "LOCKED", 1, 1
    if int(approved or 0) < 0 or status == "REJECTED":
        return "REJECTED", -1, 0
    if status == "CONFLICT":
        return "CONFLICT", 0, 0
    if int(approved or 0) == 1 or status == "APPROVED":
        return "APPROVED", 1, 0
    return "NEEDS_REVIEW", 0, 0


def migrate_glossary_phase1(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)")}
    for definition in (
        "source_key TEXT NOT NULL DEFAULT ''",
        "version INTEGER NOT NULL DEFAULT 0",
        "archived_at TEXT NOT NULL DEFAULT ''",
    ):
        if definition.split()[0] not in columns:
            conn.execute(f"ALTER TABLE glossary_terms ADD COLUMN {definition}")

    for row in conn.execute(
        "SELECT id, source_term, target_term, review_status, approved, locked, archived_at FROM glossary_terms"
    ).fetchall():
        source_key = normalize_source_key(row["source_term"])
        state = _canonical_state(row["approved"], row["locked"], row["review_status"])
        if not row["archived_at"] and state[0] in {"APPROVED", "LOCKED"} and _target_is_blank(row["target_term"]):
            state = ("CONFLICT", 0, 0)
        conn.execute(
            """
            UPDATE glossary_terms
            SET source_key = ?, review_status = ?, approved = ?, locked = ?
            WHERE id = ?
            """,
            (source_key, *state, row["id"]),
        )

    active_groups: dict[tuple[int, str], list[sqlite3.Row]] = {}
    for row in conn.execute(
        """
        SELECT id, book_id, source_key, target_term
        FROM glossary_terms
        WHERE review_status IN ('APPROVED', 'LOCKED')
          AND COALESCE(archived_at, '') = ''
        ORDER BY id
        """
    ).fetchall():
        active_groups.setdefault((int(row["book_id"] or 0), row["source_key"]), []).append(row)
    for rows in active_groups.values():
        targets = {
            " ".join(unicodedata.normalize("NFKC", str(row["target_term"] or "")).split())
            for row in rows
        }
        if len(targets) > 1:
            conn.executemany(
                """
                UPDATE glossary_terms
                SET review_status = 'CONFLICT', approved = 0, locked = 0
                WHERE id = ?
                """,
                ((row["id"],) for row in rows),
            )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS glossary_term_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL DEFAULT 0,
            chapter_id INTEGER NOT NULL DEFAULT 0,
            extractor TEXT NOT NULL DEFAULT '',
            evidence_type TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (term_id) REFERENCES glossary_terms(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_evidence_term ON glossary_term_evidence(term_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_terms_source_key ON glossary_terms(book_id, source_key)")
    ensure_history_table(conn)


class GlossaryRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _actor(actor: str) -> str:
        return actor or os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

    @staticmethod
    def _row(conn: sqlite3.Connection, term_id: int) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()

    @staticmethod
    def _source_rows(conn: sqlite3.Connection, book_id: int, source_key: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM glossary_terms WHERE book_id = ? AND source_key = ? ORDER BY id",
            (book_id, source_key),
        ).fetchall()

    @staticmethod
    def _log(
        conn: sqlite3.Connection,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        actor: str,
        request_id: str,
    ) -> None:
        ensure_history_table(conn)
        def bounded_snapshot(row: dict[str, Any]) -> dict[str, Any]:
            if not row:
                return {}
            return {
                "id": row["id"],
                "book_id": row["book_id"],
                "review_status": row["review_status"],
                "approved": row["approved"],
                "locked": row["locked"],
                "version": row["version"],
                "archived": bool(row["archived_at"]),
                "target_present": not _target_is_blank(row["target_term"]),
            }

        conn.execute(
            """
            INSERT INTO glossary_history
                (term_id, book_id, source_term, target_term, action, old_target,
                 old_mode, new_mode, user, before_json, after_json, actor, request_id, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                after["id"],
                after["book_id"],
                after["source_term"],
                after["target_term"],
                action,
                before.get("target_term", ""),
                before.get("mode", ""),
                after.get("mode", ""),
                actor,
                json.dumps(bounded_snapshot(before), ensure_ascii=False, sort_keys=True),
                json.dumps(bounded_snapshot(after), ensure_ascii=False, sort_keys=True),
                actor,
                request_id,
                after["version"],
            ),
        )

    @staticmethod
    def _assert_target_and_conflicts(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> None:
        if _target_is_blank(row["target_term"]):
            raise GlossaryStateConflict("target_required")
        targets = conn.execute(
            """
            SELECT DISTINCT TRIM(target_term)
            FROM glossary_terms
            WHERE book_id = ? AND source_key = ? AND COALESCE(archived_at, '') = ''
              AND TRIM(target_term) != ''
            """,
            (row["book_id"], row["source_key"]),
        ).fetchall()
        if len(targets) > 1:
            raise GlossaryStateConflict("normalized_target_conflict")

    def put(self, *, actor: str = "", request_id: str = "", **values: Any) -> int:
        source = str(values["source"] or "").strip()
        if not source:
            return 0
        target = str(values["target"] or "").strip()
        book_id = int(values["book_id"])
        source_key = normalize_source_key(source)
        with get_connection(self.db_path) as conn:
            rows = self._source_rows(conn, book_id, source_key)
            if len(rows) > 1:
                raise GlossaryStateConflict("normalized_source_collision")
            if rows and values["preserve_existing"]:
                current = rows[0]
                term_id = int(current["id"])
                current_state = (current["review_status"], current["approved"], current["locked"])
                if current["archived_at"] or current_state != ("NEEDS_REVIEW", 0, 0):
                    return term_id
                before = dict(current)
                conn.execute(
                    """
                    UPDATE glossary_terms
                    SET occurrence_count = occurrence_count + 1,
                        last_seen = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        version = version + 1
                    WHERE id = ?
                    """,
                    (term_id,),
                )
                after = dict(self._row(conn, term_id))
                self._log(conn, "observe", before, after, self._actor(actor), request_id)
                conn.commit()
                return term_id
            before = dict(rows[0]) if rows else {}
            if rows and rows[0]["archived_at"]:
                raise GlossaryStateConflict("archived_term")

            if not rows:
                state = _requested_state(values["approved"], values["locked"], values["review_status"])
                if _target_is_blank(target) and state[0] in {"APPROVED", "LOCKED"}:
                    state = ("CONFLICT", 0, 0)
                conn.execute(
                    """
                    INSERT INTO glossary_terms
                        (book_id, source_term, source_key, target_term, category, confidence, approved, mode,
                         pinyin, notes_vi, variants, occurrence_count, priority, locked, genre,
                         term_type, alternatives, gender, first_seen_chapter_id,
                         first_seen_chapter_number, review_status, source_context, last_seen,
                         updated_at, version, archived_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, '')
                    """,
                    (
                        book_id, source, source_key, target, values["category"], values["confidence"],
                        state[1], values["mode"],
                        values["pinyin"], values["notes_vi"], values["variants"], values["priority"],
                        state[2], values["genre"], values["term_type"], values["alternatives"],
                        values["gender"], values["first_seen_chapter_id"], values["first_seen_chapter_number"],
                        state[0], values["source_context"],
                    ),
                )
                term_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                action = "add"
            else:
                current = rows[0]
                term_id = int(current["id"])
                target_to_store = target
                if (current["locked"] == 1 or current["approved"] != 0) and int(values["approved"] or 0) <= 0:
                    target_to_store = current["target_term"]
                state = _canonical_state(current["approved"], current["locked"], current["review_status"])
                if state[0] == "NEEDS_REVIEW":
                    state = _requested_state(values["approved"], values["locked"], values["review_status"])
                if _target_is_blank(target_to_store) and state[0] in {"APPROVED", "LOCKED"}:
                    state = ("CONFLICT", 0, 0)
                conn.execute(
                    """
                    UPDATE glossary_terms
                    SET target_term = ?, category = ?, mode = ?, pinyin = ?, notes_vi = ?, variants = ?,
                        confidence = ?, priority = ?, locked = ?, genre = ?, term_type = ?,
                        alternatives = COALESCE(NULLIF(?, ''), alternatives),
                        gender = COALESCE(NULLIF(?, ''), gender),
                        first_seen_chapter_id = CASE WHEN first_seen_chapter_id = 0 THEN ? ELSE first_seen_chapter_id END,
                        first_seen_chapter_number = CASE WHEN first_seen_chapter_number = 0 THEN ? ELSE first_seen_chapter_number END,
                        review_status = ?, approved = ?,
                        source_context = COALESCE(NULLIF(?, ''), source_context),
                        occurrence_count = occurrence_count + 1, last_seen = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP, version = version + 1
                    WHERE id = ?
                    """,
                    (
                        target_to_store, values["category"], values["mode"], values["pinyin"],
                        values["notes_vi"], values["variants"], values["confidence"], values["priority"],
                        state[2], values["genre"],
                        values["term_type"], values["alternatives"], values["gender"],
                        values["first_seen_chapter_id"], values["first_seen_chapter_number"], state[0], state[1],
                        values["source_context"], term_id,
                    ),
                )
                action = "update"
            after = dict(self._row(conn, term_id))
            self._log(conn, action, before, after, self._actor(actor), request_id)
            conn.commit()
            return term_id

    @staticmethod
    def _requested_update_state(current: sqlite3.Row, changes: dict[str, Any]) -> tuple[str, int, int]:
        if "locked" in changes:
            locked = int(changes["locked"] or 0)
            if locked not in {0, 1}:
                raise GlossaryStateConflict("invalid_transition")
            state = ("LOCKED", 1, 1) if locked else ("APPROVED", 1, 0)
            if "approved" in changes and int(changes["approved"]) != state[1]:
                raise GlossaryStateConflict("invalid_transition")
            if "review_status" in changes:
                status = str(changes["review_status"] or "").strip().upper()
                if status != state[0]:
                    raise GlossaryStateConflict("invalid_transition")
            return state
        if "review_status" in changes:
            status = str(changes["review_status"] or "").strip().upper()
            if status not in CANONICAL_STATES:
                raise GlossaryStateConflict("invalid_transition")
            state = (status, *CANONICAL_STATES[status])
            if "approved" in changes and int(changes["approved"]) != state[1]:
                raise GlossaryStateConflict("invalid_transition")
            return state
        if "approved" in changes:
            approved = int(changes["approved"])
            states = {-1: ("REJECTED", -1, 0), 0: ("NEEDS_REVIEW", 0, 0), 1: ("APPROVED", 1, 0)}
            if approved not in states:
                raise GlossaryStateConflict("invalid_transition")
            return states[approved]
        return _canonical_state(current["approved"], current["locked"], current["review_status"])

    def _validate_transition(
        self,
        conn: sqlite3.Connection,
        current: sqlite3.Row,
        action: str,
        candidate: sqlite3.Row | dict[str, Any],
    ) -> bool:
        current_state = (current["review_status"], current["approved"], current["locked"])
        if action == "unlock":
            if current_state != ("LOCKED", 1, 1):
                return False
            self._assert_target_and_conflicts(conn, candidate)
        elif action == "reject":
            if current["locked"] == 1:
                raise GlossaryStateConflict("locked_term")
            if current["review_status"] == "REJECTED" and current["approved"] == -1:
                return False
        elif action == "approve":
            if current["approved"] != 0:
                return False
            self._assert_target_and_conflicts(conn, candidate)
        elif action == "lock":
            if current_state == ("LOCKED", 1, 1):
                return False
            self._assert_target_and_conflicts(conn, candidate)
        elif action == "needs_review":
            if current_state != ("NEEDS_REVIEW", 0, 0):
                raise GlossaryStateConflict("invalid_transition")
        elif action == "conflict":
            if current["locked"] == 1:
                raise GlossaryStateConflict("invalid_transition")
        else:
            raise GlossaryStateConflict("invalid_transition")
        return True

    def update(self, term_id: int, *, actor: str = "", request_id: str = "", **updates: Any) -> bool:
        if updates.get("mode") is not None and updates["mode"] not in {"", "translate", "context", "transliterate"}:
            raise ValueError(f"Invalid mode: {updates['mode']}")
        changes = {key: value for key, value in updates.items() if value is not None}
        with get_connection(self.db_path) as conn:
            current = self._row(conn, term_id)
            if current is None or current["archived_at"]:
                return False
            if not changes:
                return True
            before = dict(current)
            merged = {**before, **changes}
            state_change = {"approved", "locked", "review_status"} & changes.keys()
            state = self._requested_update_state(current, changes)
            merged.update(review_status=state[0], approved=state[1], locked=state[2])
            if state_change:
                if "locked" in changes:
                    action = "lock" if int(changes["locked"] or 0) else "unlock"
                else:
                    action = {
                        "APPROVED": "unlock" if current["locked"] == 1 else "approve",
                        "LOCKED": "lock",
                        "REJECTED": "reject",
                        "NEEDS_REVIEW": "needs_review",
                        "CONFLICT": "conflict",
                    }[state[0]]
                current_state = (current["review_status"], current["approved"], current["locked"])
                if state == current_state and action not in {"lock", "unlock"}:
                    if state[0] in {"APPROVED", "LOCKED"}:
                        self._assert_target_and_conflicts(conn, merged)
                elif not self._validate_transition(conn, current, action, merged):
                    raise GlossaryStateConflict("invalid_transition")
            elif _target_is_blank(merged["target_term"]) and state[0] in {"APPROVED", "LOCKED"}:
                state = ("CONFLICT", 0, 0)
            changes.update(review_status=state[0], approved=state[1], locked=state[2])
            fields = [f"{column} = ?" for column in changes]
            conn.execute(
                f"UPDATE glossary_terms SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP, version = version + 1 WHERE id = ?",
                (*changes.values(), term_id),
            )
            after = dict(self._row(conn, term_id))
            self._log(conn, "update", before, after, self._actor(actor), request_id)
            conn.commit()
            return True

    def _transition(self, term_id: int, action: str, state: tuple[str, int, int], *, actor: str, request_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            current = self._row(conn, term_id)
            if current is None or current["archived_at"]:
                return False
            if not self._validate_transition(conn, current, action, current):
                return False
            before = dict(current)
            conn.execute(
                """
                UPDATE glossary_terms
                SET review_status = ?, approved = ?, locked = ?, updated_at = CURRENT_TIMESTAMP,
                    version = version + 1
                WHERE id = ?
                """,
                (*state, term_id),
            )
            after = dict(self._row(conn, term_id))
            self._log(conn, action, before, after, self._actor(actor), request_id)
            conn.commit()
            return True

    def approve(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        return self._transition(term_id, "approve", ("APPROVED", 1, 0), actor=actor, request_id=request_id)

    def reject(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        return self._transition(term_id, "reject", ("REJECTED", -1, 0), actor=actor, request_id=request_id)

    def set_locked(self, term_id: int, locked: bool, *, actor: str = "", request_id: str = "") -> bool:
        action = "lock" if locked else "unlock"
        state = ("LOCKED", 1, 1) if locked else ("APPROVED", 1, 0)
        return self._transition(term_id, action, state, actor=actor, request_id=request_id)

    def archive(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        with get_connection(self.db_path) as conn:
            current = self._row(conn, term_id)
            if current is None or current["archived_at"]:
                return False
            before = dict(current)
            conn.execute(
                "UPDATE glossary_terms SET archived_at = ?, updated_at = CURRENT_TIMESTAMP, version = version + 1 WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), term_id),
            )
            after = dict(self._row(conn, term_id))
            self._log(conn, "archive", before, after, self._actor(actor), request_id)
            conn.commit()
            return True

    def restore(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        with get_connection(self.db_path) as conn:
            current = self._row(conn, term_id)
            if current is None or not current["archived_at"]:
                return False
            collision = conn.execute(
                """
                SELECT 1 FROM glossary_terms
                WHERE book_id = ? AND source_key = ? AND id != ? AND COALESCE(archived_at, '') = ''
                LIMIT 1
                """,
                (current["book_id"], current["source_key"], term_id),
            ).fetchone()
            if collision:
                raise GlossaryStateConflict("normalized_source_collision")
            before = dict(current)
            conn.execute(
                "UPDATE glossary_terms SET archived_at = '', updated_at = CURRENT_TIMESTAMP, version = version + 1 WHERE id = ?",
                (term_id,),
            )
            after = dict(self._row(conn, term_id))
            self._log(conn, "restore", before, after, self._actor(actor), request_id)
            conn.commit()
            return True
