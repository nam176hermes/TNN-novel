from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import sqlite3

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, JobStatus, TaskStage, TaskStatus
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.services.import_job_service import ImportJobService, TaskImportOutcome


@dataclass
class SuccessfulPipeline:
    stages: list[TaskStage]

    def run_stage(self, stage, task, *, cancel_check):
        self.stages.append(stage)
        assert not cancel_check()
        if stage is TaskStage.IMPORTING:
            return TaskImportOutcome(
                text_length=28,
                content_hash="chapter-hash",
                fetch_method="direct_http",
                elapsed_ms=12,
            )
        return None


def _task(identity: str, number: int) -> dict[str, object]:
    return {
        "canonical_identity": identity,
        "canonical_chapter_url": f"https://www.69shuba.com/chapter/{number}",
        "chapter_number": number,
        "title": f"Chương {number}",
    }


def _service(temp_db_path, pipeline, *, worker_id: str = "worker-a", lease_seconds: int = 120):
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    return repository, ImportJobService(
        repository,
        worker_id=worker_id,
        pipeline=pipeline,
        lease_seconds=lease_seconds,
    )


def _create_job(service, *, tasks: list[dict[str, object]]):
    return service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        tasks=tasks,
    )


def test_worker_runs_enqueued_job_sequentially_to_success(temp_db_path) -> None:
    repository, service = _service(temp_db_path, SuccessfulPipeline([]))
    job = _create_job(service, tasks=[_task("69shuba:chapter-1", 1)])

    service.enqueue_job(job.id, "operator-a")
    completed = service.run_job(job.id, "operator-a")

    tasks = repository.list_tasks(job.id, "operator-a")
    assert completed.status.value == "succeeded"
    assert [task.stage for task in tasks] == [TaskStage.SUCCEEDED]
    assert [event.event_type for event in repository.list_events(job.id, "operator-a")][-1] == "job_transitioned"
    stage_events = [
        event.payload.get("stage")
        for event in repository.list_events(job.id, "operator-a")
        if event.event_type == "task_transitioned"
    ]
    assert stage_events == ["fetching", "parsing", "validating", "importing", "succeeded"]


def test_worker_finishes_partially_succeeded_when_one_task_fails(temp_db_path) -> None:
    class PartialPipeline(SuccessfulPipeline):
        def run_stage(self, stage, task, *, cancel_check):
            if task.chapter_number == 2 and stage is TaskStage.PARSING:
                raise SourceAdapterError(
                    "Source unavailable",
                    code=FetchErrorCode.SOURCE_UNAVAILABLE,
                    retryable=True,
                )
            return super().run_stage(stage, task, cancel_check=cancel_check)

    repository, service = _service(temp_db_path, PartialPipeline([]))
    job = _create_job(service, tasks=[_task("chapter-1", 1), _task("chapter-2", 2)])
    service.enqueue_job(job.id, "operator-a")

    completed = service.run_job(job.id, "operator-a")

    assert completed.status is JobStatus.PARTIALLY_SUCCEEDED
    assert [task.status for task in repository.list_tasks(job.id, "operator-a")] == [
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
    ]


def test_cancel_before_run_cancels_queued_tasks_idempotently(temp_db_path) -> None:
    repository, service = _service(temp_db_path, SuccessfulPipeline([]))
    job = _create_job(service, tasks=[_task("chapter-1", 1), _task("chapter-2", 2)])
    service.enqueue_job(job.id, "operator-a")

    first = service.request_cancel(job.id, "operator-a")
    second = service.request_cancel(job.id, "operator-a")

    assert first.status is JobStatus.CANCELLED
    assert second.status is JobStatus.CANCELLED
    assert {task.status for task in repository.list_tasks(job.id, "operator-a")} == {TaskStatus.CANCELLED}


