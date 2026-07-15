from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.database.db import get_book_by_title, get_chapter, init_db, list_chapters
from app.mobile_api.services.pipeline_service import PipelineService


def _pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    pipeline.data_dir = data_dir
    pipeline.legacy_artifact_root = None
    return pipeline


def _import_url_chapter(pipeline: PipelineService, text: str = "Noi dung chuong"):
    return pipeline.import_from_text(
        "Truyen thu nghiem",
        1,
        "Mo dau",
        text,
        source_type="url",
        source_url="HTTPS://Example.TEST:443/books/one#fragment",
        book_source="example",
        book_source_url="HTTPS://Example.TEST:443/books",
        adapter_id="example-adapter",
    )


def test_importing_same_canonical_chapter_twice_skips_duplicate(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    pipeline = _pipeline(temp_db_path, tmp_path)

    created = _import_url_chapter(pipeline)
    skipped = _import_url_chapter(pipeline)

    chapters = list_chapters(temp_db_path, created.book_id)
    assert len(chapters) == 1
    assert created.operation == "created"
    assert skipped.operation == "skipped_duplicate"
    assert skipped.chapter_id == created.chapter_id
    assert skipped.content_hash == created.content_hash
    assert chapters[0]["canonical_chapter_url"] == "https://example.test/books/one"


def test_importing_same_identity_with_new_content_updates_in_place(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    pipeline = _pipeline(temp_db_path, tmp_path)

    created = _import_url_chapter(pipeline, "Noi dung cu")
    updated = _import_url_chapter(pipeline, "Noi dung moi")

    chapters = list_chapters(temp_db_path, created.book_id)
    chapter = get_chapter(temp_db_path, created.book_id, 1)
    assert len(chapters) == 1
    assert chapter is not None
    assert updated.operation == "updated"
    assert updated.chapter_id == created.chapter_id
    assert updated.content_hash != created.content_hash
    assert chapter["content_hash"] == updated.content_hash
    assert chapter["content_revision"] == 2
    assert Path(chapter["raw_text_path"]).read_text(encoding="utf-8") == "Noi dung moi"


def test_concurrent_imports_with_same_identity_create_one_chapter(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)

    def run_import() -> object:
        return _import_url_chapter(_pipeline(temp_db_path, tmp_path), "Noi dung dong thoi")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: run_import(), range(2)))

    chapters = list_chapters(temp_db_path, first.book_id)
    assert len(chapters) == 1
    assert {first.operation, second.operation} == {"created", "skipped_duplicate"}
    assert first.chapter_id == second.chapter_id


def test_import_transaction_rolls_back_new_book_when_chapter_write_fails(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    pipeline = _pipeline(temp_db_path, tmp_path)

    def fail_write(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.OperationalError("forced chapter failure")

    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.upsert_import_chapter_with_connection",
        fail_write,
    )

    with pytest.raises(Exception, match="Could not import chapter content"):
        _import_url_chapter(pipeline)

    assert get_book_by_title(temp_db_path, "Truyen thu nghiem") is None
    assert not list((tmp_path / "raw").glob("*.txt"))


def test_init_db_backfills_legacy_import_identity_without_removing_records(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            book_key TEXT DEFAULT '',
            owner_user_id TEXT DEFAULT '',
            author TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            source_url TEXT DEFAULT '',
            cover_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            chapter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            adapter_id TEXT DEFAULT '',
            raw_text_path TEXT,
            cleaned_text_path TEXT,
            translated_text_path TEXT,
            content_html_path TEXT,
            audio_path TEXT,
            source_hash TEXT DEFAULT '',
            status TEXT DEFAULT 'imported',
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            translated_at TIMESTAMP,
            audio_created_at TIMESTAMP,
            deleted_at TIMESTAMP
        );
        INSERT INTO books (title, book_key, source_url)
        VALUES ('Sach cu', 'sachcu', 'HTTPS://Example.TEST:443/books/old#fragment');
        INSERT INTO chapters (book_id, chapter_number, title, source_url, adapter_id, source_hash)
        VALUES (1, 1, 'Mo dau', 'HTTPS://Example.TEST:443/books/old/1#fragment', 'example-adapter', 'legacy-hash');
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    book = conn.execute("SELECT * FROM books WHERE id = 1").fetchone()
    chapter = conn.execute("SELECT * FROM chapters WHERE id = 1").fetchone()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chapters)").fetchall()}
    conn.close()

    assert book is not None
    assert chapter is not None
    assert {"canonical_chapter_url", "content_hash", "source_updated_at", "content_revision"} <= columns
    assert book["canonical_source_url"] == "https://example.test/books/old"
    assert chapter["canonical_chapter_url"] == "https://example.test/books/old/1"
    assert chapter["content_hash"] == "legacy-hash"
    assert chapter["content_revision"] == 1
