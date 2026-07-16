from __future__ import annotations

from pathlib import Path

import pytest

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, TaskStage
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError, SourceChapterContent
from app.observability import CircuitBreakerConfig, Observability
from app.services.import_job_runtime import RetryPolicy
from app.services.import_job_quotas import ImportJobQuotaError, ImportJobQuotaPolicy
from app.services.import_job_service import ImportJobService, TaskImportOutcome
from app.services.source_import_task_pipeline import SourceImportTaskPipeline


class _NoopPipeline:
    def run_stage(self, stage, task, *, cancel_check):
        del stage, task, cancel_check
        return None


def _task(number: int = 1) -> dict[str, object]:
    return {
        "canonical_identity": f"69shuba:chapter-{number}",
        "canonical_chapter_url": f"https://www.69shuba.com/book/1/chapter/{number}",
        "chapter_number": number,
        "title": f"Chương {number}",
    }


def _service(db_path: Path, *, policy: ImportJobQuotaPolicy) -> ImportJobService:
    init_db(db_path)
    return ImportJobService(
        ImportJobRepository(db_path),
        worker_id="observability-test",
        pipeline=_NoopPipeline(),
        quota_policy=policy,
    )


def test_service_rejects_chapter_and_active_job_quotas(temp_db_path: Path) -> None:
    service = _service(
        temp_db_path,
        policy=ImportJobQuotaPolicy(max_chapters_per_job=1, max_active_jobs_per_owner=1),
    )

    with pytest.raises(ImportJobQuotaError, match="chapter_quota_exceeded"):
        service.create_job(
            owner_user_id="operator-a",
            source="69shuba",
            source_url="https://www.69shuba.com/book/1",
            tasks=[_task(1), _task(2)],
        )

    service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[_task(1)],
    )
    with pytest.raises(ImportJobQuotaError, match="active_job_quota_exceeded"):
        service.create_job(
            owner_user_id="operator-a",
            source="69shuba",
            source_url="https://www.69shuba.com/book/2",
            tasks=[_task(2)],
        )


def test_source_task_pipeline_enforces_byte_quota_and_does_not_persist_content(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    job = repository.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
    )
    task = repository.create_task(
        job_id=job.id,
        owner_user_id="operator-a",
        canonical_identity="69shuba:chapter-1",
        canonical_chapter_url="https://www.69shuba.com/book/1/chapter/1",
        chapter_number=1,
        title="Chương 1",
    )

    class FetchOnlyPipeline:
        def fetch_source_chapter(self, url: str) -> SourceChapterContent:
            return SourceChapterContent(
                adapter_id="69shuba",
                source="www.69shuba.com",
                source_url=url,
                chapter_number=1,
                title="Chương 1",
                text="nội dung không được lưu vào metrics",
                fetch_method="direct_http",
                fetch_bytes_received=128,
            )

    pipeline = SourceImportTaskPipeline(repository, FetchOnlyPipeline(), max_chapter_bytes=64)

    with pytest.raises(SourceAdapterError) as raised:
        pipeline.run_stage(TaskStage.FETCHING, task, cancel_check=lambda: False)

    assert raised.value.code is FetchErrorCode.CONTENT_INVALID
    assert "nội dung không được lưu" not in str(raised.value)


def test_source_task_pipeline_circuit_breaker_blocks_fetch_before_network(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    job = repository.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
    )
    task = repository.create_task(
        job_id=job.id,
        owner_user_id="operator-a",
        canonical_identity="69shuba:chapter-1",
        canonical_chapter_url="https://www.69shuba.com/book/1/chapter/1",
        chapter_number=1,
        title="Chương 1",
    )
    observability = Observability(circuit_config=CircuitBreakerConfig(failure_threshold=1))
    observability.circuit_breaker.record_failure("69shuba", "direct_http", "connect_timeout")
    calls = 0

    class Pipeline:
        def fetch_source_chapter(self, url: str) -> SourceChapterContent:
            nonlocal calls
            calls += 1
            raise AssertionError(url)

    pipeline = SourceImportTaskPipeline(repository, Pipeline(), observability=observability)

    with pytest.raises(SourceAdapterError) as raised:
        pipeline.run_stage(TaskStage.FETCHING, task, cancel_check=lambda: False)

    assert raised.value.code is FetchErrorCode.SOURCE_UNAVAILABLE
    assert calls == 0


def test_worker_records_job_task_and_retry_metrics(temp_db_path: Path) -> None:
    class RetryThenImport:
        failed = False

        def run_stage(self, stage, task, *, cancel_check):
            assert not cancel_check()
            if stage is TaskStage.FETCHING and not self.failed:
                self.failed = True
                raise SourceAdapterError(
                    "temporary timeout",
                    code=FetchErrorCode.CONNECT_TIMEOUT,
                    retryable=True,
                )
            if stage is TaskStage.IMPORTING:
                return TaskImportOutcome(
                    text_length=42,
                    content_hash="safe-hash",
                    fetch_method="direct_http",
                    elapsed_ms=7,
                    operation="updated",
                )
            return None

    observability = Observability()
    service = ImportJobService(
        ImportJobRepository(temp_db_path),
        worker_id="observability-test",
        pipeline=RetryThenImport(),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
        quota_policy=ImportJobQuotaPolicy(),
        observability=observability,
        sleep=lambda _seconds: None,
        random_value=lambda: 0.5,
    )
    init_db(temp_db_path)
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[_task(1)],
    )
    service.enqueue_job(job.id, "operator-a")
    completed = service.run_job(job.id, "operator-a")

    assert completed.status.value == "succeeded"
    snapshot = observability.snapshot()["metrics"]
    counter_names = {entry["name"] for entry in snapshot["counters"]}
    assert {"import_jobs_total", "import_tasks_total", "import_task_retries_total", "import_operations_total"}.issubset(counter_names)
    gauges = {entry["name"]: entry["value"] for entry in snapshot["gauges"]}
    assert gauges["active_jobs"] == 0
    assert gauges["queue_depth"] == 0


def test_worker_fails_pending_tasks_when_total_duration_limit_is_exceeded(temp_db_path: Path) -> None:
    service = _service(
        temp_db_path,
        policy=ImportJobQuotaPolicy(max_job_duration_seconds=1),
    )
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[_task(1)],
    )
    service.enqueue_job(job.id, "operator-a")
    from app.database.connection import get_connection

    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE import_jobs SET started_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job.id,))
        conn.commit()

    completed = service.run_job(job.id, "operator-a")
    task = service.list_tasks(job.id, "operator-a")[0]

    assert completed.status.value == "failed"
    assert task.status.value == "failed"
    assert task.error_code == "job_duration_exceeded"
