#!/usr/bin/env python3
"""Characterize current glossary behavior using an isolated synthetic fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import tempfile

from app.database.db import glossary_coverage, list_glossary, select_prompt_glossary_terms
from app.database.schema import SCHEMA


_PAGE_SIZE = 50


def _create_fixture(db_path: Path, rows: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, target_term, approved, locked, review_status, mode, created_at)
            VALUES (1, ?, ?, 1, 0, 'APPROVED', 'translate', ?)
            """,
            [
                (
                    f"synthetic-source-{index:05d}",
                    f"synthetic-target-{index:05d}",
                    f"{index:08d}",
                )
                for index in range(rows)
            ],
        )
        conn.commit()
    finally:
        conn.close()


def characterize(rows: int, work_dir: Path) -> dict[str, object]:
    """Exercise list, SQL query, prompt selection, and QA on synthetic rows."""
    if rows < 2:
        raise ValueError("rows must be at least 2")
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="glossary-phase0-", dir=work_dir) as temporary:
        db_path = Path(temporary) / "fixture.db"
        _create_fixture(db_path, rows)

        listed = list_glossary(db_path, book_id=1)
        with sqlite3.connect(db_path) as conn:
            first_page = conn.execute(
                "SELECT id FROM glossary_terms WHERE book_id = 1 ORDER BY id LIMIT ?",
                (_PAGE_SIZE,),
            ).fetchall()
            final_row = conn.execute(
                """
                SELECT 1 FROM glossary_terms
                WHERE book_id = 1
                ORDER BY id
                LIMIT 1 OFFSET ?
                """,
                (rows - 1,),
            ).fetchone()

        sample = "synthetic-source-00000 " + f"synthetic-source-{rows - 1:05d}"
        prompt_rows = select_prompt_glossary_terms(db_path, 1, sample)
        qa_result = glossary_coverage(db_path, 1, sample)

    return {
        "fixture": {"rows": rows, "synthetic": True},
        "characterization": {
            "list": {"first_page_rows": len(listed[:_PAGE_SIZE]), "returned_rows": len(listed)},
            "query": {"first_page_rows": len(first_page), "last_row_found": final_row is not None},
            "prompt": {"selected_rows": len(prompt_rows)},
            "qa": {"matched_rows": int(qa_result["matched_count"])},
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--work-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = characterize(args.rows, args.work_dir)
    except (OSError, sqlite3.Error, ValueError):
        print(json.dumps({"error": "characterization_failed"}), file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
