from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import threading
import time

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, JobStatus, TaskStage
from app.services.import_job_runtime import RetryPolicy
from app.services.import_job_service import ImportJobService, TaskImportOutcome


@dataclass
class _Pipeline:
    imported: set[str] = field(default_factory=set)
    created_operations: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    crash_once: bool = False

    def run_stage(self, stage, task, *, cancel_check):
        assert not cancel_check()
        if stage is TaskStage.IMPORTING:
            with self.lock:
                if task.canonical_identity in self.imported:
                    operation = "skipped_duplicate"
                else:
                    self.imported.add(task.canonical_identity)
                    self.created_operations += 1
                    operation = "created"
            if self.crash_once:
                self.crash_once = False
                raise SystemExit("simulated worker crash")
            return TaskImportOutcome(
                text_length=32,
                content_hash=f"hash-{task.chapter_number}",
                fetch_method="direct_http",
                elapsed_ms=1,
                operation=operation,
            )
        return None


def _service(db_path: Path, pipeline: _Pipeline, *, worker_id: str) -> ImportJobService:
    return ImportJobService(
        ImportJobRepository(db_path),
        worker_id=worker_id,
        pipeline=pipeline,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0),
        sleep=lambda _seconds: None,
        random_value=lambda: 0.5,
    )


def _enqueue_job(service: ImportJobService, *, chapters: int = 1):
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        tasks=[
            {
                "canonical_identity": f"69shuba:chapter-{number}",
                "canonical_chapter_url": f"https://www.69shuba.com/book/123/chapter/{number}",
                "chapter_number": number,
                "title": f"Chương {number}",
            }
            for number in range(1, chapters + 1)
        ],
    )
    return service.enqueue_job(job.id, "operator-a")


def test_separate_worker_processes_durable_job_created_before_api_stops(temp_db_path: Path, tmp_path: Path) -> None:
    from app.import_worker import DurableImportWorker, worker_healthcheck

    init_db(temp_db_path)
    pipeline = _Pipeline()
    api_service = _service(temp_db_path, pipeline, worker_id="api-process")
    job = _enqueue_job(api_service)

    worker_service = _service(temp_db_path, pipeline, worker_id="worker-process")
    heartbeat_path = tmp_path / "import-worker.heartbeat"
    worker = DurableImportWorker(worker_service, heartbeat_path=heartbeat_path)

    assert worker.run_once() == 1
    assert worker_service.get_job(job.id, "operator-a").status is JobStatus.SUCCEEDED
    assert pipeline.imported == {"69shuba:chapter-1"}
    assert worker_healthcheck(temp_db_path, heartbeat_path=heartbeat_path)


def test_restarted_worker_recovers_expired_lease_without_duplicate_import(temp_db_path: Path, tmp_path: Path) -> None:
    from app.import_worker import DurableImportWorker

    init_db(temp_db_path)
    pipeline = _Pipeline(crash_once=True)
    first_service = _service(temp_db_path, pipeline, worker_id="worker-a")
    job = _enqueue_job(first_service)
    first_worker = DurableImportWorker(first_service, heartbeat_path=tmp_path / "worker-a.heartbeat")

    try:
        first_worker.run_once()
    except SystemExit:
        pass

    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("UPDATE chapter_tasks SET lease_expires_at = '2000-01-01T00:00:00+00:00'")
        conn.commit()

    second_service = _service(temp_db_path, pipeline, worker_id="worker-b")
    second_worker = DurableImportWorker(second_service, heartbeat_path=tmp_path / "worker-b.heartbeat")

    assert second_worker.run_once() == 1
    assert second_service.get_job(job.id, "operator-a").status is JobStatus.SUCCEEDED
    assert pipeline.imported == {"69shuba:chapter-1"}
    assert pipeline.created_operations == 1


