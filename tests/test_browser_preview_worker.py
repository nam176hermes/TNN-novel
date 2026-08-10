from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.database.db import init_db
from app.database.import_jobs import (
    ImportJobRepository,
    InvalidImportJobTransition,
    JobStatus,
    TaskStatus,
)
from app.import_contracts import BrowserResultState, ImportOperationKind
from app.import_worker import DurableImportWorker
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.services.import_job_factory import create_import_job_service
from app.services.import_job_runtime import RetryPolicy


OWNER = "operator-a"
SOURCE_URL = "https://www.69shuba.com/book/123"
FUTURE_DEADLINE = "2099-08-10T12:00:00+00:00"
EXPIRED_DEADLINE = "2000-08-10T12:00:00+00:00"


def _preview_mapping(**changes: object) -> dict[str, object]:
    preview: dict[str, object] = {
        "adapter_id": "69shuba",
        "adapter_label": "69shu-ba",
        "adapter_version": "2026.08",
        "parser_method": "html_parser",
        "source": "69shuba",
        "source_url": SOURCE_URL,
        "title": "A novel",
        "author": "Author",
        "description": "Public summary",
        "cover_url": "https://cdn.example.test/cover.jpg",
        "chapters": [
            {
                "chapter_number": 1,
                "title": "Chapter 1",
                "url": "https://www.69shuba.com/chapter/1",
            }
        ],
        "chapter_count": 1,
        "policy": {
            "source_id": "69shuba",
            "label": "69shu-ba",
            "delay_seconds": 1,
            "max_concurrency": 1,
            "retry_limit": 3,
        },
        "bypass_used": False,
        "bypass_method": "",
        "fetch_method": "direct_http",
        "fetch_status_code": 200,
        "fetch_attempts": 1,
        "fetch_elapsed_ms": 25,
        "fetch_bytes_received": 1234,
        "fetch_final_url": SOURCE_URL,
        "fetch_cookies_refreshed": False,
        "fetch_cache_hit": False,
    }
    preview.update(changes)
    return preview


@dataclass
class PreviewPipeline:
    preview: dict[str, object] = field(default_factory=_preview_mapping)
    error: BaseException | None = None
    calls: list[str] = field(default_factory=list)

    def preview_source_url(self, url: str) -> dict[str, object]:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.preview


def _service(db_path: Path, pipeline: PreviewPipeline, *, worker_id: str):
    return create_import_job_service(
        worker_id=worker_id,
        pipeline=pipeline,  # type: ignore[arg-type]
        db_path=db_path,
    )


def _enqueue_preview(service, *, deadline_at: str = FUTURE_DEADLINE):
    job = service.create_job(
        owner_user_id=OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[_preview_task()],
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=deadline_at,
        correlation_id="preview-correlation",
    )
    return service.enqueue_job(job.id, OWNER)


def _preview_task() -> dict[str, object]:
    return {
        "canonical_identity": f"69shuba:{SOURCE_URL}",
        "canonical_chapter_url": SOURCE_URL,
        "chapter_number": 0,
        "title": "Preview",
    }


def _run_worker(service, heartbeat_path: Path) -> int:
    return DurableImportWorker(service, heartbeat_path=heartbeat_path).run_once()


