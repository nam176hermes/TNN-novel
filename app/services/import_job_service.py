"""Sequential durable worker core for P06 import jobs.

The database is the scheduling source of truth.  This module deliberately has
no HTTP routes, background thread, automatic retry scheduler, or concurrency
greater than one task per ``run_job`` invocation.  A later integration can
provide a real source/import pipeline through the small injected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
import random
import time
from contextlib import contextmanager
from threading import Condition
from urllib.parse import urlparse

from app.database.import_jobs import (
    ChapterTask,
    ImportJob,
    ImportJobRepository,
    JobStatus,
    TaskStage,
    TaskStatus,
)
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.services.import_job_runtime import BoundedTaskRunner, RetryPolicy


class _OrderedImportGate:
    def __init__(self, tasks: list[ChapterTask]) -> None:
        self._remaining = [task.id for task in sorted(tasks, key=lambda item: (item.chapter_number, item.id))]
        self._condition = Condition()

    @contextmanager
    def turn(self, task_id: int):
        with self._condition:
            while task_id in self._remaining and self._remaining[0] != task_id:
                self._condition.wait()
        try:
            yield
        finally:
            self.finish(task_id)

    def finish(self, task_id: int) -> None:
        with self._condition:
            if task_id in self._remaining:
                self._remaining.remove(task_id)
                self._condition.notify_all()


@dataclass(frozen=True)
class TaskImportOutcome:
    """Safe metadata returned by the final importing pipeline stage."""

    book_id: int | None = None
    chapter_id: int | None = None
    text_length: int = 0
    content_hash: str = ""
    fetch_method: str = ""
    elapsed_ms: int = 0


class ImportTaskPipeline(Protocol):
    """A source/import implementation supplied by a future integration."""

    def run_stage(
        self,
        stage: TaskStage,
        task: ChapterTask,
        *,
        cancel_check: Callable[[], bool],
    ) -> TaskImportOutcome | None: ...


class ImportJobService:
    """Service operations and a single-task-at-a-time durable worker."""

    def __init__(
        self,
        repository: ImportJobRepository,
        *,
        worker_id: str,
        pipeline: ImportTaskPipeline,
        lease_seconds: int = 120,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
        bounded_runner: BoundedTaskRunner | None = None,
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.pipeline = pipeline
        self.lease_seconds = max(1, lease_seconds)
        self.retry_policy = retry_policy or RetryPolicy()
        self.clock = clock
        self.sleep = sleep
        self.random_value = random_value
        self.bounded_runner = bounded_runner or BoundedTaskRunner()

    @classmethod
    def for_database(
        cls,
        db_path: Path,
        *,
        worker_id: str,
        pipeline: ImportTaskPipeline,
        lease_seconds: int = 120,
    ) -> "ImportJobService":
        return cls(
            ImportJobRepository(db_path),
            worker_id=worker_id,
            pipeline=pipeline,
            lease_seconds=lease_seconds,
        )

    def create_job(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_url: str,
        tasks: list[Mapping[str, Any]],
        book_id: int | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> ImportJob:
        job = self.repository.create_job(
            owner_user_id=owner_user_id,
            source=source,
            source_url=source_url,
            total=len(tasks),
            book_id=book_id,
            config_snapshot=config_snapshot,
        )
        for task in tasks:
            self.repository.create_task(
                job_id=job.id,
                owner_user_id=owner_user_id,
                canonical_identity=str(task["canonical_identity"]),
                canonical_chapter_url=str(task["canonical_chapter_url"]),
                chapter_number=int(task.get("chapter_number") or 0),
                title=str(task.get("title") or ""),
                book_id=book_id,
            )
        return self.get_job(job.id, owner_user_id)

    def enqueue_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        return self.repository.enqueue_job(job_id, owner_user_id)

    def get_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        job = self.repository.get_job(job_id, owner_user_id)
        if job is None:
            raise LookupError("import job not found")
        return job

    def request_cancel(self, job_id: str, owner_user_id: str) -> ImportJob:
        self.repository.request_cancel(job_id, owner_user_id)
        self.repository.cancel_queued_tasks(job_id, owner_user_id)
        return self._finalize_job(job_id, owner_user_id)

    def retry_failed_tasks(self, job_id: str, owner_user_id: str) -> list[ChapterTask]:
        """Explicit retry only for failed tasks marked retryable by the pipeline."""
        retried: list[ChapterTask] = []
        for task in self.repository.list_tasks(job_id, owner_user_id):
            if task.status is TaskStatus.FAILED and task.retryable:
                retried.append(self.repository.retry_task(task.id, owner_user_id))
        if retried:
            self.repository.restart_job_for_retry(job_id, owner_user_id)
        return retried

    def recover_interrupted_jobs(self) -> list[str]:
        """Recover only expired task leases; it never reruns a task itself."""
        recovered = self.repository.recover_expired_tasks()
        return sorted({job_id for job_id, _owner_user_id, _task_id in recovered})

    def run_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        """Run a bounded fetch batch and serialize imports by chapter order."""
        job = self.get_job(job_id, owner_user_id)
        if job.cancel_requested_at:
            self.repository.cancel_queued_tasks(job_id, owner_user_id)
            return self._finalize_job(job_id, owner_user_id)
        if job.status is JobStatus.QUEUED:
            self.repository.transition_job(job_id, owner_user_id, JobStatus.RUNNING)
        elif job.status is not JobStatus.RUNNING:
            return job

        claimed: list[ChapterTask] = []
        while len(claimed) < self.bounded_runner.max_queue_size:
            if self.repository.is_cancel_requested(job_id, owner_user_id):
                self.repository.cancel_queued_tasks(job_id, owner_user_id)
                break
            task = self.repository.claim_next_task(
                job_id,
                owner_user_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if task is None:
                break
            claimed.append(task)
        gate = _OrderedImportGate(claimed)
        self.bounded_runner.run([
            (
                task.fetch_method or "direct_http",
                urlparse(task.canonical_chapter_url).hostname or "",
                lambda task=task: self._run_claimed_task(
                    task,
                    owner_user_id,
                    stages=(TaskStage.FETCHING, TaskStage.PARSING, TaskStage.VALIDATING),
                    finalize=False,
                ),
                lambda task=task: self._run_import_if_active(task, owner_user_id, gate),
            )
            for task in claimed
        ])
        return self._finalize_job(job_id, owner_user_id)

    def _run_claimed_task(
        self,
        task: ChapterTask,
        owner_user_id: str,
        *,
        import_gate: _OrderedImportGate | None = None,
        stages: tuple[TaskStage, ...] = (
            TaskStage.FETCHING,
            TaskStage.PARSING,
            TaskStage.VALIDATING,
            TaskStage.IMPORTING,
        ),
        finalize: bool = True,
    ) -> None:
        outcome: TaskImportOutcome | None = None
        try:
            for stage in stages:
                if self._cancel_claimed_task(task, owner_user_id):
                    return
                self.repository.renew_task_lease(
                    task.id,
                    owner_user_id,
                    lease_token=task.lease_token,
                    lease_seconds=self.lease_seconds,
                )
                self.repository.transition_task(
                    task.id,
                    owner_user_id,
                    status=TaskStatus.RUNNING,
                    stage=stage,
                    lease_token=task.lease_token,
                )
                started = self.clock()
                retry_attempt = 1
                while True:
                    try:
                        if stage is TaskStage.IMPORTING and import_gate is not None:
                            with import_gate.turn(task.id):
                                result = self.pipeline.run_stage(stage, task, cancel_check=lambda: self.repository.is_cancel_requested(task.job_id, owner_user_id))
                        else:
                            result = self.pipeline.run_stage(stage, task, cancel_check=lambda: self.repository.is_cancel_requested(task.job_id, owner_user_id))
                        break
                    except SourceAdapterError as exc:
                        elapsed = self.clock() - started
                        if not self.retry_policy.should_retry(exc, attempt=retry_attempt, elapsed_seconds=elapsed):
                            raise
                        delay = self.retry_policy.delay_seconds(
                            attempt=retry_attempt,
                            random_value=self.random_value,
                            retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                        )
                        next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                        self.repository.schedule_task_retry(
                            task.id,
                            owner_user_id,
                            lease_token=task.lease_token,
                            next_attempt_at=next_attempt,
                            error_code=exc.code.value,
                            error_message=exc.safe_message,
                        )
                        if self.repository.is_cancel_requested(task.job_id, owner_user_id):
                            self._cancel_claimed_task(task, owner_user_id)
                            return
                        self.sleep(delay)
                        if self.repository.is_cancel_requested(task.job_id, owner_user_id):
                            self._cancel_claimed_task(task, owner_user_id)
                            return
                        self.repository.transition_task(
                            task.id,
                            owner_user_id,
                            status=TaskStatus.RUNNING,
                            stage=stage,
                            lease_token=task.lease_token,
                        )
                        retry_attempt += 1
                if stage is TaskStage.IMPORTING and result is not None:
                    outcome = result
                if self._cancel_claimed_task(task, owner_user_id):
                    return
            if finalize:
                outcome = outcome or TaskImportOutcome()
                self.repository.transition_task(
                    task.id,
                    owner_user_id,
                    status=TaskStatus.SUCCEEDED,
                    stage=TaskStage.SUCCEEDED,
                    text_length=outcome.text_length,
                    content_hash=outcome.content_hash,
                    fetch_method=outcome.fetch_method,
                    elapsed_ms=outcome.elapsed_ms,
                    book_id=outcome.book_id,
                    chapter_id=outcome.chapter_id,
                    lease_token=task.lease_token,
                )
        except SourceAdapterError as exc:
            status = (
                TaskStatus.USER_VERIFICATION_REQUIRED
                if exc.code is FetchErrorCode.USER_VERIFICATION_REQUIRED
                else TaskStatus.FAILED
            )
            stage = (
                TaskStage.USER_VERIFICATION_REQUIRED
                if status is TaskStatus.USER_VERIFICATION_REQUIRED
                else TaskStage.FAILED
            )
            self.repository.transition_task(
                task.id,
                owner_user_id,
                status=status,
                stage=stage,
                error_code=exc.code.value,
                error_message=exc.safe_message,
                retryable=bool(exc.retryable),
                lease_token=task.lease_token,
            )
        except Exception:
            self.repository.transition_task(
                task.id,
                owner_user_id,
                status=TaskStatus.FAILED,
                stage=TaskStage.FAILED,
                error_code=FetchErrorCode.INTERNAL_ERROR.value,
                error_message="Import task failed",
                retryable=False,
                lease_token=task.lease_token,
            )
        finally:
            if import_gate is not None:
                import_gate.finish(task.id)

    def _run_import_if_active(
        self,
        task: ChapterTask,
        owner_user_id: str,
        import_gate: _OrderedImportGate,
    ) -> None:
        current = next(
            (item for item in self.repository.list_tasks(task.job_id, owner_user_id) if item.id == task.id),
            None,
        )
        if current is None or current.status is not TaskStatus.RUNNING:
            import_gate.finish(task.id)
            return
        self._run_claimed_task(
            task,
            owner_user_id,
            import_gate=import_gate,
            stages=(TaskStage.IMPORTING,),
            finalize=True,
        )

    def _cancel_claimed_task(self, task: ChapterTask, owner_user_id: str) -> bool:
        if not self.repository.is_cancel_requested(task.job_id, owner_user_id):
            return False
        self.repository.transition_task(
            task.id,
            owner_user_id,
            status=TaskStatus.CANCELLED,
            stage=TaskStage.CANCELLED,
            error_code=FetchErrorCode.CANCELLED.value,
            lease_token=task.lease_token,
        )
        return True

    def _finalize_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        job = self.get_job(job_id, owner_user_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return job
        if job.cancel_requested_at and job.running_count == 0 and job.queued_count == 0:
            return self.repository.transition_job(job_id, owner_user_id, JobStatus.CANCELLED)
        if job.running_count or job.queued_count:
            return job
        if job.total == 0 or job.succeeded_count == job.total:
            return self.repository.transition_job(job_id, owner_user_id, JobStatus.SUCCEEDED)
        if job.succeeded_count:
            return self.repository.transition_job(job_id, owner_user_id, JobStatus.PARTIALLY_SUCCEEDED)
        return self.repository.transition_job(job_id, owner_user_id, JobStatus.FAILED)
