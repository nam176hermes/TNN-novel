from __future__ import annotations

import sqlite3
from pathlib import Path


OWNER_TABLES = (
    "books",
    "mobile_jobs",
    "ebook_import_runs",
    "provider_usage",
    "job_attempts",
)


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _operator_user_id(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT id FROM users WHERE source = 'env' LIMIT 1").fetchone()
    assert row is not None
    return str(row[0])


def _table_owner_values(db_path: Path, table_name: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"SELECT owner_user_id FROM {table_name} ORDER BY rowid").fetchall()
    return [str(row[0] or "") for row in rows]


def test_core_resource_tables_have_owner_user_id(temp_db_path: Path) -> None:
    from app.database.db import init_db

    init_db(temp_db_path)

    for table_name in OWNER_TABLES:
        assert "owner_user_id" in _columns(temp_db_path, table_name)


def test_existing_core_rows_are_backfilled_idempotently(temp_db_path: Path) -> None:
    from app.database.db import init_db

    with sqlite3.connect(temp_db_path) as conn:
        conn.executescript(
            """
            INSERT INTO books (id, title) VALUES (101, 'Legacy Book');
            INSERT INTO mobile_jobs (
                job_id, job_type, status, created_at, updated_at
            ) VALUES ('legacy-job', 'translate', 'queued', '2026-06-30T00:00:00+00:00', '2026-06-30T00:00:00+00:00');
            INSERT INTO ebook_import_runs (id, book_id, title) VALUES (201, 101, 'Legacy Import');
            INSERT INTO provider_usage (
                id, provider_id, model, task_type, prompt_tokens, completion_tokens,
                total_tokens, estimated_cost_usd, job_id
            ) VALUES (301, 'gemini', 'model', 'translate', 1, 2, 3, 0.01, 'legacy-job');
            INSERT INTO job_attempts (
                id, job_id, provider_id, model, status
            ) VALUES (401, 'legacy-job', 'gemini', 'model', 'failed');
            """
        )
        conn.commit()

    init_db(temp_db_path)
    owner_id = _operator_user_id(temp_db_path)

    for table_name in OWNER_TABLES:
        assert _table_owner_values(temp_db_path, table_name) == [owner_id]

    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("UPDATE books SET owner_user_id = 'external-owner' WHERE id = 101")
        conn.commit()

    init_db(temp_db_path)

    assert _table_owner_values(temp_db_path, "books") == ["external-owner"]
    for table_name in OWNER_TABLES[1:]:
        assert _table_owner_values(temp_db_path, table_name) == [owner_id]


def test_new_book_import_usage_and_attempt_rows_get_operator_owner(temp_db_path: Path) -> None:
    from app.database.db import (
        add_book,
        get_book_by_id,
        init_db,
        list_ebook_import_runs,
        record_ebook_import_run,
        record_job_attempt,
        record_provider_usage,
    )

    init_db(temp_db_path)
    owner_id = _operator_user_id(temp_db_path)

    book_id = add_book(temp_db_path, "Owned Book")
    usage_id = record_provider_usage(
        temp_db_path,
        provider_id="gemini",
        model="gemini-test",
        task_type="translate",
        prompt_tokens=10,
        completion_tokens=5,
        estimated_cost_usd=0.01,
        job_id="owned-job",
        chapter_id=None,
    )
    attempt_id = record_job_attempt(
        temp_db_path,
        job_id="owned-job",
        chapter_id=None,
        provider_id="gemini",
        model="gemini-test",
        status="success",
    )
    import_id = record_ebook_import_run(
        temp_db_path,
        book_id=book_id,
        title="Owned Book",
        filename="owned.epub",
        source_format="epub",
        duplicate_strategy="skip",
        split_mode="auto",
        chapter_count=1,
        imported_chapters=1,
        skipped_chapters=0,
    )

    with sqlite3.connect(temp_db_path) as conn:
        conn.row_factory = sqlite3.Row
        usage = conn.execute("SELECT * FROM provider_usage WHERE id = ?", (usage_id,)).fetchone()
        attempt = conn.execute("SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)).fetchone()

    assert get_book_by_id(temp_db_path, book_id)["owner_user_id"] == owner_id
    assert usage["owner_user_id"] == owner_id
    assert attempt["owner_user_id"] == owner_id
    assert list_ebook_import_runs(temp_db_path)[0]["id"] == import_id
    assert list_ebook_import_runs(temp_db_path)[0]["owner_user_id"] == owner_id


def test_new_mobile_jobs_and_retry_jobs_get_operator_owner(temp_db_path: Path) -> None:
    from app.database.db import get_mobile_job, init_db
    from app.mobile_api.services.job_service import JobService, JobTracker

    class EmptyPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int):
            return None

    init_db(temp_db_path)
    owner_id = _operator_user_id(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path, stale_after_seconds=999999)

    failed = tracker.create_job("translate", [11], 1, {"provider_id": "gemini"})
    tracker.update_job(failed.job_id, status="failed", error="Provider failed")
    retry_job_id = JobService(EmptyPipeline(), tracker=tracker).retry_failed_translation_job(failed.job_id)

    failed_record = get_mobile_job(temp_db_path, failed.job_id)
    retry_record = get_mobile_job(temp_db_path, retry_job_id)

    assert failed_record["owner_user_id"] == owner_id
    assert retry_record["owner_user_id"] == owner_id
    assert retry_record["params"]["retry_of_job_id"] == failed.job_id


def test_owner_metadata_does_not_filter_book_listing(temp_db_path: Path) -> None:
    from app.database.db import add_book, init_db, list_books

    init_db(temp_db_path)
    operator_book_id = add_book(temp_db_path, "Operator Book")
    other_book_id = add_book(temp_db_path, "Other Owner Book")
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute(
            "UPDATE books SET owner_user_id = 'other-owner' WHERE id = ?",
            (other_book_id,),
        )
        conn.commit()

    listed_ids = {book["id"] for book in list_books(temp_db_path)}

    assert {operator_book_id, other_book_id}.issubset(listed_ids)
