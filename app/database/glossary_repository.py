from __future__ import annotations

import json
import hashlib
import hmac
import math
import os
import re
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

WEAK_SOURCE_TERMS = {
    "的", "了", "是", "在", "有", "不", "也", "都", "就", "这", "那", "然后", "只是", "一个", "一下", "自己",
}
QUERY_SCOPES = {"all", "book", "global", "effective", "legacy"}
QUERY_SORTS = {
    "review": """
        (CASE WHEN approved = 0 THEN 0 ELSE -10 END
         + locked * 20 + priority
         + CASE term_type
             WHEN 'realm' THEN 100 WHEN 'sect' THEN 90 WHEN 'character' THEN 85
             WHEN 'place' THEN 85 WHEN 'artifact' THEN 80 WHEN 'technique' THEN 75
             WHEN 'concept' THEN 70 WHEN 'title' THEN 65 ELSE 0 END
         + CASE WHEN occurrence_count >= 2 THEN MIN(occurrence_count, 10) * 6 ELSE 0 END) DESC,
        occurrence_count DESC, length(source_term) DESC, source_term COLLATE NOCASE ASC, id ASC
    """,
    "source_asc": "source_term COLLATE NOCASE ASC, id ASC",
    "source_desc": "source_term COLLATE NOCASE DESC, id DESC",
    "updated_desc": "updated_at DESC, id DESC",
    "updated_asc": "updated_at ASC, id ASC",
    "priority_desc": "priority DESC, source_term COLLATE NOCASE ASC, id ASC",
    "evidence_desc": "evidence_count DESC, source_term COLLATE NOCASE ASC, id ASC",
}


class GlossaryStateConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GlossaryValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__("validation_failed")