def test_restarted_worker_requeues_due_retry_only_after_its_lease_expires(temp_db_path: Path, tmp_path: Path) -> None:
    from app.import_worker import DurableImportWorker

    init_db(temp_db_path)
    pipeline = _Pipeline()
    service = _service(temp_db_path, pipeline, worker_id="worker-a")
    job = _enqueue_job(service)
    task = service.repository.claim_next_task(
        job.id,
        "operator-a",
        worker_id="worker-a",
    )
    assert task is not None
    service.repository.schedule_task_retry(
        task.id,
        "operator-a",
        lease_token=task.lease_token,
        next_attempt_at="2000-01-01T00:00:00+00:00",
        error_code="connect_timeout",
        error_message="temporary source failure",
    )
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("UPDATE chapter_tasks SET lease_expires_at = '2000-01-01T00:00:00+00:00'")
        conn.commit()

    worker = DurableImportWorker(service, heartbeat_path=tmp_path / "retry-worker.heartbeat")

    assert worker.run_once() == 1
    assert service.get_job(job.id, "operator-a").status is JobStatus.SUCCEEDED


def test_two_worker_processes_claim_one_task_without_duplicate_import(temp_db_path: Path, tmp_path: Path) -> None:
    from app.import_worker import DurableImportWorker

    init_db(temp_db_path)
    pipeline = _Pipeline()
    first_service = _service(temp_db_path, pipeline, worker_id="worker-a")
    job = _enqueue_job(first_service)
    second_service = _service(temp_db_path, pipeline, worker_id="worker-b")
    first_worker = DurableImportWorker(first_service, heartbeat_path=tmp_path / "worker-a.heartbeat")
    second_worker = DurableImportWorker(second_service, heartbeat_path=tmp_path / "worker-b.heartbeat")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda worker: worker.run_once(), (first_worker, second_worker)))

    assert first_service.get_job(job.id, "operator-a").status is JobStatus.SUCCEEDED
    assert pipeline.imported == {"69shuba:chapter-1"}


def test_worker_healthcheck_rejects_missing_or_stale_heartbeat(temp_db_path: Path, tmp_path: Path) -> None:
    from app.import_worker import WorkerHeartbeat, worker_healthcheck

    init_db(temp_db_path)
    heartbeat_path = tmp_path / "import-worker.heartbeat"

    assert not worker_healthcheck(temp_db_path, heartbeat_path=heartbeat_path, now=100, max_age_seconds=30)
    WorkerHeartbeat(heartbeat_path, clock=lambda: 100).touch()
    assert worker_healthcheck(temp_db_path, heartbeat_path=heartbeat_path, now=120, max_age_seconds=30)
    assert not worker_healthcheck(temp_db_path, heartbeat_path=heartbeat_path, now=131, max_age_seconds=30)


def test_run_forever_keeps_heartbeat_fresh_during_blocking_job_and_joins_ticker(
    tmp_path: Path,
) -> None:
    from app.import_worker import DurableImportWorker

    class RecordingHeartbeat:
        def __init__(self) -> None:
            self._condition = threading.Condition()
            self.touch_count = 0

        def touch(self) -> None:
            with self._condition:
                self.touch_count += 1
                self._condition.notify_all()

        def wait_for_touches(self, expected: int, timeout: float) -> bool:
            deadline = time.monotonic() + timeout
            with self._condition:
                while self.touch_count < expected:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._condition.wait(remaining)
                return True

    entered_job = threading.Event()
    release_job = threading.Event()
    stop_event = threading.Event()
    heartbeat = RecordingHeartbeat()
    worker = DurableImportWorker(
        object(),  # type: ignore[arg-type]
        heartbeat_path=tmp_path / "ticker.heartbeat",
        heartbeat_interval_seconds=0.02,
        close_browser=lambda: None,
    )
    worker.heartbeat = heartbeat  # type: ignore[assignment]

    def blocking_run_once() -> int:
        entered_job.set()
        assert release_job.wait(1)
        stop_event.set()
        return 1

    worker.run_once = blocking_run_once  # type: ignore[method-assign]
    runner = threading.Thread(
        target=worker.run_forever,
        kwargs={"stop_event": stop_event},
        name="test-import-worker-runner",
    )
    runner.start()

    assert entered_job.wait(1)
    assert heartbeat.wait_for_touches(3, 0.5), (
        "heartbeat ticker did not remain active while run_once was blocked"
    )
    release_job.set()
    runner.join(1)
    assert not runner.is_alive()

    touches_after_join = heartbeat.touch_count
    time.sleep(0.06)
    assert heartbeat.touch_count == touches_after_join
    assert not any(
        thread.name.startswith("import-worker-heartbeat-") and thread.is_alive()
        for thread in threading.enumerate()
    )
