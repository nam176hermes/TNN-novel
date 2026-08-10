from __future__ import annotations

import sqlite3

import pytest

from app.database.db import init_db
from app.database.import_jobs import (
    ImportJobRepository,
    InvalidImportJobTransition,
    JobStatus,
    TaskStage,
    TaskStatus,
)
from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
    PreviewBrowserPayload,
    encode_browser_result,
)


def _repository(temp_db_path):
    init_db(temp_db_path)
    return ImportJobRepository(temp_db_path)


def _job(repository: ImportJobRepository, owner: str = "operator-a"):
    return repository.create_job(
        owner_user_id=owner,
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        total=0,
        config_snapshot={"adapter_id": "69shuba", "cookie": "must-not-persist"},
    )


def _task(repository: ImportJobRepository, job_id: str, owner: str = "operator-a"):
    return repository.create_task(
        job_id=job_id,
        owner_user_id=owner,
        canonical_identity="69shuba:https://www.69shuba.com/chapter/1",
        canonical_chapter_url="https://www.69shuba.com/chapter/1",
        chapter_number=1,
        title="Chương 1",
    )


def test_import_job_state_machine_allows_only_declared_transitions(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    job = _job(repository)

    running = repository.transition_job(job.id, "operator-a", JobStatus.RUNNING)
    succeeded = repository.transition_job(job.id, "operator-a", JobStatus.SUCCEEDED)

    assert running.status is JobStatus.RUNNING
    assert succeeded.status is JobStatus.SUCCEEDED
    with pytest.raises(InvalidImportJobTransition):
        repository.transition_job(job.id, "operator-a", JobStatus.RUNNING)


def test_terminal_task_only_returns_to_queue_through_explicit_retry(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    task = _task(repository, _job(repository).id)
    repository.transition_task(
        task.id,
        "operator-a",
        status=TaskStatus.RUNNING,
        stage=TaskStage.FETCHING,
    )
    failed = repository.transition_task(
        task.id,
        "operator-a",
        status=TaskStatus.FAILED,
        stage=TaskStage.FAILED,
        error_code="source_unavailable",
    )

    assert failed.status is TaskStatus.FAILED
    with pytest.raises(InvalidImportJobTransition):
        repository.transition_task(
            task.id,
            "operator-a",
            status=TaskStatus.RUNNING,
            stage=TaskStage.FETCHING,
        )

    retried = repository.retry_task(task.id, "operator-a")
    assert retried.status is TaskStatus.QUEUED
    assert retried.stage is TaskStage.QUEUED
    assert retried.attempts == 1


def test_cancel_request_is_idempotent_and_event_payload_is_sanitized(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    job = _job(repository)
    task = _task(repository, job.id)
    repository.transition_job(job.id, "operator-a", JobStatus.RUNNING)
    claimed = repository.claim_next_task(job.id, "operator-a", worker_id="chapter-worker-a")
    assert claimed is not None and claimed.id == task.id

    first = repository.request_cancel(job.id, "operator-a")
    second = repository.request_cancel(job.id, "operator-a")
    events = repository.list_events(job.id, "operator-a")
    current_task = repository.list_tasks(job.id, "operator-a")[0]

    assert first.cancel_requested_at
    assert second.cancel_requested_at == first.cancel_requested_at
    assert first.status is JobStatus.RUNNING
    assert first.result_snapshot is None
    assert current_task.status is TaskStatus.RUNNING
    assert current_task.lease_token == claimed.lease_token
    assert [event.event_type for event in events] == [
        "job_created",
        "task_created",
        "job_transitioned",
        "task_claimed",
        "cancel_requested",
    ]
    assert repository.get_job(job.id, "operator-a").config_snapshot == {"adapter_id": "69shuba"}


def test_task_counters_are_derived_consistently_and_events_are_monotonic(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    job = _job(repository)
    first = _task(repository, job.id)
    second = repository.create_task(
        job_id=job.id,
        owner_user_id="operator-a",
        canonical_identity="69shuba:https://www.69shuba.com/chapter/2",
        canonical_chapter_url="https://www.69shuba.com/chapter/2",
        chapter_number=2,
        title="Chương 2",
    )

    repository.transition_task(
        first.id,
        "operator-a",
        status=TaskStatus.RUNNING,
        stage=TaskStage.FETCHING,
    )
    repository.transition_task(
        first.id,
        "operator-a",
        status=TaskStatus.SUCCEEDED,
        stage=TaskStage.SUCCEEDED,
        text_length=42,
        content_hash="hash-1",
    )
    repository.transition_task(
        second.id,
        "operator-a",
        status=TaskStatus.RUNNING,
        stage=TaskStage.FETCHING,
    )
    repository.transition_task(
        second.id,
        "operator-a",
        status=TaskStatus.FAILED,
        stage=TaskStage.FAILED,
        error_code="content_invalid",
    )

    current = repository.get_job(job.id, "operator-a")
    events = repository.list_events(job.id, "operator-a")

    assert current.total == 2
    assert current.succeeded_count == 1
    assert current.failed_count == 1
    assert current.queued_count == 0
    assert current.running_count == 0
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_owner_isolation_prevents_cross_owner_reads_and_transitions(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    job = _job(repository, owner="operator-a")
    task = _task(repository, job.id, owner="operator-a")

    assert repository.get_job(job.id, "operator-b") is None
    assert repository.list_tasks(job.id, "operator-b") == []
    assert repository.list_events(job.id, "operator-b") == []
    with pytest.raises(PermissionError):
        repository.transition_task(
            task.id,
            "operator-b",
            status=TaskStatus.RUNNING,
            stage=TaskStage.FETCHING,
        )


def test_init_db_migrates_legacy_database_with_import_job_tables(tmp_path) -> None:
    db_path = tmp_path / "legacy-import-job.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                source TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
            CREATE TABLE import_jobs (id TEXT PRIMARY KEY);
            INSERT INTO import_jobs (id) VALUES ('legacy-job');
            CREATE TABLE chapter_tasks (
                id INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                canonical_identity TEXT NOT NULL
            );
            INSERT INTO chapter_tasks (id, job_id, canonical_identity)
            VALUES (1, 'legacy-job', 'legacy:chapter'), (2, 'legacy-job', 'legacy:chapter');
            CREATE TABLE import_job_events (
                id INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                sequence INTEGER NOT NULL
            );
            INSERT INTO import_job_events (id, job_id, sequence)
            VALUES (1, 'legacy-job', 1), (2, 'legacy-job', 1);
            """
        )

    init_db(db_path)
    repository = ImportJobRepository(db_path)
    job = _job(repository)

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(import_jobs)")
        }
        task_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(chapter_tasks)")
        }
        preserved_legacy_rows = connection.execute(
            "SELECT COUNT(*) FROM chapter_tasks WHERE job_id = 'legacy-job'"
        ).fetchone()[0]

    assert {"import_jobs", "chapter_tasks", "import_job_events"}.issubset(tables)
    assert {
        "cancel_requested_at",
        "config_snapshot_json",
        "error_summary",
        "operation_kind",
        "deadline_at",
        "correlation_id",
        "result_state",
        "result_snapshot_json",
        "result_published_at",
    }.issubset(columns)
    assert {"retryable", "lease_token", "lease_owner", "lease_expires_at"}.issubset(task_columns)
    assert preserved_legacy_rows == 2
    with sqlite3.connect(db_path) as connection:
        legacy_row = connection.execute(
            "SELECT id, operation_kind, source, source_url FROM import_jobs WHERE id = 'legacy-job'"
        ).fetchone()
    assert legacy_row == ("legacy-job", "import_chapters", "", "")
    assert job.id


def test_new_import_jobs_default_to_chapter_operation_with_empty_result(temp_db_path) -> None:
    repository = _repository(temp_db_path)

    job = _job(repository)

    assert job.operation_kind is ImportOperationKind.IMPORT_CHAPTERS
    assert job.deadline_at == ""
    assert job.correlation_id == ""
    assert job.result_state is None
    assert job.result_snapshot is None
    assert job.result_published_at == ""


def test_preview_job_round_trips_deadline_correlation_and_result_fields(temp_db_path) -> None:
    repository = _repository(temp_db_path)
    result = BrowserTaskResult(
        correlation_id="preview-correlation",
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload(
            adapter_id="69shuba",
            adapter_label="69shu-ba",
            source="69shuba",
            source_url="https://www.69shuba.com/book/123",
            title="A novel",
        ),
    )
    job = repository.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at="2026-08-10T12:00:00+00:00",
        correlation_id="preview-correlation" + ("x" * 200),
    )
    with sqlite3.connect(temp_db_path) as connection:
        connection.execute(
            """
            UPDATE import_jobs
            SET result_state = ?, result_snapshot_json = ?, result_published_at = ?
            WHERE id = ?
            """,
            (
                BrowserResultState.COMPLETED.value,
                encode_browser_result(result),
                "2026-08-10T11:00:00+00:00",
                job.id,
            ),
        )

    loaded = repository.get_job(job.id, "operator-a")

    assert loaded is not None
    assert loaded.operation_kind is ImportOperationKind.PREVIEW
    assert loaded.deadline_at == "2026-08-10T12:00:00+00:00"
    assert loaded.correlation_id == ("preview-correlation" + ("x" * 200))[:128]
    assert loaded.result_state is BrowserResultState.COMPLETED
    assert loaded.result_snapshot == result
    assert loaded.result_published_at == "2026-08-10T11:00:00+00:00"