IMPORT_FIELDS = {
    "category": "term",
    "confidence": 1.0,
    "mode": "translate",
    "pinyin": "",
    "notes_vi": "",
    "variants": "",
    "approved": 1,
    "priority": 0,
    "locked": 0,
    "genre": "",
    "term_type": "term",
    "alternatives": "",
    "gender": "",
    "first_seen_chapter_id": 0,
    "first_seen_chapter_number": 0,
    "review_status": "",
    "source_context": "",
    "occurrence_count": None,
    "archived_at": "",
}
IMPORT_POLICIES = {"skip_conflicts", "reject_conflicts"}
SQLITE_INTEGER_MIN = -(2**63)
SQLITE_INTEGER_MAX = 2**63 - 1
EXPORT_FIELDS = (
    "id", "book_id", "source_term", "target_term", "category", "confidence", "approved",
    "locked", "review_status", "mode", "pinyin", "notes_vi", "variants", "occurrence_count",
    "priority", "genre", "term_type", "alternatives", "gender", "first_seen_chapter_id",
    "first_seen_chapter_number", "source_context", "archived_at", "version",
)


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _variant_keys(value: object) -> set[str]:
    return {
        normalize_source_key(part)
        for part in re.split(r"[,;\n|]+", str(value or ""))
        if normalize_source_key(part)
    }


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
        "chapter_count INTEGER NOT NULL DEFAULT 0",
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
    phase5_index = next(
        (
            row
            for row in conn.execute("PRAGMA index_list(glossary_term_evidence)").fetchall()
            if row["name"] == "idx_glossary_evidence_phase5_unique"
        ),
        None,
    )
    if phase5_index is not None and int(phase5_index["unique"] or 0) == 1:
        conn.execute("DROP INDEX idx_glossary_evidence_phase5_unique")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_glossary_evidence_phase5_unique "
        "ON glossary_term_evidence(term_id, chapter_id, extractor) "
        "WHERE extractor IN ('deterministic-v2', 'hybrid-v1')"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS book_glossary_settings (
            book_id INTEGER PRIMARY KEY,
            extraction_mode TEXT NOT NULL DEFAULT 'deterministic'
                CHECK(extraction_mode IN ('deterministic', 'hybrid')),
            provider_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_terms_source_key ON glossary_terms(book_id, source_key)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_glossary_terms_scope_status "
        "ON glossary_terms(book_id, archived_at, review_status, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_glossary_terms_review_filters "
        "ON glossary_terms(review_status, term_type, mode, locked, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_glossary_terms_effective_source "
        "ON glossary_terms(source_key, book_id, archived_at, review_status)"
    )
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
    def _resource(row: sqlite3.Row | dict[str, Any], *, inherited: bool = False, evidence_count: int = 0) -> dict[str, Any]:
        resource = dict(row)
        resource["canonical_status"] = str(resource.get("review_status") or "CONFLICT")
        resource["version"] = int(resource.get("version") or 0)
        resource["archived"] = bool(resource.get("archived_at"))
        resource["inherited"] = inherited
        resource["evidence_count"] = evidence_count
        return resource

    def get_resource(self, term_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT g.*, (SELECT COUNT(*) FROM glossary_term_evidence e WHERE e.term_id = g.id) AS evidence_count
                FROM glossary_terms g
                WHERE g.id = ? AND COALESCE(g.archived_at, '') = ''
                """,
                (term_id,),
            ).fetchone()
        if row is None:
            return None
        return self._resource(row, evidence_count=int(row["evidence_count"] or 0))

    def get_detail(self, term_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT g.*, (SELECT COUNT(*) FROM glossary_term_evidence e WHERE e.term_id = g.id) AS evidence_count
                FROM glossary_terms g WHERE g.id = ?
                """,
                (term_id,),
            ).fetchone()
            if row is None:
                return None
            resource = self._resource(row, evidence_count=int(row["evidence_count"] or 0))
            evidence_rows = conn.execute(
                "SELECT * FROM glossary_term_evidence WHERE term_id = ? ORDER BY id",
                (term_id,),
            ).fetchall()
            history_rows = conn.execute(
                "SELECT * FROM glossary_history WHERE term_id = ? ORDER BY id",
                (term_id,),
            ).fetchall()

        evidence: list[dict[str, Any]] = []
        for row in evidence_rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(str(item.pop("evidence_json") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item["evidence"] = {}
            evidence.append(item)
        history: list[dict[str, Any]] = []
        for row in history_rows:
            item = dict(row)
            for key in ("before_json", "after_json"):
                try:
                    item[key.removesuffix("_json")] = json.loads(str(item.pop(key) or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    item[key.removesuffix("_json")] = {}
            history.append(item)
        resource.update(evidence=evidence, history=history)
        return resource

    @staticmethod
    def _query_cte(
        *,
        book_id: int | None,
        q: str,
        review_statuses: tuple[str, ...],
        term_type: str | None,
        mode: str | None,
        locked: bool | None,
        scope: str,
        approved: int | None,
        include_weak: bool,
        archived: bool,
        effective_ids: tuple[int, ...] | None,
    ) -> tuple[str, list[Any]]:
        if scope not in QUERY_SCOPES:
            raise ValueError("invalid_scope")
        where = [
            "COALESCE(g.archived_at, '') != ''" if archived else "COALESCE(g.archived_at, '') = ''"
        ]
        params: list[Any] = []
        if scope == "book":
            if book_id is None:
                raise ValueError("book_id_required")
            where.append("g.book_id = ?")
            params.append(book_id)
        elif scope == "global":
            where.append("g.book_id = 0")
        elif scope == "legacy" and book_id is not None:
            where.append("g.book_id IN (0, ?)")
            params.append(book_id)
        elif scope == "effective":
            if book_id is None:
                raise ValueError("book_id_required")
            if effective_ids is None:
                raise ValueError("effective_ids_required")
            where.append("g.id IN (SELECT CAST(value AS INTEGER) FROM json_each(?))")
            params.append(json.dumps(effective_ids))
        if q:
            like = f"%{q.casefold()}%"
            where.append(
                "(LOWER(g.source_term) LIKE ? OR LOWER(g.target_term) LIKE ? OR LOWER(g.source_key) LIKE ? "
                "OR LOWER(g.term_type) LIKE ? OR LOWER(g.notes_vi) LIKE ?)"
            )
            params.extend((like, like, like, like, like))
        if review_statuses:
            where.append(f"g.review_status IN ({','.join('?' for _ in review_statuses)})")
            params.extend(review_statuses)
        if term_type:
            where.append("g.term_type = ?")
            params.append(term_type)
        if mode:
            where.append("g.mode = ?")
            params.append(mode)
        if locked is not None:
            where.append("g.locked = ?")
            params.append(int(locked))
        if approved is not None:
            where.append("g.approved = ?")
            params.append(approved)
        if not include_weak and not archived:
            where.extend(
                [
                    "TRIM(g.source_term) != ''",
                    "TRIM(g.target_term) != ''",
                    "length(TRIM(g.source_term)) > 1",
                    f"g.source_term NOT IN ({','.join('?' for _ in WEAK_SOURCE_TERMS)})",
                ]
            )
            params.extend(sorted(WEAK_SOURCE_TERMS))
        cte = f"""
            WITH filtered AS (
                SELECT g.*,
                       CASE WHEN ? = 'effective' AND g.book_id = 0 THEN 1 ELSE 0 END AS inherited,
                       CASE WHEN g.book_id = 0 THEN 'global' ELSE 'book' END AS scope_label,
                       g.review_status AS canonical_status,
                       (SELECT COUNT(*) FROM glossary_term_evidence e WHERE e.term_id = g.id) AS evidence_count
                FROM glossary_terms g
                WHERE {' AND '.join(where)}
            )
        """
        return cte, [scope, *params]

    def query(
        self,
        *,
        book_id: int | None = None,
        q: str = "",
        review_statuses: tuple[str, ...] = (),
        term_type: str | None = None,
        mode: str | None = None,
        locked: bool | None = None,
        scope: str = "all",
        sort: str = "review",
        limit: int = 50,
        offset: int = 0,
        approved: int | None = None,
        include_weak: bool = False,
        archived: bool = False,
        effective_ids: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        order_by = QUERY_SORTS.get(sort)
        if order_by is None:
            raise ValueError("invalid_sort")
        cte, params = self._query_cte(
            book_id=book_id,
            q=q.strip(),
            review_statuses=review_statuses,
            term_type=term_type,
            mode=mode,
            locked=locked,
            scope=scope,
            approved=approved,
            include_weak=include_weak,
            archived=archived,
            effective_ids=effective_ids,
        )
        facet_sql = cte + """
            SELECT 'review_status' AS facet, review_status AS value, COUNT(*) AS count FROM filtered GROUP BY review_status
            UNION ALL SELECT 'term_type', term_type, COUNT(*) FROM filtered GROUP BY term_type
            UNION ALL SELECT 'mode', mode, COUNT(*) FROM filtered GROUP BY mode
            UNION ALL SELECT 'locked', CAST(locked AS TEXT), COUNT(*) FROM filtered GROUP BY locked
            UNION ALL SELECT 'scope', scope_label, COUNT(*) FROM filtered GROUP BY scope_label
        """
        page_sql = cte + f"SELECT * FROM filtered ORDER BY {order_by} LIMIT ? OFFSET ?"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(page_sql, (*params, limit, offset)).fetchall()
            facet_rows = conn.execute(facet_sql, params).fetchall()
        facets: dict[str, dict[str, int]] = {
            "review_status": {}, "term_type": {}, "mode": {}, "locked": {}, "scope": {},
        }
        for row in facet_rows:
            facets[str(row["facet"])][str(row["value"] or "")] = int(row["count"] or 0)
        total = sum(facets["review_status"].values())
        return {
            "items": [self._resource(row, inherited=bool(row["inherited"]), evidence_count=int(row["evidence_count"])) for row in rows],
            "total": total,
            "facets": facets,
        }

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

    def record_extraction_candidates(
        self,
        *,
        book_id: int,
        chapter_id: int,
        chapter_number: int,
        extractor: str,
        candidates: list[dict[str, Any]],
        skip_source_keys: set[str] | None = None,
    ) -> dict[str, int]:
        """Persist bounded extraction evidence without inflating retry counts."""
        if extractor not in {"deterministic-v2", "hybrid-v1"}:
            raise ValueError("invalid_extractor")
        skipped_keys = skip_source_keys or set()
        created = updated = skipped = 0
        actor = f"{extractor}-extractor"
        request_id = f"chapter:{chapter_id}"
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for candidate in candidates:
                source = " ".join(unicodedata.normalize("NFKC", str(candidate.get("source_term") or "")).split())
                source_key = normalize_source_key(source)
                if not source_key or source_key in skipped_keys:
                    skipped += 1
                    continue
                rows = self._source_rows(conn, book_id, source_key)
                if len(rows) > 1:
                    skipped += 1
                    continue
                current = rows[0] if rows else None
                if current is not None and current["archived_at"]:
                    skipped += 1
                    continue
                if extractor == "hybrid-v1" and current is not None:
                    if current["review_status"] in {"APPROVED", "LOCKED", "REJECTED"}:
                        skipped += 1
                        continue
                    prior_evidence = conn.execute(
                        "SELECT 1 FROM glossary_term_evidence "
                        "WHERE term_id = ? AND chapter_id = ? LIMIT 1",
                        (current["id"], chapter_id),
                    ).fetchone()
                    if prior_evidence is not None:
                        skipped += 1
                        continue

                mention_count = max(0, int(candidate.get("mention_count") or 0))
                target = str(candidate.get("target_term") or "").strip()
                term_type = str(candidate.get("term_type") or "other").strip().lower() or "other"
                evidence = {
                    "evidence_types": sorted(
                        {str(value) for value in candidate.get("evidence_types") or [] if str(value)}
                    ),
                    "mention_count": mention_count,
                    "source_fingerprint": hashlib.sha256(
                        f"{book_id}:{chapter_id}:{source_key}".encode("utf-8")
                    ).hexdigest(),
                    "title_match": bool(candidate.get("title_match")),
                }
                evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

                is_new = current is None
                if is_new:
                    conn.execute(
                        """
                        INSERT INTO glossary_terms
                            (book_id, source_term, source_key, target_term, category, confidence,
                             approved, mode, occurrence_count, chapter_count, locked, term_type,
                             first_seen_chapter_id, first_seen_chapter_number, review_status,
                             source_context, last_seen, updated_at, version, archived_at)
                        VALUES (?, ?, ?, ?, ?, ?, 0, 'translate', ?, 1, 0, ?, ?, ?,
                                'NEEDS_REVIEW', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, '')
                        """,
                        (
                            book_id,
                            source,
                            source_key,
                            target,
                            term_type,
                            float(candidate.get("confidence") or 0.5),
                            mention_count,
                            term_type,
                            chapter_id,
                            chapter_number,
                            str(candidate.get("source_context") or "")[:200],
                        ),
                    )
                    term_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                    current = self._row(conn, term_id)
                    created += 1
                else:
                    term_id = int(current["id"])

                evidence_row = conn.execute(
                    "SELECT id, evidence_json FROM glossary_term_evidence "
                    "WHERE term_id = ? AND chapter_id = ? AND extractor = ?",
                    (term_id, chapter_id, extractor),
                ).fetchone()
                evidence_changed = evidence_row is None or evidence_row["evidence_json"] != evidence_json
                if evidence_row is None:
                    conn.execute(
                        """
                        INSERT INTO glossary_term_evidence
                            (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
                        VALUES (?, ?, ?, ?, 'chapter_observation', ?)
                        """,
                        (term_id, book_id, chapter_id, extractor, evidence_json),
                    )
                elif evidence_changed:
                    conn.execute(
                        "UPDATE glossary_term_evidence SET evidence_json = ?, evidence_type = 'chapter_observation' "
                        "WHERE id = ?",
                        (evidence_json, evidence_row["id"]),
                    )

                evidence_rows = conn.execute(
                    "SELECT chapter_id, evidence_json FROM glossary_term_evidence "
                    "WHERE term_id = ? AND extractor IN ('deterministic-v2', 'hybrid-v1')",
                    (term_id,),
                ).fetchall()
                occurrence_count = 0
                chapter_ids: set[int] = set()
                for row in evidence_rows:
                    try:
                        payload = json.loads(str(row["evidence_json"] or "{}"))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        payload = {}
                    value = payload.get("mention_count") if isinstance(payload, dict) else 0
                    if type(value) is int and value >= 0:
                        occurrence_count += value
                    chapter_ids.add(int(row["chapter_id"] or 0))

                before = dict(current)
                status = str(current["review_status"])
                target_conflict = (
                    extractor == "hybrid-v1"
                    and status in {"NEEDS_REVIEW", "CONFLICT"}
                    and bool(str(current["target_term"] or "").strip())
                    and bool(target)
                    and str(current["target_term"]).strip() != target
                )
                row_changed = (
                    int(current["occurrence_count"] or 0) != occurrence_count
                    or int(current["chapter_count"] or 0) != len(chapter_ids)
                    or (target_conflict and status != "CONFLICT")
                )
                if is_new:
                    after = dict(self._row(conn, term_id))
                    self._log(conn, "add", {}, after, actor, request_id)
                elif row_changed:
                    conn.execute(
                        """
                        UPDATE glossary_terms
                        SET occurrence_count = ?, chapter_count = ?,
                            review_status = CASE WHEN ? THEN 'CONFLICT' ELSE review_status END,
                            approved = CASE WHEN ? THEN 0 ELSE approved END,
                            locked = CASE WHEN ? THEN 0 ELSE locked END,
                            updated_at = CURRENT_TIMESTAMP, version = version + 1
                        WHERE id = ?
                        """,
                        (
                            occurrence_count,
                            len(chapter_ids),
                            int(target_conflict),
                            int(target_conflict),
                            int(target_conflict),
                            term_id,
                        ),
                    )
                    after = dict(self._row(conn, term_id))
                    self._log(conn, "observe", before, after, actor, request_id)
                if not is_new and evidence_changed:
                    updated += 1
                elif not is_new and not evidence_changed:
                    skipped += 1
            conn.commit()
        return {"created": created, "updated": updated, "skipped": skipped}

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
        expected_version = updates.pop("expected_version", None)
        changes = {key: value for key, value in updates.items() if value is not None}
        with get_connection(self.db_path) as conn:
            if expected_version is not None:
                conn.execute("BEGIN IMMEDIATE")
            current = self._row(conn, term_id)
            if current is None or current["archived_at"]:
                return False
            if expected_version is not None and int(current["version"] or 0) != int(expected_version):
                raise GlossaryStateConflict("stale_version")
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

    def bulk(
        self,
        action: str,
        terms: list[dict[str, int]],
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict[str, Any]:
        if action not in {"approve", "reject", "lock", "archive"}:
            raise GlossaryStateConflict("invalid_action")
        if not 1 <= len(terms) <= 200:
            raise GlossaryStateConflict("bulk_limit_exceeded")
        ids = [int(term["id"]) for term in terms]
        if len(ids) != len(set(ids)):
            raise GlossaryStateConflict("duplicate_term")
        expected = {int(term["id"]): int(term["expected_version"]) for term in terms}
        state_by_action = {
            "approve": ("APPROVED", 1, 0),
            "reject": ("REJECTED", -1, 0),
            "lock": ("LOCKED", 1, 1),
        }

        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows: list[sqlite3.Row] = []
            for term_id in ids:
                row = self._row(conn, term_id)
                if row is None or row["archived_at"]:
                    raise GlossaryStateConflict("term_not_found")
                if int(row["version"] or 0) != expected[term_id]:
                    raise GlossaryStateConflict("stale_version")
                if action in {"approve", "lock"} and row["review_status"] == "CONFLICT":
                    raise GlossaryStateConflict("unresolved_conflict")
                if action != "archive" and not self._validate_transition(
                    conn, row, action, row
                ):
                    raise GlossaryStateConflict("invalid_transition")
                rows.append(row)

            for row in rows:
                before = dict(row)
                if action == "archive":
                    conn.execute(
                        """
                        UPDATE glossary_terms
                        SET archived_at = ?, updated_at = CURRENT_TIMESTAMP, version = version + 1
                        WHERE id = ?
                        """,
                        (datetime.now(timezone.utc).isoformat(), row["id"]),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE glossary_terms
                        SET review_status = ?, approved = ?, locked = ?,
                            updated_at = CURRENT_TIMESTAMP, version = version + 1
                        WHERE id = ?
                        """,
                        (*state_by_action[action], row["id"]),
                    )
                after = dict(self._row(conn, int(row["id"])))
                self._log(conn, action, before, after, self._actor(actor), request_id)
            resources = [self._resource(self._row(conn, term_id)) for term_id in ids]
            conn.commit()
        return {"action": action, "updated": len(resources), "items": resources}

    def query_conflicts(
        self,
        *,
        book_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        where = ["COALESCE(archived_at, '') = ''", "review_status != 'REJECTED'", "source_key != ''"]
        params: list[Any] = []
        if book_id is not None:
            where.append("book_id IN (0, ?)")
            params.append(book_id)
        offset = (page - 1) * per_page
        ctes = f"""
            WITH eligible AS (
                SELECT id, book_id, source_key, variants
                FROM glossary_terms
                WHERE {' AND '.join(where)}
            ),
            normalized AS (
                SELECT 'normalized_duplicate' AS conflict_type,
                       book_id AS group_book_id,
                       source_key,
                       MIN(id) AS canonical_id,
                       NULL AS secondary_id,
                       COUNT(*) AS member_total
                FROM eligible
                GROUP BY book_id, source_key
                HAVING COUNT(*) > 1
            ),
            global_book AS (
                SELECT 'global_book' AS conflict_type,
                       -1 AS group_book_id,
                       source_key,
                       MIN(id) AS canonical_id,
                       NULL AS secondary_id,
                       COUNT(*) AS member_total
                FROM eligible
                GROUP BY source_key
                HAVING MIN(book_id) = 0 AND MAX(book_id) > 0
            ),
            primary_variant AS (
                SELECT 'primary_variant' AS conflict_type,
                       -2 AS group_book_id,
                       printf('%d:%d', a.id, b.id) AS source_key,
                       a.id AS canonical_id,
                       b.id AS secondary_id,
                       2 AS member_total
                FROM eligible a
                JOIN eligible b ON a.id < b.id
                WHERE glossary_variant_has(a.variants, b.source_key) = 1
                   OR glossary_variant_has(b.variants, a.source_key) = 1
            ),
            candidates AS (
                SELECT * FROM normalized
                UNION ALL SELECT * FROM global_book
                UNION ALL SELECT * FROM primary_variant
            )
        """
        with get_connection(self.db_path) as conn:
            conn.create_function(
                "glossary_variant_has",
                2,
                lambda variants, source_key: int(str(source_key or "") in _variant_keys(variants)),
                deterministic=True,
            )
            total = int(conn.execute(f"{ctes} SELECT COUNT(*) FROM candidates", params).fetchone()[0])
            groups = conn.execute(
                f"""
                {ctes}
                SELECT conflict_type, group_book_id, source_key, canonical_id,
                       secondary_id, member_total
                FROM candidates
                ORDER BY conflict_type, group_book_id, source_key, canonical_id,
                         COALESCE(secondary_id, 0)
                LIMIT ? OFFSET ?
                """,
                (*params, per_page, offset),
            ).fetchall()
            members_by_group: dict[int, list[dict[str, Any]]] = {
                index: [] for index in range(len(groups))
            }
            if groups:
                member_selects: list[str] = []
                member_params: list[Any] = []
                active = [
                    "COALESCE(archived_at, '') = ''",
                    "review_status != 'REJECTED'",
                    "source_key != ''",
                ]
                for index, group in enumerate(groups):
                    conditions = list(active)
                    conflict_type = str(group["conflict_type"])
                    if conflict_type == "normalized_duplicate":
                        conditions.extend(("book_id = ?", "source_key = ?"))
                        member_params.extend((group["group_book_id"], group["source_key"]))
                    elif conflict_type == "global_book":
                        conditions.append("source_key = ?")
                        member_params.append(group["source_key"])
                        if book_id is not None:
                            conditions.append("book_id IN (0, ?)")
                            member_params.append(book_id)
                    else:
                        conditions.append("id IN (?, ?)")
                        member_params.extend((group["canonical_id"], group["secondary_id"]))
                    member_selects.append(
                        f"""
                        SELECT {index} AS group_index, id
                        FROM (
                            SELECT id
                            FROM glossary_terms
                            WHERE {' AND '.join(conditions)}
                            ORDER BY id
                            LIMIT 200
                        )
                        """
                    )
                rows = conn.execute(
                    f"""
                    WITH selected_members AS (
                        {' UNION ALL '.join(member_selects)}
                    )
                    SELECT m.group_index, g.*, COUNT(e.id) AS evidence_count
                    FROM selected_members m
                    JOIN glossary_terms g ON g.id = m.id
                    LEFT JOIN glossary_term_evidence e ON e.term_id = g.id
                    GROUP BY m.group_index, g.id
                    ORDER BY m.group_index, g.id
                    """,
                    member_params,
                ).fetchall()
                for row in rows:
                    members_by_group[int(row["group_index"])].append(
                        self._resource(
                            row, evidence_count=int(row["evidence_count"] or 0)
                        )
                    )
        items = []
        for index, group in enumerate(groups):
            members = members_by_group[index]
            member_total = int(group["member_total"])
            conflict_type = str(group["conflict_type"])
            identity = {
                "type": conflict_type,
                "book_id": int(group["group_book_id"]),
                "source_key": str(group["source_key"]),
            }
            items.append(
                {
                    "id": _stable_digest(identity)[:16],
                    "types": [conflict_type],
                    "canonical_id": int(group["canonical_id"]),
                    "member_total": member_total,
                    "members_truncated": member_total > len(members),
                    "members": members,
                }
            )
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }

    def query_legacy_conflicts(
        self,
        *,
        book_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
        member_limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return the legacy conflict shape with bounded groups and members."""
        where = ["approved >= 0", "COALESCE(archived_at, '') = ''"]
        params: list[Any] = []
        if book_id is not None:
            where.append("book_id IN (0, ?)")
            params.append(book_id)
        where_sql = " AND ".join(where)
        typed_terms = (
            "'character','sect','realm','skill','artifact','location','title',"
            "'cultivation','organization','place'"
        )
        with get_connection(self.db_path) as conn:
            candidates = conn.execute(
                f"""
                WITH source_conflicts AS (
                    SELECT 'source_conflict' AS conflict_type, source_term AS conflict_key,
                           COUNT(DISTINCT target_term) AS conflict_count
                    FROM glossary_terms
                    WHERE {where_sql}
                    GROUP BY source_term
                    HAVING COUNT(DISTINCT target_term) > 1
                ),
                target_reuse AS (
                    SELECT 'target_reuse' AS conflict_type, target_term AS conflict_key,
                           COUNT(DISTINCT source_term) AS conflict_count
                    FROM glossary_terms
                    WHERE {where_sql} AND target_term != ''
                      AND LOWER(COALESCE(term_type, category, '')) IN ({typed_terms})
                    GROUP BY target_term
                    HAVING COUNT(DISTINCT source_term) > 1
                )
                SELECT * FROM source_conflicts
                UNION ALL SELECT * FROM target_reuse
                ORDER BY conflict_count DESC, conflict_type, conflict_key
                LIMIT ? OFFSET ?
                """,
                (*params, *params, limit, offset),
            ).fetchall()
            source_keys = [row["conflict_key"] for row in candidates if row["conflict_type"] == "source_conflict"]
            target_keys = [row["conflict_key"] for row in candidates if row["conflict_type"] == "target_reuse"]
            source_details: dict[str, list[dict[str, Any]]] = {}
            source_member_totals: dict[str, int] = {}
            if source_keys:
                placeholders = ",".join("?" for _ in source_keys)
                rows = conn.execute(
                    f"""
                    WITH ranked AS (
                        SELECT source_term, book_id, target_term, approved, mode,
                               COUNT(*) OVER (PARTITION BY source_term) AS member_total,
                               ROW_NUMBER() OVER (PARTITION BY source_term ORDER BY book_id, id) AS member_number
                        FROM glossary_terms
                        WHERE source_term IN ({placeholders}) AND {where_sql}
                    )
                    SELECT * FROM ranked WHERE member_number <= ?
                    ORDER BY source_term, member_number
                    """,
                    (*source_keys, *params, member_limit),
                ).fetchall()
                for row in rows:
                    key = str(row["source_term"])
                    source_member_totals[key] = int(row["member_total"])
                    source_details.setdefault(key, []).append(
                        {
                            "book_id": row["book_id"],
                            "target_term": row["target_term"],
                            "approved": row["approved"],
                            "mode": row["mode"],
                        }
                    )
            target_details: dict[str, list[dict[str, Any]]] = {}
            target_member_totals: dict[str, int] = {}
            if target_keys:
                placeholders = ",".join("?" for _ in target_keys)
                rows = conn.execute(
                    f"""
                    WITH ranked AS (
                        SELECT target_term, book_id, source_term, approved, mode, term_type, locked,
                               COUNT(*) OVER (PARTITION BY target_term) AS member_total,
                               ROW_NUMBER() OVER (
                                   PARTITION BY target_term
                                   ORDER BY locked DESC, book_id DESC, source_term, id
                               ) AS member_number
                        FROM glossary_terms
                        WHERE target_term IN ({placeholders}) AND {where_sql}
                    )
                    SELECT * FROM ranked WHERE member_number <= ?
                    ORDER BY target_term, member_number
                    """,
                    (*target_keys, *params, member_limit),
                ).fetchall()
                for row in rows:
                    key = str(row["target_term"])
                    target_member_totals[key] = int(row["member_total"])
                    target_details.setdefault(key, []).append(
                        {
                            "book_id": row["book_id"],
                            "source_term": row["source_term"],
                            "approved": row["approved"],
                            "mode": row["mode"],
                            "term_type": row["term_type"],
                            "locked": row["locked"],
                        }
                    )
        conflicts: list[dict[str, Any]] = []
        for row in candidates:
            key = str(row["conflict_key"])
            if row["conflict_type"] == "source_conflict":
                member_total = source_member_totals.get(key, 0)
                conflicts.append(
                    {
                        "type": "source_conflict",
                        "source_term": key,
                        "targets": source_details.get(key, []),
                        "member_total": member_total,
                        "truncated": member_total > member_limit,
                    }
                )
            else:
                member_total = target_member_totals.get(key, 0)
                conflicts.append(
                    {
                        "type": "target_reuse",
                        "target_term": key,
                        "sources": target_details.get(key, []),
                        "member_total": member_total,
                        "truncated": member_total > member_limit,
                    }
                )
        return conflicts

    def _merge_preview(
        self,
        conn: sqlite3.Connection,
        canonical_id: int,
        duplicate_ids: list[int],
    ) -> dict[str, Any]:
        ids = [canonical_id, *duplicate_ids]
        if not duplicate_ids or len(ids) > 200 or len(ids) != len(set(ids)):
            raise GlossaryStateConflict("invalid_merge")
        rows = [self._row(conn, term_id) for term_id in ids]
        if any(row is None or row["archived_at"] for row in rows):
            raise GlossaryStateConflict("term_not_found")
        canonical = rows[0]
        assert canonical is not None
        canonical_variants = _variant_keys(canonical["variants"])
        for duplicate in rows[1:]:
            assert duplicate is not None
            related = (
                duplicate["source_key"] == canonical["source_key"]
                or duplicate["source_key"] in canonical_variants
                or canonical["source_key"] in _variant_keys(duplicate["variants"])
            )
            if not related:
                raise GlossaryStateConflict("merge_candidate_mismatch")
        versions = [{"id": int(row["id"]), "version": int(row["version"] or 0)} for row in rows if row]
        placeholders = ",".join("?" for _ in ids)
        evidence = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM glossary_term_evidence WHERE term_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]
        history = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM glossary_history WHERE term_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]
        evidence_count = len(evidence)
        history_count = len(history)
        occurrence_count = sum(int(row["occurrence_count"] or 0) for row in rows if row)
        digest = _stable_digest(
            {
                "canonical_id": canonical_id,
                "duplicate_ids": duplicate_ids,
                "versions": versions,
                "occurrence_count": occurrence_count,
                "evidence": evidence,
                "history": history,
            }
        )
        return {
            "canonical_id": canonical_id,
            "duplicate_ids": duplicate_ids,
            "versions": versions,
            "digest": digest,
            "evidence_count": evidence_count,
            "history_count": history_count,
            "occurrence_count": occurrence_count,
        }

    def preview_merge(self, canonical_id: int, duplicate_ids: list[int]) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            return self._merge_preview(conn, canonical_id, duplicate_ids)

    def apply_merge(
        self,
        canonical_id: int,
        duplicate_ids: list[int],
        digest: str,
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            preview = self._merge_preview(conn, canonical_id, duplicate_ids)
            if not hmac.compare_digest(str(digest), preview["digest"]):
                raise GlossaryStateConflict("preview_mismatch")
            canonical_before = dict(self._row(conn, canonical_id))
            placeholders = ",".join("?" for _ in duplicate_ids)
            conn.execute(
                f"""
                UPDATE glossary_term_evidence SET term_id = ?
                WHERE term_id IN ({placeholders})
                """,
                (canonical_id, *duplicate_ids),
            )
            conn.execute(
                f"UPDATE glossary_history SET term_id = ? WHERE term_id IN ({placeholders})",
                (canonical_id, *duplicate_ids),
            )
            conn.execute(
                """
                UPDATE glossary_terms
                SET occurrence_count = ?, updated_at = CURRENT_TIMESTAMP, version = version + 1
                WHERE id = ?
                """,
                (preview["occurrence_count"], canonical_id),
            )
            canonical_after = dict(self._row(conn, canonical_id))
            self._log(
                conn, "merge", canonical_before, canonical_after, self._actor(actor), request_id
            )
            archived_at = datetime.now(timezone.utc).isoformat()
            for duplicate_id in duplicate_ids:
                before = dict(self._row(conn, duplicate_id))
                conn.execute(
                    """
                    UPDATE glossary_terms
                    SET archived_at = ?, updated_at = CURRENT_TIMESTAMP, version = version + 1
                    WHERE id = ?
                    """,
                    (archived_at, duplicate_id),
                )
                after = dict(self._row(conn, duplicate_id))
                self._log(
                    conn, "merge_archive", before, after, self._actor(actor), request_id
                )
            conn.commit()
        return {**preview, "merged": len(duplicate_ids)}

    @staticmethod
    def _canonical_import_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        canonical: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for item_number, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                errors.append({"item": item_number, "field": "item", "code": "invalid_type"})
                continue
            source = str(raw.get("source_term") or "").strip()
            target = str(raw.get("target_term") or "").strip()
            if not source:
                errors.append({"item": item_number, "field": "source_term", "code": "required"})
            if "target_term" not in raw:
                errors.append({"item": item_number, "field": "target_term", "code": "required"})
            if not source or "target_term" not in raw:
                continue
            if len(source) > 500 or len(target) > 2000:
                errors.append({"item": item_number, "field": "item", "code": "too_long"})
                continue
            integer_values: dict[str, int | None] = {}
            invalid_number = False
            for field, default, nullable in (
                ("id", None, True),
                ("version", None, True),
                ("book_id", 0, False),
                ("approved", IMPORT_FIELDS["approved"], False),
                ("locked", IMPORT_FIELDS["locked"], False),
                ("priority", IMPORT_FIELDS["priority"], False),
                ("first_seen_chapter_id", IMPORT_FIELDS["first_seen_chapter_id"], False),
                ("first_seen_chapter_number", IMPORT_FIELDS["first_seen_chapter_number"], False),
                ("occurrence_count", None, True),
            ):
                value = raw.get(field, default)
                if nullable and value is None:
                    integer_values[field] = None
                    continue
                if isinstance(value, bool):
                    errors.append({"item": item_number, "field": field, "code": "invalid_type"})
                    invalid_number = True
                    break
                if type(value) is not int:
                    errors.append({"item": item_number, "field": field, "code": "invalid_number"})
                    invalid_number = True
                    break
                if not SQLITE_INTEGER_MIN <= value <= SQLITE_INTEGER_MAX:
                    errors.append({"item": item_number, "field": field, "code": "out_of_range"})
                    invalid_number = True
                    break
                integer_values[field] = value
            if invalid_number:
                continue
            confidence_value = raw.get("confidence", IMPORT_FIELDS["confidence"])
            if isinstance(confidence_value, bool) or type(confidence_value) not in {int, float}:
                errors.append({"item": item_number, "field": "item", "code": "invalid_number"})
                continue
            confidence = float(confidence_value)
            book_id = int(integer_values["book_id"] or 0)
            approved = int(integer_values["approved"] or 0)
            locked = int(integer_values["locked"] or 0)
            priority = int(integer_values["priority"] or 0)
            first_seen_chapter_id = int(integer_values["first_seen_chapter_id"] or 0)
            first_seen_chapter_number = int(integer_values["first_seen_chapter_number"] or 0)
            occurrence_count = integer_values["occurrence_count"]
            if (
                book_id < 0
                or approved not in {-1, 0, 1}
                or locked not in {0, 1}
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or first_seen_chapter_id < 0
                or first_seen_chapter_number < 0
                or (occurrence_count is not None and occurrence_count < 0)
            ):
                errors.append({"item": item_number, "field": "item", "code": "invalid_value"})
                continue
            mode = str(raw.get("mode", IMPORT_FIELDS["mode"]) or "")
            if mode not in {"", "translate", "context", "transliterate"}:
                errors.append({"item": item_number, "field": "mode", "code": "invalid_value"})
                continue
            review_status = str(raw.get("review_status") or "").strip().upper()
            if review_status and review_status not in CANONICAL_STATES:
                errors.append({"item": item_number, "field": "review_status", "code": "invalid_value"})
                continue
            if review_status:
                state = (review_status, approved, locked)
                if (approved, locked) != CANONICAL_STATES[review_status]:
                    errors.append({"item": item_number, "field": "item", "code": "invalid_state"})
                    continue
            else:
                states_by_flags = {
                    (0, 0): ("NEEDS_REVIEW", 0, 0),
                    (1, 0): ("APPROVED", 1, 0),
                    (-1, 0): ("REJECTED", -1, 0),
                    (1, 1): ("LOCKED", 1, 1),
                }
                state = states_by_flags.get((approved, locked))
                if state is None:
                    errors.append({"item": item_number, "field": "item", "code": "invalid_state"})
                    continue
            archived_value = raw.get("archived", bool(raw.get("archived_at")))
            if "archived" in raw and not isinstance(archived_value, bool):
                errors.append({"item": item_number, "field": "archived", "code": "invalid_type"})
                continue
            if not archived_value and state[0] in {"APPROVED", "LOCKED"} and _target_is_blank(target):
                errors.append({"item": item_number, "field": "target_term", "code": "target_required"})
                continue
            source_key = normalize_source_key(source)
            identity = (book_id, source_key)
            if identity in seen:
                errors.append({"item": item_number, "field": "source_term", "code": "duplicate_item"})
                continue
            seen.add(identity)
            item = {
                key: raw.get(key, default)
                for key, default in IMPORT_FIELDS.items()
            }
            item.update(
                item_number=item_number,
                book_id=book_id,
                source_term=source,
                source_key=source_key,
                target_term=target,
                approved=state[1],
                locked=state[2],
                review_status=state[0],
                mode=mode,
                priority=priority,
                confidence=confidence,
                first_seen_chapter_id=first_seen_chapter_id,
                first_seen_chapter_number=first_seen_chapter_number,
                occurrence_count=occurrence_count,
                archived_at=str(raw.get("archived_at") or "") if archived_value else "",
            )
            for key in (
                "category", "pinyin", "notes_vi", "variants", "genre", "term_type",
                "alternatives", "gender", "source_context",
            ):
                item[key] = str(item[key] or "")
            canonical.append(item)
        return canonical, errors

    def _import_preview(
        self,
        conn: sqlite3.Connection,
        items: list[dict[str, Any]],
        conflict_policy: str,
        legacy_partial: bool = False,
    ) -> dict[str, Any]:
        if conflict_policy not in IMPORT_POLICIES:
            raise GlossaryStateConflict("invalid_conflict_policy")
        if legacy_partial:
            materialized: list[dict[str, Any]] = []
            for raw in items:
                if not isinstance(raw, dict):
                    materialized.append(raw)
                    continue
                merged: dict[str, Any] = {
                    "approved": 0,
                    "locked": 0,
                    "review_status": "NEEDS_REVIEW",
                }
                book_value = raw.get("book_id", 0)
                source = str(raw.get("source_term") or "").strip()
                if type(book_value) is int and not isinstance(book_value, bool) and source:
                    existing = self._source_rows(
                        conn, book_value, normalize_source_key(source)
                    )
                    if len(existing) == 1:
                        merged.update(dict(existing[0]))
                        merged["archived"] = bool(existing[0]["archived_at"])
                merged.update(raw)
                materialized.append(merged)
            items = materialized
        canonical, errors = self._canonical_import_items(items)
        if errors:
            raise GlossaryValidationError(errors)
        actions: list[dict[str, Any]] = []
        affected: list[dict[str, Any]] = []
        summary = {"added": 0, "updated": 0, "skipped": 0}
        conflict_errors: list[dict[str, Any]] = []
        for item in canonical:
            rows = self._source_rows(conn, item["book_id"], item["source_key"])
            code = ""
            current = rows[0] if len(rows) == 1 else None
            if len(rows) > 1:
                code = "normalized_source_collision"
            elif current is not None:
                current_state = _canonical_state(
                    current["approved"], current["locked"], current["review_status"]
                )
                desired_state = (item["review_status"], item["approved"], item["locked"])
                if current["locked"] == 1 and (
                    desired_state != current_state
                    or item["target_term"] != current["target_term"]
                ):
                    code = "invalid_transition"
                elif not item["archived_at"] and desired_state[0] in {"APPROVED", "LOCKED"}:
                    other_targets = {
                        " ".join(unicodedata.normalize("NFKC", str(row["target_term"] or "")).split())
                        for row in rows
                        if int(row["id"]) != int(current["id"]) and not row["archived_at"]
                    }
                    other_targets.add(
                        " ".join(unicodedata.normalize("NFKC", item["target_term"]).split())
                    )
                    if len(other_targets) > 1:
                        code = "normalized_target_conflict"
            if code:
                if conflict_policy == "reject_conflicts":
                    conflict_errors.append(
                        {"item": item["item_number"], "field": "item", "code": code}
                    )
                else:
                    summary["skipped"] += 1
                    actions.append({"item": item["item_number"], "action": "skip", "code": code})
                continue
            if current is None:
                summary["added"] += 1
                affected.append(
                    {"book_id": item["book_id"], "source_key": item["source_key"], "version": None}
                )
                actions.append({"item": item["item_number"], "action": "add"})
            else:
                summary["updated"] += 1
                affected.append({"id": int(current["id"]), "version": int(current["version"] or 0)})
                actions.append(
                    {"item": item["item_number"], "action": "update", "id": int(current["id"])}
                )
        if conflict_errors:
            raise GlossaryValidationError(conflict_errors)
        digest = _stable_digest(
            {
                "schema_version": 1,
                "conflict_policy": conflict_policy,
                "items": canonical,
                "affected": affected,
                "actions": actions,
            }
        )
        return {
            "schema_version": 1,
            "digest": digest,
            "conflict_policy": conflict_policy,
            "summary": summary,
            "actions": actions,
            "affected": affected,
            "canonical_items": canonical,
        }

    def preview_import(
        self,
        items: list[dict[str, Any]],
        conflict_policy: str = "skip_conflicts",
        *,
        legacy_partial: bool = False,
    ) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            return self._import_preview(conn, items, conflict_policy, legacy_partial)

    def apply_import(
        self,
        items: list[dict[str, Any]],
        digest: str,
        conflict_policy: str = "skip_conflicts",
        *,
        actor: str = "",
        request_id: str = "",
        legacy_partial: bool = False,
    ) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            preview = self._import_preview(conn, items, conflict_policy, legacy_partial)
            if not hmac.compare_digest(str(digest), preview["digest"]):
                raise GlossaryStateConflict("import_drift")
            items_by_number = {
                int(item["item_number"]): item for item in preview["canonical_items"]
            }
            for action in preview["actions"]:
                if action["action"] == "skip":
                    continue
                item = items_by_number[int(action["item"])]
                if action["action"] == "add":
                    conn.execute(
                        """
                        INSERT INTO glossary_terms
                            (book_id, source_term, source_key, target_term, category, confidence,
                             approved, mode, pinyin, notes_vi, variants, occurrence_count, priority,
                             locked, genre, term_type, alternatives, gender, first_seen_chapter_id,
                             first_seen_chapter_number, review_status, source_context, archived_at,
                             last_seen, updated_at, version)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                        """,
                        (
                            item["book_id"], item["source_term"], item["source_key"], item["target_term"],
                            item["category"], float(item["confidence"] or 0), item["approved"], item["mode"],
                            item["pinyin"], item["notes_vi"], item["variants"],
                            int(item["occurrence_count"] or 0), item["priority"], item["locked"], item["genre"],
                            item["term_type"], item["alternatives"], item["gender"],
                            int(item["first_seen_chapter_id"] or 0), int(item["first_seen_chapter_number"] or 0),
                            item["review_status"], item["source_context"], item["archived_at"],
                        ),
                    )
                    term_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                    before: dict[str, Any] = {}
                else:
                    term_id = int(action["id"])
                    before = dict(self._row(conn, term_id))
                    occurrence_count = (
                        before["occurrence_count"]
                        if item["occurrence_count"] is None
                        else item["occurrence_count"]
                    )
                    conn.execute(
                        """
                        UPDATE glossary_terms
                        SET source_term = ?, source_key = ?, target_term = ?, category = ?, confidence = ?,
                            approved = ?, mode = ?, pinyin = ?, notes_vi = ?, variants = ?,
                            occurrence_count = ?, priority = ?, locked = ?, genre = ?, term_type = ?,
                            alternatives = ?, gender = ?, first_seen_chapter_id = ?,
                            first_seen_chapter_number = ?, review_status = ?, source_context = ?,
                            archived_at = ?, updated_at = CURRENT_TIMESTAMP, version = version + 1
                        WHERE id = ?
                        """,
                        (
                            item["source_term"], item["source_key"], item["target_term"], item["category"],
                            float(item["confidence"] or 0), item["approved"], item["mode"], item["pinyin"],
                            item["notes_vi"], item["variants"], occurrence_count, item["priority"], item["locked"],
                            item["genre"], item["term_type"], item["alternatives"], item["gender"],
                            int(item["first_seen_chapter_id"] or 0), int(item["first_seen_chapter_number"] or 0),
                            item["review_status"], item["source_context"], item["archived_at"], term_id,
                        ),
                    )
                after = dict(self._row(conn, term_id))
                self._log(
                    conn,
                    "import_add" if action["action"] == "add" else "import_update",
                    before,
                    after,
                    self._actor(actor),
                    request_id,
                )
            conn.commit()
        return {**preview["summary"], "errors": []}

    def export_terms(self, book_id: int | None = None, scope: str = "all") -> list[dict[str, Any]]:
        if scope not in {"all", "book", "global"}:
            raise ValueError("invalid_scope")
        if scope == "book" and book_id is None:
            raise ValueError("book_id_required")
        where = ""
        params: tuple[Any, ...] = ()
        if scope == "book":
            where, params = "WHERE book_id = ?", (book_id,)
        elif scope == "global":
            where = "WHERE book_id = 0"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(EXPORT_FIELDS)} FROM glossary_terms {where} ORDER BY id",
                params,
            ).fetchall()
        return [
            {**dict(row), "archived": bool(row["archived_at"])}
            for row in rows
        ]
