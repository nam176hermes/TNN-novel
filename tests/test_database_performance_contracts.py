from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import app.database.db as db_mod
from app.mobile_api.services.pipeline_service import PipelineService


def test_request_connection_skips_startup_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)

    def fail_if_called(_conn: sqlite3.Connection) -> None:
        raise AssertionError("normal connections must not run startup migrations")

    monkeypatch.setattr(db_mod, "_migrate_legacy_schema", fail_if_called)

    with db_mod.get_connection(db_path) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_db_runs_migrations_once_per_explicit_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    original = db_mod._migrate_legacy_schema
    calls = 0

    def count_migration(conn: sqlite3.Connection) -> None:
        nonlocal calls
        calls += 1
        original(conn)

    monkeypatch.setattr(db_mod, "_migrate_legacy_schema", count_migration)

    db_mod.init_db(db_path)

    assert calls == 1
    with sqlite3.connect(db_path) as conn:
        versions = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
            (db_mod.CURRENT_SCHEMA_VERSION,),
        ).fetchone()[0]
    assert versions == 1


def test_library_summary_uses_one_connection_and_one_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    covers_dir = tmp_path / "covers"
    covers_dir.mkdir()
    cover_path = covers_dir / "book-a.jpg"
    cover_path.write_bytes(b"cover")

    with sqlite3.connect(db_path) as conn:
        book_a = conn.execute(
            """
            INSERT INTO books (title, book_key, author, source, source_url, cover_path, created_at)
            VALUES ('Book A', 'book-a', 'Author A', 'manual', 'https://example.test/a', ?, '2026-01-01')
            """,
            (str(cover_path),),
        ).lastrowid
        book_b = conn.execute(
            """
            INSERT INTO books (title, book_key, author, source, created_at)
            VALUES ('Book B', 'book-b', 'Author B', 'ebook', '2026-01-02')
            """
        ).lastrowid
        raw_only = conn.execute(
            "INSERT INTO books (title, book_key, created_at) VALUES ('Raw Only', 'raw-only', '2026-01-03')"
        ).lastrowid
        conn.execute(
            "INSERT INTO books (title, book_key, created_at) VALUES ('Empty', 'empty', '2026-01-04')"
        )

        first_a = conn.execute(
            """
            INSERT INTO chapters (
                book_id, chapter_number, title, raw_text_path, translated_text_path,
                status, translated_at
            ) VALUES (?, 1, 'A1', '/private/a1-raw.txt', '/private/a1-vi.txt', 'translated', '2026-02-01')
            """,
            (book_a,),
        ).lastrowid
        latest_a = conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, raw_text_path, status)
            VALUES (?, 2, 'A2', '/private/a2-raw.txt', 'qa_low')
            """,
            (book_a,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, raw_text_path, status)
            VALUES (?, 3, 'A3', '/private/a3-raw.txt', 'failed')
            """,
            (book_a,),
        )
        conn.execute(
            """
            INSERT INTO chapters (
                book_id, chapter_number, title, translated_text_path, status, deleted_at
            ) VALUES (?, 4, 'A4 deleted', '/private/a4-vi.txt', 'translated', '2026-03-01')
            """,
            (book_a,),
        )
        only_b = conn.execute(
            """
            INSERT INTO chapters (
                book_id, chapter_number, title, content_html_path, audio_path,
                status, translated_at, audio_created_at
            ) VALUES (?, 1, 'B1', '/book-assets/b1.html', '/private/b1.mp3',
                      'audio_done', '2026-04-01', '2026-04-02')
            """,
            (book_b,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, raw_text_path, status)
            VALUES (?, 1, 'Raw chapter', '/private/raw.txt', 'imported')
            """,
            (raw_only,),
        )
        conn.commit()

    service = object.__new__(PipelineService)
    service.db_path = db_path
    service.data_dir = tmp_path
    original_connect = db_mod.sqlite3.connect
    connection_count = 0
    statements: list[str] = []

    def counted_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(lambda statement: statements.append(statement.strip()))
        return conn

    monkeypatch.setattr(db_mod.sqlite3, "connect", counted_connect)

    summaries = service.list_translated_book_summaries()

    assert connection_count == 1
    assert len(
        [statement for statement in statements if statement.upper().startswith(("SELECT", "WITH"))]
    ) == 1
    assert [summary["title"] for summary in summaries] == ["Book B", "Book A"]
    assert summaries[0]["total_chapters"] == 1
    assert summaries[0]["translated_chapters"] == 1
    assert summaries[0]["audio_chapters"] == 1
    assert summaries[0]["first_translated_chapter_id"] == only_b
    assert summaries[0]["latest_translated_chapter_id"] == only_b

    summary_a = summaries[1]
    assert summary_a["total_chapters"] == 3
    assert summary_a["translated_chapters"] == 2
    assert summary_a["audio_chapters"] == 0
    assert summary_a["failed_chapters"] == 1
    assert summary_a["qa_low_chapters"] == 1
    assert summary_a["first_translated_chapter_id"] == first_a
    assert summary_a["latest_translated_chapter_id"] == latest_a
    assert summary_a["latest_chapter_number"] == 2
    assert summary_a["latest_chapter_title"] == "A2"
    assert summary_a["cover_url"] == "/covers/book-a.jpg"
    assert {summary["title"] for summary in summaries}.isdisjoint({"Raw Only", "Empty"})


def test_book_list_uses_one_connection_and_one_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        active_book = conn.execute(
            "INSERT INTO books (title, book_key) VALUES ('Active', 'active')"
        ).lastrowid
        deleted_only_book = conn.execute(
            "INSERT INTO books (title, book_key) VALUES ('Deleted Only', 'deleted-only')"
        ).lastrowid
        conn.execute("INSERT INTO books (title, book_key) VALUES ('Empty', 'empty')")
        conn.execute(
            "INSERT INTO chapters (book_id, chapter_number, title) VALUES (?, 1, 'Active chapter')",
            (active_book,),
        )
        conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, deleted_at)
            VALUES (?, 1, 'Deleted chapter', '2026-01-01')
            """,
            (deleted_only_book,),
        )
        conn.commit()

    service = object.__new__(PipelineService)
    service.db_path = db_path
    service.data_dir = tmp_path
    original_connect = db_mod.sqlite3.connect
    connection_count = 0
    statements: list[str] = []

    def counted_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(lambda statement: statements.append(statement.strip()))
        return conn

    monkeypatch.setattr(db_mod.sqlite3, "connect", counted_connect)

    books = service.list_books()

    assert connection_count == 1
    assert len([statement for statement in statements if statement.upper().startswith("SELECT")]) == 1
    assert [book["title"] for book in books] == ["Active"]
