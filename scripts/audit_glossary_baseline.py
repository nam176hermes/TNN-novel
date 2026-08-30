#!/usr/bin/env python3
"""Read-only baseline audit for legacy glossary data.

The report intentionally contains only aggregate counts.  It is safe to save
alongside migration planning evidence because it never includes glossary terms,
targets, contexts, or the inspected database path.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sqlite3
import unicodedata


_VALID_STATE_TUPLES = {
    ("NEEDS_REVIEW", 0, 0),
    ("CONFLICT", 0, 0),
    ("APPROVED", 1, 0),
    ("LOCKED", 1, 1),
    ("REJECTED", -1, 0),
}


def _normalized_value(value: object) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    return "".join(
        character.lower() if "LATIN" in unicodedata.name(character, "") else character
        for character in normalized
    )


def _stored_integer(value: object) -> int | None:
    """Accept only SQLite integer values; never coerce malformed stored data."""
    return value if type(value) is int else None


def _stored_book_scope(value: object) -> int | None:
    """Return a valid non-negative stored scope without merging malformed values."""
    scope = _stored_integer(value)
    return scope if scope is not None and scope >= 0 else None


def _open_query_only(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _history_coverage(conn: sqlite3.Connection, total_terms: int) -> dict[str, int]:
    history_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(glossary_history)").fetchall()
    }
    if not {"book_id", "source_term"} <= history_columns:
        return {"terms_with_history": 0, "terms_without_history": total_terms}
    covered = conn.execute(
        """
        SELECT COUNT(*)
        FROM glossary_terms AS term
        WHERE EXISTS (
            SELECT 1
            FROM glossary_history AS history
            WHERE history.book_id = term.book_id
              AND history.source_term = term.source_term
        )
        """
    ).fetchone()[0]
    return {"terms_with_history": int(covered), "terms_without_history": total_terms - int(covered)}


def audit_glossary(db_path: Path) -> dict[str, object]:
    """Return aggregate migration-readiness counts without changing *db_path*."""
    with _open_query_only(db_path) as conn:
        rows = conn.execute(
            """
            SELECT book_id, source_term, target_term, approved, locked, review_status, mode
            FROM glossary_terms
            """
        ).fetchall()

        same_book: dict[tuple[int, str], list[str]] = defaultdict(list)
        global_rows: dict[str, list[str]] = defaultdict(list)
        book_rows: dict[tuple[int, str], list[str]] = defaultdict(list)
        state_mismatches = 0
        active_blank_targets = 0
        legacy_blank_modes = 0

        for book_id, source, target, approved, locked, review_status, mode in rows:
            approved_value = _stored_integer(approved)
            locked_value = _stored_integer(locked)
            numeric_state = (review_status, approved_value, locked_value)
            if numeric_state not in _VALID_STATE_TUPLES:
                state_mismatches += 1
            if approved_value == 1 and not _normalized_value(target):
                active_blank_targets += 1
            if not _normalized_value(mode):
                legacy_blank_modes += 1

            source_key = _normalized_value(source)
            if not source_key:
                continue
            target_key = _normalized_value(target)
            book_scope = _stored_book_scope(book_id)
            if book_scope is None:
                continue
            same_book[(book_scope, source_key)].append(target_key)
            if book_scope == 0:
                global_rows[source_key].append(target_key)
            else:
                book_rows[(book_scope, source_key)].append(target_key)

        collision_groups = [members for members in same_book.values() if len(members) > 1]
        conflict_groups: list[list[str]] = []
        for (book_id, source_key), scoped_rows in book_rows.items():
            inherited_rows = global_rows.get(source_key, [])
            if inherited_rows and set(inherited_rows) != set(scoped_rows):
                conflict_groups.append(inherited_rows + scoped_rows)

        counts = {
            "active_blank_targets": active_blank_targets,
            "global_book_conflicts": {
                "groups": len(conflict_groups),
                "rows": sum(len(members) for members in conflict_groups),
            },
            "history_coverage": _history_coverage(conn, len(rows)),
            "legacy_blank_modes": legacy_blank_modes,
            "normalized_same_book_collisions": {
                "groups": len(collision_groups),
                "rows": sum(len(members) for members in collision_groups),
            },
            "state_mismatches": state_mismatches,
        }
    return {"counts": counts}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="SQLite database to inspect read-only")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = audit_glossary(args.db)
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        print(json.dumps({"error": "audit_failed"}), file=__import__("sys").stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
