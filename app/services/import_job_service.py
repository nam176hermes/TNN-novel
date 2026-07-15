"""Sequential durable worker core for P06 import jobs.

The database is the scheduling source of truth.  This module deliberately has
no HTTP routes, background thread, automatic retry scheduler, or concurrency
greater than one task per ``run_job`` invocation.  A later integration can
provide a real source/import pipeline through the small injected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from app.database.import_jobs import (
    ChapterTask,
    ImportJob,
    ImportJobRepository,
    JobStatus,
    TaskStage,
    TaskStatus,
)
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError


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
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.pipeline = pipeline
        self.lease_seconds = max(1, lease_seconds)

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
        """Run all currently queued tasks sequentially (concurrency = 1)."""
        job = self.get_job(job_id, owner_user_id)
        if job.cancel_requested_at:
            self.repository.cancel_queued_tasks(job_id, owner_user_id)
            return self._finalize_job(job_id, owner_user_id)
        if job.status is JobStatus.QUEUED:
            self.repository.transition_job(job_id, owner_user_id, JobStatus.RUNNING)
        elif job.status is not JobStatus.RUNNING:
            return job

        while True:
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
            self._run_claimed_task(task, owner_user_id)
        return self._finalize_job(job_id, owner_user_id)

    def _run_claimed_task(self, task: ChapterTask, owner_user_id: str) -> None:
        outcome: TaskImportOutcome | None = None
        try:
            for stage in (
                TaskStage.FETCHING,
                TaskStage.PARSING,
                TaskStage.VALIDATING,
                TaskStage.IMPORTING,
            ):
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
                result = self.pipeline.run_stage(
                    stage,
                    task,
                    cancel_check=lambda: self.repository.is_cancel_requested(task.job_id, owner_user_id),
                )
                if stage is TaskStage.IMPORTING and result is not None:
                    outcome = result
                if self._cancel_claimed_task(task, owner_user_id):
                    return
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