def test_cancel_between_stages_stops_claimed_task_and_remaining_queue(temp_db_path) -> None:
    class CancellingPipeline(SuccessfulPipeline):
        service: ImportJobService

        def run_stage(self, stage, task, *, cancel_check):
            if stage is TaskStage.PARSING:
                self.service.request_cancel(task.job_id, "operator-a")
                return None
            return super().run_stage(stage, task, cancel_check=cancel_check)

    pipeline = CancellingPipeline([])
    repository, service = _service(temp_db_path, pipeline)
    pipeline.service = service
    job = _create_job(service, tasks=[_task("chapter-1", 1), _task("chapter-2", 2)])
    service.enqueue_job(job.id, "operator-a")

    completed = service.run_job(job.id, "operator-a")

    assert completed.status is JobStatus.CANCELLED
    assert {task.status for task in repository.list_tasks(job.id, "operator-a")} == {TaskStatus.CANCELLED}


def test_expired_lease_recovers_crashed_task_without_duplicate_fake_import(temp_db_path) -> None:
    class IdempotentCrashPipeline(SuccessfulPipeline):
        crash_once = True
        imported: set[str]

        def __init__(self):
            super().__init__([])
            self.imported = set()

        def run_stage(self, stage, task, *, cancel_check):
            if stage is TaskStage.IMPORTING:
                self.imported.add(task.canonical_identity)
                if self.crash_once:
                    self.crash_once = False
                    raise SystemExit("simulated process crash")
            return super().run_stage(stage, task, cancel_check=cancel_check)

    pipeline = IdempotentCrashPipeline()
    repository, service = _service(temp_db_path, pipeline, lease_seconds=1)
    job = _create_job(service, tasks=[_task("chapter-1", 1)])
    service.enqueue_job(job.id, "operator-a")

    try:
        service.run_job(job.id, "operator-a")
    except SystemExit:
        pass
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("UPDATE chapter_tasks SET lease_expires_at = '2000-01-01T00:00:00+00:00'")
        conn.commit()

    assert service.recover_interrupted_jobs() == [job.id]
    completed = service.run_job(job.id, "operator-a")

    assert completed.status is JobStatus.SUCCEEDED
    assert pipeline.imported == {"chapter-1"}
    assert repository.list_tasks(job.id, "operator-a")[0].attempts == 2
    assert {event.event_type for event in repository.list_events(job.id, "operator-a")} >= {
        "task_recovered",
        "job_recovered",
    }


def test_two_workers_atomically_claim_only_one_task(temp_db_path) -> None:
    repository, service = _service(temp_db_path, SuccessfulPipeline([]))
    job = _create_job(service, tasks=[_task("chapter-1", 1)])
    service.enqueue_job(job.id, "operator-a")

    def claim(worker_id: str):
        return ImportJobRepository(temp_db_path).claim_next_task(
            job.id,
            "operator-a",
            worker_id=worker_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ["worker-a", "worker-b"]))

    assert sum(claim is not None for claim in claims) == 1
    assert repository.list_tasks(job.id, "operator-a")[0].status is TaskStatus.RUNNING


def test_retry_failed_tasks_resets_only_retryable_failures(temp_db_path) -> None:
    class RetryPipeline(SuccessfulPipeline):
        failed_once = True

        def run_stage(self, stage, task, *, cancel_check):
            if task.chapter_number == 2 and stage is TaskStage.FETCHING and self.failed_once:
                self.failed_once = False
                raise SourceAdapterError(
                    "Temporary source error",
                    code=FetchErrorCode.SOURCE_UNAVAILABLE,
                    retryable=True,
                )
            return super().run_stage(stage, task, cancel_check=cancel_check)

    repository, service = _service(temp_db_path, RetryPipeline([]))
    job = _create_job(service, tasks=[_task("chapter-1", 1), _task("chapter-2", 2)])
    service.enqueue_job(job.id, "operator-a")
    assert service.run_job(job.id, "operator-a").status is JobStatus.PARTIALLY_SUCCEEDED

    retried = service.retry_failed_tasks(job.id, "operator-a")
    completed = service.run_job(job.id, "operator-a")

    assert [task.chapter_number for task in retried] == [2]
    assert completed.status is JobStatus.SUCCEEDED
    assert [task.attempts for task in repository.list_tasks(job.id, "operator-a")] == [1, 2]
