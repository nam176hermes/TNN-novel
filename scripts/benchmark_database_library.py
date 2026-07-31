#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import db
from app.mobile_api.services.pipeline_service import PipelineService


def _stats(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "min_ms": min(values),
        "median_ms": statistics.median(values),
        "max_ms": max(values),
    }


def _measure(call, samples: int) -> tuple[list[float], object]:
    values: list[float] = []
    result: object = None
    for _ in range(samples):
        started = time.perf_counter()
        result = call()
        values.append((time.perf_counter() - started) * 1000)
    return values, result


def _create_fixture(root: Path, book_count: int) -> tuple[Path, Path]:
    data_dir = root / f"books-{book_count}"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "pipeline.db"
    db.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        for book_index in range(book_count):
            book_id = conn.execute(
                """
                INSERT INTO books (
                    title, book_key, author, source, source_url, created_at
                ) VALUES (?, ?, 'Audit', 'synthetic', '', ?)
                """,
                (
                    f"Synthetic Book {book_index:03}",
                    f"synthetic-book-{book_index:03}",
                    f"2026-01-{(book_index % 28) + 1:02} 00:00:00",
                ),
            ).lastrowid
            for chapter_number in range(1, 11):
                translated_path = (
                    f"/synthetic/{book_id}/{chapter_number}.txt"
                    if chapter_number <= 7
                    else None
                )
                audio_path = (
                    f"/synthetic/{book_id}/{chapter_number}.mp3"
                    if chapter_number <= 2
                    else None
                )
                status = (
                    "audio_done"
                    if audio_path
                    else "translated"
                    if translated_path
                    else "qa_low"
                    if chapter_number == 8
                    else "imported"
                )
                conn.execute(
                    """
                    INSERT INTO chapters (
                        book_id, chapter_number, title, raw_text_path,
                        translated_text_path, audio_path, status,
                        translated_at, audio_created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        chapter_number,
                        f"Chapter {chapter_number}",
                        f"/synthetic/{book_id}/{chapter_number}-raw.txt",
                        translated_path,
                        audio_path,
                        status,
                        f"2026-02-{chapter_number:02} 00:00:00" if translated_path else None,
                        f"2026-03-{chapter_number:02} 00:00:00" if audio_path else None,
                    ),
                )
        conn.commit()
    return db_path, data_dir


def _trace_call(db_path: Path, call) -> tuple[object, int, list[str]]:
    original_connect = db.sqlite3.connect
    connection_count = 0
    statements: list[str] = []

    def counted_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(lambda statement: statements.append(statement.strip()))
        return conn

    with patch.object(db.sqlite3, "connect", side_effect=counted_connect):
        result = call()
    queries = [
        statement
        for statement in statements
        if statement.upper().startswith(("SELECT", "WITH"))
    ]
    return result, connection_count, queries


def _query_plan(db_path: Path, query: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
    return [str(row[3]) for row in rows]


def run_benchmark(work_dir: Path, samples: int, book_counts: list[int]) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    connection_db = work_dir / "connection.db"
    init_values, _ = _measure(lambda: db.init_db(connection_db), 3)

    raw_values: list[float] = []
    project_values: list[float] = []
    for _ in range(max(samples, 10)):
        started = time.perf_counter()
        raw_conn = sqlite3.connect(connection_db)
        raw_values.append((time.perf_counter() - started) * 1000)
        raw_conn.close()

        started = time.perf_counter()
        project_conn = db.get_connection(connection_db)
        project_values.append((time.perf_counter() - started) * 1000)
        project_conn.close()

    result = {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "workspace": str(PROJECT_ROOT),
        "fixture_root": str(work_dir),
        "startup_initialization": _stats(init_values),
        "raw_connection": _stats(raw_values),
        "project_connection": _stats(project_values),
        "library": {},
    }

    for book_count in book_counts:
        db_path, data_dir = _create_fixture(work_dir, book_count)
        service = object.__new__(PipelineService)
        service.db_path = db_path
        service.data_dir = data_dir

        book_values, books = _measure(service.list_books, samples)
        summary_values, summaries = _measure(service.list_translated_book_summaries, samples)
        _, book_connections, book_queries = _trace_call(db_path, service.list_books)
        traced_summaries, summary_connections, summary_queries = _trace_call(
            db_path,
            service.list_translated_book_summaries,
        )
        result["library"][str(book_count)] = {
            "book_list": {
                **_stats(book_values),
                "response_books": len(books),
                "connection_count": book_connections,
                "query_count": len(book_queries),
                "payload_bytes": len(json.dumps(books, ensure_ascii=False).encode("utf-8")),
                "query_plan": _query_plan(db_path, book_queries[0]),
            },
            "translated_library": {
                **_stats(summary_values),
                "response_books": len(summaries),
                "connection_count": summary_connections,
                "query_count": len(summary_queries),
                "payload_bytes": len(
                    json.dumps(traced_summaries, ensure_ascii=False).encode("utf-8")
                ),
                "query_plan": _query_plan(db_path, summary_queries[0]),
            },
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark isolated Novel-TNN database/library paths")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--work-dir", type=Path, help="Directory for synthetic databases")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--book-counts", type=int, nargs="+", default=[1, 10, 59, 100])
    args = parser.parse_args()

    if args.samples < 1 or any(count < 1 for count in args.book_counts):
        parser.error("samples and book counts must be positive")

    if args.work_dir:
        result = run_benchmark(args.work_dir.resolve(), args.samples, args.book_counts)
    else:
        with tempfile.TemporaryDirectory(prefix="novel-tnn-p2a-") as temp_dir:
            result = run_benchmark(Path(temp_dir), args.samples, args.book_counts)

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
