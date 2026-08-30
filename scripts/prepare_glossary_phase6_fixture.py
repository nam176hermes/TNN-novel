#!/usr/bin/env python3
"""Prepare a disposable 10k-row glossary fixture for Phase 6 certification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database.db import add_book, add_chapter, get_connection, init_db
from scripts.benchmark_glossary_baseline import _create_fixture


def prepare_fixture(data_dir: Path, rows: int = 10_000) -> dict[str, int]:
    """Create synthetic API/UI data without reading or modifying operator data."""
    if rows != 10_000:
        raise ValueError("rows_must_equal_10000")
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("data_dir_must_be_empty")
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "pipeline.db"

    # Initialize the empty database before the bulk fixture so migration behavior
    # is covered without paying an irrelevant row-by-row legacy backfill cost.
    init_db(db_path)
    _create_fixture(db_path, rows)
    book_id = add_book(db_path, "Synthetic Phase 6 operator journey")
    raw_path = data_dir / "raw" / "phase6-chapter.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("玄天圣典玄天圣典。青云宗青云宗。", encoding="utf-8")
    chapter_id = add_chapter(
        db_path,
        book_id,
        1,
        "第一章 青云宗",
        raw_text_path=raw_path,
    )

    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE glossary_terms SET source_key = source_term WHERE source_key = ''"
        )
        conn.execute(
            """
            UPDATE glossary_terms
            SET review_status = 'NEEDS_REVIEW', approved = 0, locked = 0
            WHERE id IN (1, 2)
            """
        )
        conn.execute(
            """
            UPDATE glossary_terms
            SET source_term = CASE id
                    WHEN 3 THEN 'Ｐｈａｓｅ６ Conflict'
                    ELSE 'phase6 conflict'
                END,
                source_key = 'phase6 conflict',
                target_term = CASE id WHEN 3 THEN 'Canonical' ELSE 'Duplicate' END,
                review_status = 'CONFLICT', approved = 0, locked = 0
            WHERE id IN (3, 4)
            """
        )
        conn.commit()

    return {"book_id": book_id, "chapter_id": chapter_id, "rows": rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--rows", default=10_000, type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = prepare_fixture(args.data_dir, args.rows)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