def _database_dump(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        return "\n".join(connection.iterdump())


def test_worker_claims_preview_and_publishes_typed_completed_result(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    api_pipeline = PreviewPipeline()
    api_service = _service(temp_db_path, api_pipeline, worker_id="api-process")
    job = _enqueue_preview(api_service)
    worker_pipeline = PreviewPipeline()
    worker_service = _service(temp_db_path, worker_pipeline, worker_id="preview-worker")

    assert _run_worker(worker_service, tmp_path / "preview-worker.heartbeat") == 1

    completed = worker_service.get_job(job.id, OWNER)
    task = worker_service.list_tasks(job.id, OWNER)[0]
    assert api_pipeline.calls == []
    assert worker_pipeline.calls == [SOURCE_URL]
    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result_state is BrowserResultState.COMPLETED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.payload is not None
    assert completed.result_snapshot.payload.title == "A novel"
    assert task.status is TaskStatus.SUCCEEDED
    assert [event.event_type for event in worker_service.list_events(job.id, OWNER)].count(
        "browser_result_published"
    ) == 1


def test_worker_cannot_claim_preview_before_task_creation_and_enqueue_marker(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    pipeline = PreviewPipeline()
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    repository = service.repository
    job = repository.create_job(
        owner_user_id=OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        total=1,
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=FUTURE_DEADLINE,
        correlation_id="partially-assembled-preview",
    )
    worker = DurableImportWorker(
        service,
        heartbeat_path=tmp_path / "assembly-race-worker.heartbeat",
        close_browser=lambda: None,
    )

    assert worker.run_once() == 0
    assert repository.get_job(job.id, OWNER).status is JobStatus.QUEUED

    task = repository.create_task(
        job_id=job.id,
        owner_user_id=OWNER,
        canonical_identity=f"69shuba:{SOURCE_URL}",
        canonical_chapter_url=SOURCE_URL,
        chapter_number=0,
        title="Preview",
    )
    assert worker.run_once() == 0
    assert repository.get_job(job.id, OWNER).status is JobStatus.QUEUED
    assert repository.list_tasks(job.id, OWNER)[0].status is TaskStatus.QUEUED
    assert pipeline.calls == []

    repository.enqueue_job(job.id, OWNER)
    assert worker.run_once() == 1

    completed = repository.get_job(job.id, OWNER)
    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result_state is BrowserResultState.COMPLETED
    assert repository.list_tasks(job.id, OWNER)[0].id == task.id
    assert pipeline.calls == [SOURCE_URL]


def test_worker_maps_verification_required_to_blocked_result(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    pipeline = PreviewPipeline(
        error=SourceAdapterError(
            "Complete source verification in the worker browser",
            code=FetchErrorCode.USER_VERIFICATION_REQUIRED,
            retryable=False,
            http_status=403,
        )
    )
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)

    assert _run_worker(service, tmp_path / "blocked-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    task = service.list_tasks(job.id, OWNER)[0]
    assert completed.result_state is BrowserResultState.BLOCKED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.error_code == "user_verification_required"
    assert completed.result_snapshot.error_message == "Complete source verification in the worker browser"
    assert task.status is TaskStatus.USER_VERIFICATION_REQUIRED


def test_worker_maps_safe_source_failure_without_persisting_exception_or_html(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    private_html = "PRIVATE PREVIEW HTML <script>credential</script>"
    pipeline = PreviewPipeline(
        error=SourceAdapterError(
            "The source is temporarily unavailable",
            code=FetchErrorCode.SOURCE_UNAVAILABLE,
            retryable=False,
            http_status=503,
            details={"html": private_html, "authorization": "Bearer provider-secret"},
        )
    )
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)

    assert _run_worker(service, tmp_path / "failed-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    assert completed.result_state is BrowserResultState.FAILED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.error_code == "source_unavailable"
    assert completed.result_snapshot.error_message == "The source is temporarily unavailable"
    database_dump = _database_dump(temp_db_path)
    assert private_html not in database_dump
    assert "provider-secret" not in database_dump


def test_cancel_after_preview_execution_before_publish_wins(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    class CancelBeforePublishRepository:
        def __init__(self, delegate: ImportJobRepository) -> None:
            self.delegate = delegate

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

        def publish_browser_result(self, job_id: str, owner_user_id: str, **kwargs):
            self.delegate.request_cancel(job_id, owner_user_id)
            return self.delegate.publish_browser_result(job_id, owner_user_id, **kwargs)

    init_db(temp_db_path)
    pipeline = PreviewPipeline()
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)
    service.repository = CancelBeforePublishRepository(service.repository)  # type: ignore[assignment]

    assert _run_worker(service, tmp_path / "cancel-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    events = service.list_events(job.id, OWNER)
    assert pipeline.calls == [SOURCE_URL]
    assert completed.status is JobStatus.CANCELLED
    assert completed.result_state is BrowserResultState.CANCELLED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.payload is None
    assert [event.event_type for event in events].count("browser_result_published") == 1


def test_crash_before_publish_recovers_lease_and_publishes_once(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    class CrashBeforePublishRepository:
        def __init__(self, delegate: ImportJobRepository) -> None:
            self.delegate = delegate

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

        def publish_browser_result(self, *_args, **_kwargs):
            raise SystemExit("simulated crash immediately before browser publication")

    init_db(temp_db_path)
    first_pipeline = PreviewPipeline()
    first_service = _service(temp_db_path, first_pipeline, worker_id="preview-worker-a")
    job = _enqueue_preview(first_service)
    first_service.repository = CrashBeforePublishRepository(first_service.repository)  # type: ignore[assignment]

    with pytest.raises(SystemExit, match="simulated crash"):
        _run_worker(first_service, tmp_path / "crash-worker.heartbeat")

    with sqlite3.connect(temp_db_path) as connection:
        connection.execute(
            "UPDATE chapter_tasks SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
            (job.id,),
        )
        connection.commit()

    second_pipeline = PreviewPipeline()
    second_service = _service(temp_db_path, second_pipeline, worker_id="preview-worker-b")
    assert _run_worker(second_service, tmp_path / "recovery-worker.heartbeat") == 1

    completed = second_service.get_job(job.id, OWNER)
    events = second_service.list_events(job.id, OWNER)
    assert first_pipeline.calls == [SOURCE_URL]
    assert second_pipeline.calls == [SOURCE_URL]
    assert completed.result_state is BrowserResultState.COMPLETED
    assert completed.result_snapshot is not None
    assert [event.event_type for event in events].count("browser_result_published") == 1
    assert second_service.list_tasks(job.id, OWNER)[0].attempts == 2


def test_expired_preview_never_launches_browser(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    pipeline = PreviewPipeline()
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service, deadline_at=EXPIRED_DEADLINE)

    assert _run_worker(service, tmp_path / "expired-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    assert pipeline.calls == []
    assert completed.result_state is BrowserResultState.TIMED_OUT


def test_deadline_expiring_between_stages_stops_preview_and_times_out(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    class ExpiringPipeline(PreviewPipeline):
        def preview_source_url(self, url: str) -> dict[str, object]:
            result = super().preview_source_url(url)
            with sqlite3.connect(temp_db_path) as connection:
                connection.execute("UPDATE import_jobs SET deadline_at = ?", (EXPIRED_DEADLINE,))
                connection.commit()
            return result

    init_db(temp_db_path)
    pipeline = ExpiringPipeline()
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)

    assert _run_worker(service, tmp_path / "mid-stage-timeout-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    assert pipeline.calls == [SOURCE_URL]
    assert completed.result_state is BrowserResultState.TIMED_OUT
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.payload is None


def test_unexpected_preview_error_is_sanitized_before_publication(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    private_exception = "preview crashed with PRIVATE_HTML and /tmp/provider-secret/cache.json"
    pipeline = PreviewPipeline(error=RuntimeError(private_exception))
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)

    assert _run_worker(service, tmp_path / "internal-error-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    assert completed.result_state is BrowserResultState.FAILED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.error_code == "internal_error"
    assert completed.result_snapshot.error_message == "Browser task failed"
    assert private_exception not in _database_dump(temp_db_path)


def test_preview_retry_is_rejected_without_reopening_terminal_snapshot(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    failed_pipeline = PreviewPipeline(
        error=SourceAdapterError(
            "Temporary source failure",
            code=FetchErrorCode.SOURCE_UNAVAILABLE,
            retryable=True,
            http_status=503,
        )
    )
    service = _service(temp_db_path, failed_pipeline, worker_id="preview-worker")
    service.retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0)
    failed_job = _enqueue_preview(service)
    assert _run_worker(service, tmp_path / "failed-preview-worker.heartbeat") == 1
    terminal_before_retry = service.get_job(failed_job.id, OWNER)
    task_before_retry = service.list_tasks(failed_job.id, OWNER)[0]

    with pytest.raises(InvalidImportJobTransition, match="preview jobs cannot be retried"):
        service.retry_failed_tasks(failed_job.id, OWNER)

    terminal_after_retry = service.get_job(failed_job.id, OWNER)
    task_after_retry = service.list_tasks(failed_job.id, OWNER)[0]
    later_job = _enqueue_preview(service)
    runnable = service.repository.list_runnable_jobs(limit=1)
    assert terminal_before_retry.result_snapshot is not None
    assert terminal_after_retry == terminal_before_retry
    assert task_after_retry == task_before_retry
    assert [job.id for job in runnable] == [later_job.id]


@pytest.mark.parametrize(
    ("correlation_id", "deadline_at"),
    [
        ("", FUTURE_DEADLINE),
        ("x" * 129, FUTURE_DEADLINE),
        ("preview-correlation", ""),
        ("preview-correlation", "2099-08-10T12:00:00"),
    ],
)
def test_preview_creation_rejects_invalid_terminal_contract_metadata(
    temp_db_path: Path,
    correlation_id: str,
    deadline_at: str,
) -> None:
    init_db(temp_db_path)
    service = _service(temp_db_path, PreviewPipeline(), worker_id="api-process")

    with pytest.raises(ValueError, match="invalid preview"):
        service.create_job(
            owner_user_id=OWNER,
            source="69shuba",
            source_url=SOURCE_URL,
            tasks=[_preview_task()],
            operation_kind=ImportOperationKind.PREVIEW,
            deadline_at=deadline_at,
            correlation_id=correlation_id,
        )

    assert service.repository.list_runnable_jobs(limit=1) == []


@pytest.mark.parametrize(
    ("safe_message", "http_status", "expected_message", "expected_http_status"),
    [
        ("x" * 2_001, 503, "x" * 2_000, 503),
        ("Safe source failure", 200, "Safe source failure", None),
    ],
)
def test_worker_bounds_invalid_source_error_metadata_into_failed_result(
    temp_db_path: Path,
    tmp_path: Path,
    safe_message: str,
    http_status: int,
    expected_message: str,
    expected_http_status: int | None,
) -> None:
    init_db(temp_db_path)
    pipeline = PreviewPipeline(
        error=SourceAdapterError(
            safe_message,
            code=FetchErrorCode.SOURCE_UNAVAILABLE,
            retryable=False,
            http_status=http_status,
        )
    )
    service = _service(temp_db_path, pipeline, worker_id="preview-worker")
    job = _enqueue_preview(service)

    assert _run_worker(service, tmp_path / "bounded-error-worker.heartbeat") == 1

    completed = service.get_job(job.id, OWNER)
    task = service.list_tasks(job.id, OWNER)[0]
    assert completed.result_state is BrowserResultState.FAILED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.error_message == expected_message
    assert completed.result_snapshot.http_status == expected_http_status
    assert task.status is TaskStatus.FAILED
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
