from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from app.database.db import (
    add_book,
    add_chapter,
    get_book_by_id,
    get_book_by_title,
    get_chapter,
    get_chapter_by_id,
    get_connection,
    get_job_attempts,
    get_mobile_job,
    get_qa_report,
    get_last_summary,
    init_db,
    list_glossary,
    list_books,
    list_chapters,
    load_glossary,
    put_glossary_term,
    record_job_attempt,
    request_cancel_mobile_job,
    save_mobile_job,
    save_summary,
    update_chapter_paths,
    glossary_stats,
    get_glossary_pending,
    load_locked_glossary_terms,
    approve_glossary_term,
    reject_glossary_term,
    set_glossary_term_mode,
    glossary_coverage,
    auto_approve_glossary,
    get_glossary_conflicts,
)
import app.database.db as db_mod


def test_db_reexports_connection_function_object(temp_db_path: Path) -> None:
    from app.database.connection import get_connection as repository_get_connection

    assert db_mod.get_connection is repository_get_connection
    with db_mod.get_connection(temp_db_path) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_save_mobile_job_preserves_durable_cancellation_against_stale_update(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    job = {
        "job_id": "durable-cancel",
        "job_type": "daily",
        "status": "running",
        "created_at": "2026-08-10T00:00:00+00:00",
        "updated_at": "2026-08-10T00:00:00+00:00",
    }
    save_mobile_job(temp_db_path, job)
    assert request_cancel_mobile_job(temp_db_path, job_id=job["job_id"])

    stale_completion = {**job, "status": "completed", "state": "COMPLETED", "updated_at": "2026-08-10T00:01:00+00:00"}
    save_mobile_job(temp_db_path, stale_completion)

    persisted = get_mobile_job(temp_db_path, job["job_id"])
    assert persisted is not None
    assert persisted["cancel_requested"] is True
    assert persisted["status"] == "cancelled"
    assert persisted["state"] == "CANCELED"


def test_add_and_get_book(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book", "Author", "web", "http://example.com")
    assert book_id == 1

    book = get_book_by_title(temp_db_path, "Test Book")
    assert book is not None
    assert book["title"] == "Test Book"
    assert book["author"] == "Author"
    assert book["source"] == "web"
    assert book["source_url"] == "http://example.com"
    assert book["cover_path"] == ""


def test_book_cover_path_is_persisted_and_updateable(temp_db_path: Path, tmp_path: Path):
    init_db(temp_db_path)
    cover_path = tmp_path / "cover.jpg"
    updated_cover_path = tmp_path / "updated-cover.jpg"

    book_id = add_book(
        temp_db_path,
        "Cover Book",
        "Author",
        "ebook",
        "",
        cover_path=str(cover_path),
    )

    book = get_book_by_id(temp_db_path, book_id)
    assert book is not None
    assert book["cover_path"] == str(cover_path)

    updated = db_mod.update_book(temp_db_path, book_id, cover_path=str(updated_cover_path))

    assert updated is True
    assert get_book_by_id(temp_db_path, book_id)["cover_path"] == str(updated_cover_path)


def test_init_db_seeds_style_profiles_and_glossary_metadata(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    profiles = db_mod.list_style_profiles(temp_db_path)
    default_profile = db_mod.get_default_style_profile(temp_db_path)

    assert [profile["id"] for profile in profiles] == [
        "tien_hiep",
        "huyen_huyen",
        "kiem_hiep",
        "he_thong",
    ]
    assert default_profile is not None
    assert default_profile["id"] == "tien_hiep"
    assert "sư huynh" in default_profile["pronoun_rules"]
    assert "level up" in default_profile["banned_modern_terms"]
    global_glossary = load_glossary(temp_db_path, 0)
    locked_terms = load_locked_glossary_terms(temp_db_path, 0)
    locked_by_source = {term["source_term"]: term for term in locked_terms}
    assert global_glossary["宿主"] == "ký chủ"
    assert global_glossary["积分"] == "điểm tích lũy"
    assert global_glossary["江湖"] == "giang hồ"
    assert locked_by_source["灵气"]["target_term"] == "linh khí"
    assert locked_by_source["灵气"]["genre"] == "tien_hiep"

    with get_connection(temp_db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)").fetchall()}

    assert {"locked", "genre", "term_type", "priority"}.issubset(columns)


def test_init_db_restricts_sqlite_file_permissions(
    temp_db_path: Path,
    monkeypatch,
) -> None:
    chmod_calls: list[tuple[Path, int]] = []

    def record_chmod(path: Path, mode: int, *args, **kwargs) -> None:
        chmod_calls.append((path, mode))

    monkeypatch.setattr(Path, "chmod", record_chmod)
    init_db(temp_db_path)

    assert (temp_db_path, 0o660) in chmod_calls


def test_recreated_sqlite_sidecars_keep_service_only_permissions() -> None:
    """A later SQLite write must not recreate WAL/SHM with world access."""
    with tempfile.TemporaryDirectory(dir="/tmp") as root:
        db_path = Path(root) / "sidecar-permissions.db"
        wal_path = db_path.with_name(f"{db_path.name}-wal")
        shm_path = db_path.with_name(f"{db_path.name}-shm")

        original_umask = os.umask(0)
        try:
            with get_connection(db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE permission_sidecar_probe (id INTEGER PRIMARY KEY)")
        finally:
            os.umask(original_umask)

        assert stat.S_IMODE(db_path.stat().st_mode) == 0o660
        assert stat.S_IMODE(wal_path.stat().st_mode) == 0o660
        assert stat.S_IMODE(shm_path.stat().st_mode) == 0o660


def test_get_connection_does_not_change_the_process_umask(tmp_path: Path) -> None:
    previous_umask = os.umask(0o022)
    try:
        get_connection(tmp_path / "process-umask.db").close()
        observed_umask = os.umask(0o022)
        assert observed_umask == 0o022
    finally:
        os.umask(previous_umask)


def test_set_default_style_profile_keeps_single_default(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    assert db_mod.set_default_style_profile(temp_db_path, "kiem_hiep") is True

    default_profile = db_mod.get_default_style_profile(temp_db_path)
    profiles = db_mod.list_style_profiles(temp_db_path)

    assert default_profile is not None
    assert default_profile["id"] == "kiem_hiep"
    assert sum(profile["is_default"] for profile in profiles) == 1


def test_migrates_legacy_qa_reports_without_book_id(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-qa.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                source TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                raw_text_path TEXT,
                cleaned_text_path TEXT,
                translated_text_path TEXT,
                audio_path TEXT,
                status TEXT DEFAULT 'new',
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                translated_at TIMESTAMP,
                audio_created_at TIMESTAMP
            );
            CREATE TABLE qa_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                quality_score REAL DEFAULT 0,
                fidelity_score REAL DEFAULT 0,
                style_score REAL DEFAULT 0,
                glossary_score REAL DEFAULT 0,
                audiobook_score REAL DEFAULT 0,
                verdict TEXT DEFAULT 'UNKNOWN',
                report_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO books (id, title) VALUES (1, 'Legacy Book');
            INSERT INTO chapters (id, book_id, chapter_number, title) VALUES (10, 1, 1, 'Legacy Chapter');
            INSERT INTO qa_reports (chapter_id, quality_score, verdict, report_json)
            VALUES (10, 8.5, 'PASS', '{}');
            """
        )

    init_db(db_path)
    report = get_qa_report(db_path, 1, 10)

    assert report is not None
    assert report["book_id"] == 1
    assert report["quality_score"] == 8.5


def test_soft_delete_releases_legacy_unique_chapter_number(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-chapter-unique.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                source TEXT DEFAULT 'manual',
                source_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                raw_text_path TEXT,
                cleaned_text_path TEXT,
                translated_text_path TEXT,
                audio_path TEXT,
                status TEXT DEFAULT 'imported',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                translated_at TIMESTAMP,
                audio_created_at TIMESTAMP,
                UNIQUE(book_id, chapter_number)
            );
            CREATE TABLE qa_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL);
            CREATE TABLE translation_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL);
            CREATE TABLE chapter_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL);
            INSERT INTO books (id, title) VALUES (1, 'Legacy Book');
            INSERT INTO chapters (id, book_id, chapter_number, title) VALUES (10, 1, 1, 'Old Chapter');
            """
        )

    init_db(db_path)
    assert db_mod.soft_delete_chapter(db_path, 10) is True
    replacement_id = add_chapter(db_path, 1, 1, "Replacement Chapter")

    replacement = get_chapter_by_id(db_path, replacement_id)
    assert replacement is not None
    assert replacement["chapter_number"] == 1


def test_list_books(temp_db_path: Path):
    init_db(temp_db_path)
    add_book(temp_db_path, "Book A")
    add_book(temp_db_path, "Book B")
    books = list_books(temp_db_path)
    assert len(books) == 2
    # Most recent first (DESC)
    assert books[0]["title"] == "Book B"
    assert books[1]["title"] == "Book A"


def test_update_book_persists_only_provided_fields(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Old Title", "Old Author", "manual", "old")

    updated = db_mod.update_book(temp_db_path, book_id, title="New Title", source_url="new-url")

    assert updated is True
    book = get_book_by_id(temp_db_path, book_id)
    assert book is not None
    assert book["title"] == "New Title"
    assert book["author"] == "Old Author"
    assert book["source"] == "manual"
    assert book["source_url"] == "new-url"


def test_update_book_title_merges_into_existing_book_without_losing_chapter_paths(
    temp_db_path: Path,
    tmp_path: Path,
):
    init_db(temp_db_path)
    target_book_id = add_book(temp_db_path, "Thanh Sơn", "Translator", "ebook", "")
    source_book_id = add_book(temp_db_path, "Thanh Sơn raw", "", "source", "https://example.test/raw")
    translated_path = tmp_path / "translated.txt"
    raw_path = tmp_path / "raw.txt"
    translated_path.write_text("Bản dịch chương một", encoding="utf-8")
    raw_path.write_text("原文第一章", encoding="utf-8")
    target_chapter_id = add_chapter(temp_db_path, target_book_id, 1, "Chương một")
    source_chapter_id = add_chapter(temp_db_path, source_book_id, 1, "Raw chương một", raw_text_path=raw_path)
    update_chapter_paths(temp_db_path, target_chapter_id, translated_text_path=translated_path, status="translated")

    updated = db_mod.update_book(temp_db_path, source_book_id, title="Thanh Sơn")

    assert updated is True
    visible_books = list_books(temp_db_path)
    assert [book["id"] for book in visible_books if book["title"] == "Thanh Sơn"] == [target_book_id]
    merged_chapters = list_chapters(temp_db_path, target_book_id)
    assert len(merged_chapters) == 1
    assert merged_chapters[0]["id"] == target_chapter_id
    assert merged_chapters[0]["raw_text_path"] == str(raw_path)
    assert merged_chapters[0]["translated_text_path"] == str(translated_path)
    assert get_chapter_by_id(temp_db_path, source_chapter_id) is None


def test_list_books_consolidates_existing_duplicate_book_keys(
    temp_db_path: Path,
    tmp_path: Path,
):
    init_db(temp_db_path)
    translated_path = tmp_path / "translated.txt"
    raw_path = tmp_path / "raw.txt"
    translated_path.write_text("Bản dịch chương một", encoding="utf-8")
    raw_path.write_text("原文第一章", encoding="utf-8")

    raw_conn = sqlite3.connect(temp_db_path)
    try:
        target_book_id = raw_conn.execute(
            "INSERT INTO books (title, book_key, author, source, source_url) VALUES (?, ?, ?, ?, ?)",
            ("Thanh Sơn", "thanh-son", "Translator", "ebook", ""),
        ).lastrowid
        source_book_id = raw_conn.execute(
            "INSERT INTO books (title, book_key, author, source, source_url) VALUES (?, ?, ?, ?, ?)",
            ("Thanh Sơn", "thanh-son", "", "source", "https://example.test/raw"),
        ).lastrowid
        target_chapter_id = raw_conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, translated_text_path, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (target_book_id, 1, "Chương một", str(translated_path), "translated"),
        ).lastrowid
        source_chapter_id = raw_conn.execute(
            """
            INSERT INTO chapters (book_id, chapter_number, title, raw_text_path, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_book_id, 1, "Raw chương một", str(raw_path), "imported"),
        ).lastrowid
        raw_conn.commit()
    finally:
        raw_conn.close()

    init_db(temp_db_path)
    visible_books = list_books(temp_db_path)

    assert [book["id"] for book in visible_books if book["title"] == "Thanh Sơn"] == [target_book_id]
    merged_chapters = list_chapters(temp_db_path, target_book_id)
    assert len(merged_chapters) == 1
    assert merged_chapters[0]["id"] == target_chapter_id
    assert merged_chapters[0]["raw_text_path"] == str(raw_path)
    assert merged_chapters[0]["translated_text_path"] == str(translated_path)
    assert get_book_by_id(temp_db_path, source_book_id) is None
    assert get_chapter_by_id(temp_db_path, source_chapter_id) is None


def test_delete_book_removes_book_and_cascades_chapters(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book To Delete")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter 1")

    deleted = db_mod.delete_book(temp_db_path, book_id)

    assert deleted is True
    assert get_book_by_id(temp_db_path, book_id) is None
    assert get_chapter_by_id(temp_db_path, chapter_id) is None
    assert db_mod.delete_book(temp_db_path, book_id) is False


def test_add_and_get_chapter(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")
    chapter_id = add_chapter(
        temp_db_path,
        book_id=book_id,
        chapter_number=1,
        title="第一章",
        source_url="http://example.com/1",
        adapter_id="generic_html",
        raw_text_path=Path("/tmp/raw1.txt"),
    )
    assert chapter_id == 1

    chapter = get_chapter(temp_db_path, book_id=book_id, chapter_number=1)
    assert chapter is not None
    assert chapter["title"] == "第一章"
    assert chapter["source_url"] == "http://example.com/1"
    assert chapter["adapter_id"] == "generic_html"
    assert chapter["raw_text_path"] == "/tmp/raw1.txt"


def test_list_chapters(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")
    add_chapter(temp_db_path, book_id, 1, "Chapter 1")
    add_chapter(temp_db_path, book_id, 2, "Chapter 2")
    chapters = list_chapters(temp_db_path, book_id=book_id)
    assert len(chapters) == 2
    # Ordered by chapter_number DESC
    assert chapters[0]["chapter_number"] == 2
    assert chapters[1]["chapter_number"] == 1


def test_list_chapters_filters_book_id_zero(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")
    add_chapter(temp_db_path, book_id, 1, "Chapter 1")

    assert list_chapters(temp_db_path, book_id=0) == []


def test_update_chapter_paths(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter 1")

    update_chapter_paths(
        temp_db_path,
        chapter_id,
        cleaned_text_path=Path("/tmp/clean1.txt"),
        translated_text_path=Path("/tmp/trans1.txt"),
        status="translated",
    )

    chapter = get_chapter(temp_db_path, book_id=book_id, chapter_number=1)
    assert chapter["cleaned_text_path"] == "/tmp/clean1.txt"
    assert chapter["translated_text_path"] == "/tmp/trans1.txt"
    assert chapter["status"] == "translated"
    # translated_at should be set (not None)
    assert chapter["translated_at"] is not None


def test_glossary_put_and_load(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", "term", mode="translate")
    put_glossary_term(temp_db_path, book_id, "修真", "tu chân", "practice", mode="translate")

    glossary = load_glossary(temp_db_path, book_id)
    assert glossary["灵石"] == "linh thạch"
    assert glossary["修真"] == "tu chân"
    # Global glossary (book_id=0) is also included by default
    # We didn't add any global terms, so only the two above.


def test_glossary_variants_are_loaded_for_translation_and_coverage(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(
        temp_db_path,
        book_id,
        "灵石",
        "linh thạch",
        "term",
        mode="translate",
        variants="靈石|灵矿",
    )

    glossary = load_glossary(temp_db_path, book_id)
    coverage = glossary_coverage(temp_db_path, book_id, "他拿起靈石。")

    assert glossary["灵石"] == "linh thạch"
    assert glossary["靈石"] == "linh thạch"
    assert glossary["灵矿"] == "linh thạch"
    assert ("靈石", "linh thạch") in coverage["hits"]


def test_glossary_occurrence_count_default_is_zero(temp_db_path: Path):
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        conn.execute(
            "INSERT INTO glossary_terms (source_term, target_term) VALUES (?, ?)",
            ("默认", "mặc định"),
        )
        row = conn.execute(
            "SELECT occurrence_count FROM glossary_terms WHERE source_term = ?",
            ("默认",),
        ).fetchone()

    assert row[0] == 0


def test_glossary_stats(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    # Add terms with different modes
    put_glossary_term(temp_db_path, 0, "术", "thuật", "term", mode="translate")
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", "term", mode="translate")
    put_glossary_term(temp_db_path, 0, "韩立", "Hàn Lập", "character", mode="transliterate")
    put_glossary_term(temp_db_path, 0, "七玄门", "Thất Huyền Môn", "sect", mode="context")

    stats = glossary_stats(temp_db_path, book_id)
    assert stats["total"] == 4
    assert stats["translate"] == 2
    assert stats["transliterate"] == 1
    assert stats["context"] == 1
    assert stats["categories"] >= 3


def test_list_glossary_book_zero_only_returns_global_terms(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")

    put_glossary_term(temp_db_path, 0, "全局", "toàn cục", mode="translate")
    put_glossary_term(temp_db_path, book_id, "本书", "sách này", mode="translate")

    terms = list_glossary(temp_db_path, book_id=0)

    assert [term["source_term"] for term in terms] == ["全局"]


def test_glossary_stats_book_zero_only_counts_global_terms(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")

    put_glossary_term(temp_db_path, 0, "全局", "toàn cục", mode="translate")
    put_glossary_term(temp_db_path, book_id, "本书", "sách này", mode="translate")

    stats = glossary_stats(temp_db_path, book_id=0)

    assert stats["total"] == 1
    assert stats["translate"] == 1


def test_get_glossary_pending(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    # Add approved and pending terms
    put_glossary_term(temp_db_path, book_id, "test1", "thử nghiệm", mode="translate")
    put_glossary_term(temp_db_path, book_id, "test2", "thử nghiệm2", mode="translate")
    conn = get_connection(temp_db_path)
    conn.execute("UPDATE glossary_terms SET approved = 0 WHERE source_term = 'test2'")
    conn.commit()

    pending = get_glossary_pending(temp_db_path, book_id, limit=10)
    assert len(pending) == 1
    assert pending[0]["source_term"] == "test2"


def test_get_glossary_pending_book_zero_only_returns_global_terms(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")

    put_glossary_term(temp_db_path, 0, "global-pending", "global", mode="translate", approved=0)
    put_glossary_term(temp_db_path, book_id, "book-pending", "book", mode="translate", approved=0)

    pending = get_glossary_pending(temp_db_path, book_id=0, limit=10)

    assert [term["source_term"] for term in pending] == ["global-pending"]


def test_get_translation_suggestions_book_zero_only_returns_global_suggestions(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    db_mod.add_translation_suggestion(temp_db_path, "global-q", "global-s", book_id=0)
    db_mod.add_translation_suggestion(temp_db_path, "book-q", "book-s", book_id=book_id)

    suggestions = db_mod.get_translation_suggestions(temp_db_path, book_id=0)

    assert [suggestion["q"] for suggestion in suggestions] == ["global-q"]


def test_job_attempt_crud_records_orders_and_filters_attempts(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    first_id = record_job_attempt(
        temp_db_path,
        job_id="job-1",
        chapter_id=12,
        stage="translate",
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        status="failed",
        error="rate limit",
        elapsed_ms=1234,
    )
    second_id = record_job_attempt(
        temp_db_path,
        job_id="job-1",
        chapter_id=12,
        provider_id="openrouter",
        model="openrouter/free",
        status="success",
    )
    record_job_attempt(
        temp_db_path,
        job_id="job-2",
        chapter_id=13,
        provider_id="ollama",
        model="qwen3:14b",
        status="failed",
        error="timeout",
        elapsed_ms=5000,
    )

    all_job_attempts = get_job_attempts(temp_db_path, job_id="job-1")
    chapter_attempts = get_job_attempts(temp_db_path, chapter_id=12)
    limited_attempts = get_job_attempts(temp_db_path, limit=1)

    assert first_id > 0
    assert second_id > first_id
    assert [attempt["id"] for attempt in all_job_attempts] == [second_id, first_id]
    assert all_job_attempts[0]["status"] == "success"
    assert all_job_attempts[0]["stage"] == ""
    assert all_job_attempts[0]["error"] == ""
    assert all_job_attempts[0]["elapsed_ms"] == 0
    assert all_job_attempts[1]["stage"] == "translate"
    assert all_job_attempts[1]["error"] == "rate limit"
    assert all_job_attempts[1]["elapsed_ms"] == 1234
    assert [attempt["job_id"] for attempt in chapter_attempts] == ["job-1", "job-1"]
    assert len(limited_attempts) == 1
    assert limited_attempts[0]["job_id"] == "job-2"


def test_job_attempt_filter_indexes_exist_after_init(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        index_names = {
            row["name"]
            for row in conn.execute("PRAGMA index_list(job_attempts)").fetchall()
        }

    assert "idx_job_attempts_job_id" in index_names
    assert "idx_job_attempts_chapter_id" in index_names


def test_approve_reject_glossary_term(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "临时", "tạm thời", mode="translate")
    conn = get_connection(temp_db_path)
    term_id = conn.execute("SELECT id FROM glossary_terms WHERE source_term = '临时'").fetchone()[0]
    conn.execute("UPDATE glossary_terms SET approved = 0 WHERE id = ?", (term_id,))
    conn.commit()

    assert get_glossary_pending(temp_db_path, book_id)  # still pending

    approve_glossary_term(temp_db_path, term_id)
    assert not get_glossary_pending(temp_db_path, book_id)  # cleared

    reject_glossary_term(temp_db_path, term_id)
    # already rejected, should return False
    assert not approve_glossary_term(temp_db_path, term_id)


def test_set_glossary_term_mode(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "测试", "thử nghiệm", mode="translate")
    conn = get_connection(temp_db_path)
    term_id = conn.execute("SELECT id FROM glossary_terms WHERE source_term = '测试'").fetchone()[0]

    ok = set_glossary_term_mode(temp_db_path, term_id, "context")
    assert ok

    # Invalid mode raises ValueError
    try:
        set_glossary_term_mode(temp_db_path, term_id, "invalid")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_glossary_coverage(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate")
    put_glossary_term(temp_db_path, book_id, "修真", "tu chân", mode="translate")

    source = "灵石和修真是游戏的核心。"
    result = glossary_coverage(temp_db_path, book_id, source)

    assert result["matched_count"] == 2
    assert result["total_chars"] == len(source)
    assert result["covered_chars"] > 0
    assert 0 <= result["coverage_pct"] <= 100


def test_glossary_coverage_counts_overlapping_terms_once(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate")
    put_glossary_term(temp_db_path, book_id, "灵石矿", "mỏ linh thạch", mode="translate")

    result = glossary_coverage(temp_db_path, book_id, "灵石矿旁边")

    assert result["covered_chars"] == len("灵石矿")
    assert result["coverage_pct"] == round(len("灵石矿") / len("灵石矿旁边") * 100, 1)


def test_glossary_occurrence_count_tracks_repeated_terms(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate", approved=0)
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate", approved=0)
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate", approved=0)

    conn = get_connection(temp_db_path)
    row = conn.execute("SELECT occurrence_count, approved FROM glossary_terms WHERE source_term = '灵石'").fetchone()
    assert row[0] == 3
    assert row[1] == 0


def test_auto_approve_glossary(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, book_id, "灵兽", "linh thú", mode="", approved=0)
    put_glossary_term(temp_db_path, book_id, "灵兽", "linh thú", mode="", approved=0)
    put_glossary_term(temp_db_path, book_id, "灵兽", "linh thú", mode="", approved=0)

    count = auto_approve_glossary(temp_db_path, min_occurrences=3, book_id=book_id)
    assert count == 1

    conn = get_connection(temp_db_path)
    row = conn.execute("SELECT approved, mode FROM glossary_terms WHERE source_term = '灵兽'").fetchone()
    assert row[0] == 1
    assert row[1] == "translate"


def test_get_glossary_conflicts(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    put_glossary_term(temp_db_path, 0, "掌门", "chưởng môn", mode="translate")
    put_glossary_term(temp_db_path, book_id, "掌门", "môn chủ", mode="translate")

    conflicts = get_glossary_conflicts(temp_db_path, book_id)
    assert len(conflicts) == 1
    assert conflicts[0]["source_term"] == "掌门"
    assert len(conflicts[0]["targets"]) == 2


def test_search_fuzzy_tm_returns_ranked_matches_with_metadata(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")

    db_mod.add_fuzzy_tm_entry(
        temp_db_path,
        "他拿起灵石。",
        "Hắn cầm linh thạch lên.",
        score=96,
        book_id=book_id,
        chapter_number=3,
    )
    db_mod.add_fuzzy_tm_entry(
        temp_db_path,
        "她推开木门。",
        "Nàng đẩy cửa gỗ ra.",
        score=90,
        book_id=book_id,
        chapter_number=4,
    )

    matches = db_mod.search_fuzzy_tm(temp_db_path, "他拿起灵石。", threshold=80, limit=5)

    assert len(matches) == 1
    assert matches[0]["source_text"] == "他拿起灵石。"
    assert matches[0]["translation_text"] == "Hắn cầm linh thạch lên."
    assert matches[0]["match_score"] == 100
    assert matches[0]["stored_score"] == 96
    assert matches[0]["book_id"] == book_id
    assert matches[0]["chapter_number"] == 3


def test_save_and_get_summary(temp_db_path: Path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Test Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter 1")

    save_summary(temp_db_path, chapter_id, "This is a summary.")
    summary = get_last_summary(temp_db_path, book_id)
    assert summary == "This is a summary."

    # Adding another chapter and summary should update the last summary
    chapter_id2 = add_chapter(temp_db_path, book_id, 2, "Chapter 2")
    save_summary(temp_db_path, chapter_id2, "Second summary.")
    summary2 = get_last_summary(temp_db_path, book_id)
    assert summary2 == "Second summary."
