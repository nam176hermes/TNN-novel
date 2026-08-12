"""Sequential durable worker core for P06 import jobs.

The database is the scheduling source of truth.  This module deliberately has
no HTTP routes, background thread, automatic retry scheduler, or concurrency
greater than one task per ``run_job`` invocation.  A later integration can
provide a real source/import pipeline through the small injected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol
import random
import time
from contextlib import contextmanager
from threading import Condition
from urllib.parse import urlparse

from app.database.import_jobs import (
    BrowserResultPublicationRejected,
    ChapterTask,
    ImportJob,
    ImportJobRepository,
    InvalidImportJobTransition,
    JobStatus,
    TaskStage,
    TaskStatus,
)
from app.import_contracts import (
    MAX_CORRELATION_ID_LENGTH,
    MAX_PUBLIC_STRING_LENGTH,
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
)
from app.security.url_policy import reject_credential_query
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.observability import Observability, default_observability
from app.services.import_job_runtime import BoundedTaskRunner, RetryPolicy
from app.services.import_job_quotas import ImportJobQuotaError, ImportJobQuotaPolicy


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
    operation: str = ""


class ImportTaskPipeline(Protocol):
    """A source/import implementation supplied by a future integration."""

    def run_stage(
        self,
        stage: TaskStage,
        task: ChapterTask,
        *,
        cancel_check: Callable[[], bool],
    ) -> TaskImportOutcome | BrowserTaskResult | None: ...

    def release_task(self, task_id: int) -> None: ...


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
        quota_policy: ImportJobQuotaPolicy | None = None,
        observability: Observability | None = None,
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
        self.quota_policy = quota_policy or ImportJobQuotaPolicy()
        self.observability = observability or default_observability

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
        tasks: Iterable[Mapping[str, Any]],
        book_id: int | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
        operation_kind: ImportOperationKind = ImportOperationKind.IMPORT_CHAPTERS,
        deadline_at: str = "",
        correlation_id: str = "",
    ) -> ImportJob:
        task_snapshot = list(tasks)
        reject_credential_query(source_url)
        for task in task_snapshot:
            reject_credential_query(str(task["canonical_chapter_url"]))
        if operation_kind == ImportOperationKind.PREVIEW:
            self._validate_preview_metadata(
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
        if len(task_snapshot) > self.quota_policy.max_chapters_per_job:
            raise ImportJobQuotaError(
                "chapter_quota_exceeded",
                f"A job can include at most {self.quota_policy.max_chapters_per_job} chapters",
            )
        if self.repository.count_active_jobs(owner_user_id) >= self.quota_policy.max_active_jobs_per_owner:
            raise ImportJobQuotaError(
                "active_job_quota_exceeded",
                "The active import-job limit has been reached. Wait for a job to finish before starting another.",
            )
        job = self.repository.create_job(
            owner_user_id=owner_user_id,
            source=source,
            source_url=source_url,
            total=len(task_snapshot),
            book_id=book_id,
            config_snapshot=config_snapshot,
            operation_kind=operation_kind,
            deadline_at=deadline_at,
            correlation_id=correlation_id,
        )
        for task in task_snapshot:
            self.repository.create_task(
                job_id=job.id,
                owner_user_id=owner_user_id,
                canonical_identity=str(task["canonical_identity"]),
                canonical_chapter_url=str(task["canonical_chapter_url"]),
                chapter_number=int(task.get("chapter_number") or 0),
                title=str(task.get("title") or ""),
                book_id=book_id,
            )
        result = self.get_job(job.id, owner_user_id)
        self.observability.record_job(status=result.status.value, operation="created", job_id=result.id)
        self._refresh_workload_metrics()
        return result

    def enqueue_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        job = self.repository.enqueue_job(job_id, owner_user_id)
        self._refresh_workload_metrics()
        return job

    def get_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        job = self.repository.get_job(job_id, owner_user_id)
        if job is None:
            raise LookupError("import job not found")
        return job

    def request_cancel(self, job_id: str, owner_user_id: str) -> ImportJob:
        self.repository.request_cancel(job_id, owner_user_id)
        self.repository.cancel_queued_tasks(job_id, owner_user_id)
        result = self._finalize_job(job_id, owner_user_id)
        self._record_terminal_job(result, operation="cancel")
        self._refresh_workload_metrics()
        return result

    def retry_failed_tasks(self, job_id: str, owner_user_id: str) -> list[ChapterTask]:
        """Explicit retry only for failed tasks marked retryable by the pipeline."""
        job = self.get_job(job_id, owner_user_id)
        if job.operation_kind is ImportOperationKind.PREVIEW:
            raise InvalidImportJobTransition("preview jobs cannot be retried")
        retried: list[ChapterTask] = []
        for task in self.repository.list_tasks(job_id, owner_user_id):
            if task.status is TaskStatus.FAILED and task.retryable:
                retried.append(self.repository.retry_task(task.id, owner_user_id))
        if retried:
            self.repository.restart_job_for_retry(job_id, owner_user_id)
        return retried

    def list_tasks(self, job_id: str, owner_user_id: str) -> list[ChapterTask]:
        self.get_job(job_id, owner_user_id)
        return self.repository.list_tasks(job_id, owner_user_id)

    def list_events(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ):
        self.get_job(job_id, owner_user_id)
        return self.repository.list_events(
            job_id,
            owner_user_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def recover_interrupted_jobs(self) -> list[str]:
        """Recover only expired task leases; it never reruns a task itself."""
        recovered = self.repository.recover_expired_tasks()
        return sorted({job_id for job_id, _owner_user_id, _task_id in recovered})

    def run_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        """Run a bounded fetch batch and serialize imports by chapter order."""
        job = self.get_job(job_id, owner_user_id)
        if job.cancel_requested_at:
            self.repository.cancel_queued_tasks(job_id, owner_user_id)
            result = self._finalize_job(job_id, owner_user_id)
            self._record_terminal_job(result, operation="run")
            self._refresh_workload_metrics()
            return result
        if job.status is JobStatus.QUEUED:
            job = self.repository.transition_job(job_id, owner_user_id, JobStatus.RUNNING)
        elif job.status is not JobStatus.RUNNING:
            return job
        if job.operation_kind is ImportOperationKind.PREVIEW:
            if self._preview_expired(job):
                result = self.repository.expire_browser_job(job_id, owner_user_id)
                self._record_terminal_job(result, operation="preview")
                self._refresh_workload_metrics()
                return result
            return self._run_preview_job(job, owner_user_id)
        if self._duration_limit_exceeded(job):
            self.repository.fail_pending_tasks(
                job_id,
                owner_user_id,
                error_code="job_duration_exceeded",
                error_message="Import job exceeded the configured duration limit",
            )
            result = self.repository.transition_job(
                job_id,
                owner_user_id,
                JobStatus.FAILED,
                error_summary="Import job exceeded the configured duration limit",
            )
            self._refresh_workload_metrics()
            self._record_terminal_job(result, operation="quota")
            return result

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
        result = self._finalize_job(job_id, owner_user_id)
        self._record_terminal_job(result, operation="run")
        self._refresh_workload_metrics()
        return result

    def _run_preview_job(self, job: ImportJob, owner_user_id: str) -> ImportJob:
        if self._preview_should_stop(job.id, owner_user_id):
            result = self.get_job(job.id, owner_user_id)
            self._record_terminal_job(result, operation="preview")
            self._refresh_workload_metrics()
            return result
        task = self.repository.claim_next_task(
            job.id,
            owner_user_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if task is not None:
            self._run_claimed_preview_task(job, task, owner_user_id)
        result = self.get_job(job.id, owner_user_id)
        self._record_terminal_job(result, operation="preview")
        self._refresh_workload_metrics()
        return result

    def _run_claimed_preview_task(
        self,
        job: ImportJob,
        task: ChapterTask,
        owner_user_id: str,
    ) -> None:
        current_task = task
        result: BrowserTaskResult | None = None
        try:
            try:
                result, current_task = self._execute_preview_stages(
                    job,
                    task,
                    owner_user_id,
                )
            except SourceAdapterError as exc:
                result = self._browser_source_error_result(job, exc)
                current_task = self._current_task(task, owner_user_id)
            except Exception:
                result = BrowserTaskResult(
                    correlation_id=job.correlation_id,
                    state=BrowserResultState.FAILED,
                    error_code=FetchErrorCode.INTERNAL_ERROR.value,
                    error_message="Browser task failed",
                    retryable=False,
                    http_status=500,
                )
                current_task = self._current_task(task, owner_user_id)

            if result is None or self._preview_should_stop(job.id, owner_user_id):
                return
            try:
                self._publish_preview_result(
                    job,
                    current_task,
                    owner_user_id,
                    result,
                )
            except BrowserResultPublicationRejected as exc:
                self._reconcile_preview_publication_rejection(job, owner_user_id, exc)
        finally:
            self.pipeline.release_task(task.id)

    def _execute_preview_stages(
        self,
        job: ImportJob,
        task: ChapterTask,
        owner_user_id: str,
    ) -> tuple[BrowserTaskResult | None, ChapterTask]:
        current_task = task
        outcome: BrowserTaskResult | None = None
        for stage in (
            TaskStage.FETCHING,
            TaskStage.PARSING,
            TaskStage.VALIDATING,
            TaskStage.IMPORTING,
        ):
            if self._preview_should_stop(job.id, owner_user_id):
                return None, current_task
            current_task = self.repository.renew_task_lease(
                task.id,
                owner_user_id,
                lease_token=task.lease_token,
                lease_seconds=self.lease_seconds,
            )
            current_task = self.repository.transition_task(
                task.id,
                owner_user_id,
                status=TaskStatus.RUNNING,
                stage=stage,
                lease_token=task.lease_token,
            )
            started = self.clock()
            retry_attempt = 1
            while True:
                if self._preview_should_stop(job.id, owner_user_id):
                    return None, current_task
                try:
                    stage_result = self.pipeline.run_stage(
                        stage,
                        task,
                        cancel_check=lambda: self.repository.is_cancel_requested(
                            task.job_id,
                            owner_user_id,
                        ),
                    )
                    break
                except SourceAdapterError as exc:
                    elapsed = self.clock() - started
                    if not self.retry_policy.should_retry(
                        exc,
                        attempt=retry_attempt,
                        elapsed_seconds=elapsed,
                    ):
                        raise
                    delay = self.retry_policy.delay_seconds(
                        attempt=retry_attempt,
                        random_value=self.random_value,
                        retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                    )
                    next_attempt = (
                        datetime.now(timezone.utc) + timedelta(seconds=delay)
                    ).isoformat()
                    current_task = self.repository.schedule_task_retry(
                        task.id,
                        owner_user_id,
                        lease_token=task.lease_token,
                        next_attempt_at=next_attempt,
                        error_code=exc.code.value,
                        error_message=exc.safe_message,
                    )
                    self.observability.metrics.increment(
                        "import_task_retries_total",
                        labels={
                            "adapter_id": "unknown",
                            "fetch_method": task.fetch_method or "direct_http",
                            "stage": stage.value,
                            "operation": "retry",
                        },
                    )
                    if self._preview_should_stop(job.id, owner_user_id):
                        return None, current_task
                    self.sleep(delay)
                    if self._preview_should_stop(job.id, owner_user_id):
                        return None, current_task
                    current_task = self.repository.transition_task(
                        task.id,
                        owner_user_id,
                        status=TaskStatus.RUNNING,
                        stage=stage,
                        lease_token=task.lease_token,
                    )
                    retry_attempt += 1
            if stage is TaskStage.IMPORTING:
                if not isinstance(stage_result, BrowserTaskResult):
                    raise RuntimeError("preview importing stage returned no browser result")
                outcome = stage_result
        return outcome, current_task

    def _publish_preview_result(
        self,
        job: ImportJob,
        task: ChapterTask,
        owner_user_id: str,
        result: BrowserTaskResult,
    ) -> None:
        self.repository.publish_browser_result(
            job.id,
            owner_user_id,
            task_id=task.id,
            lease_token=task.lease_token,
            lease_owner=task.lease_owner,
            expected_job_version=job.version,
            expected_task_version=task.version,
            result=result,
        )
        task_status, task_stage = {
            BrowserResultState.COMPLETED: (TaskStatus.SUCCEEDED, TaskStage.SUCCEEDED),
            BrowserResultState.BLOCKED: (
                TaskStatus.USER_VERIFICATION_REQUIRED,
                TaskStage.USER_VERIFICATION_REQUIRED,
            ),
            BrowserResultState.FAILED: (TaskStatus.FAILED, TaskStage.FAILED),
            BrowserResultState.CANCELLED: (TaskStatus.CANCELLED, TaskStage.CANCELLED),
            BrowserResultState.TIMED_OUT: (TaskStatus.FAILED, TaskStage.FAILED),
        }[result.state]
        self.observability.record_task(
            status=task_status.value,
            stage=task_stage.value,
            operation="preview",
            job_id=job.id,
            task_id=task.id,
            error_code=result.error_code,
            attempts=task.attempts,
            worker_id=self.worker_id,
        )
        if result.state is BrowserResultState.COMPLETED:
            self.observability.metrics.increment(
                "import_operations_total",
                labels={"operation": "preview"},
            )

    def _reconcile_preview_publication_rejection(
        self,
        job: ImportJob,
        owner_user_id: str,
        rejection: BrowserResultPublicationRejected,
    ) -> None:
        if rejection.code == "cancelled":
            self.repository.request_cancel(job.id, owner_user_id)
        elif rejection.code == "deadline_exceeded":
            self.repository.expire_browser_job(job.id, owner_user_id)

    def _preview_should_stop(self, job_id: str, owner_user_id: str) -> bool:
        current = self.repository.get_job(job_id, owner_user_id)
        if current is None:
            return True
        if current.result_snapshot is not None:
            return True
        if current.cancel_requested_at:
            self.repository.request_cancel(job_id, owner_user_id)
            return True
        if self._preview_expired(current):
            self.repository.expire_browser_job(job_id, owner_user_id)
            return True
        return current.status is not JobStatus.RUNNING

    def _preview_expired(self, job: ImportJob) -> bool:
        if self._duration_limit_exceeded(job):
            return True
        try:
            deadline = datetime.fromisoformat(job.deadline_at)
        except (TypeError, ValueError):
            return True
        return deadline.tzinfo is None or deadline <= datetime.now(timezone.utc)

    @staticmethod
    def _validate_preview_metadata(*, correlation_id: str, deadline_at: str) -> None:
        if not isinstance(correlation_id, str) or not (
            1 <= len(correlation_id) <= MAX_CORRELATION_ID_LENGTH
        ):
            raise ValueError("invalid preview correlation_id")
        try:
            deadline = datetime.fromisoformat(deadline_at)
        except (TypeError, ValueError):
            raise ValueError("invalid preview deadline_at") from None
        if deadline.tzinfo is None:
            raise ValueError("invalid preview deadline_at")

    @staticmethod
    def _browser_source_error_result(
        job: ImportJob,
        error: SourceAdapterError,
    ) -> BrowserTaskResult:
        http_status = error.http_status
        if (
            isinstance(http_status, bool)
            or not isinstance(http_status, int)
            or not 400 <= http_status <= 599
        ):
            http_status = None
        return BrowserTaskResult(
            correlation_id=job.correlation_id,
            state=(
                BrowserResultState.BLOCKED
                if error.code is FetchErrorCode.USER_VERIFICATION_REQUIRED
                else BrowserResultState.FAILED
            ),
            error_code=error.code.value,
            error_message=str(error.safe_message)[:MAX_PUBLIC_STRING_LENGTH],
            retryable=bool(error.retryable),
            http_status=http_status,
        )

    def _current_task(self, task: ChapterTask, owner_user_id: str) -> ChapterTask:
        return next(
            item
            for item in self.repository.list_tasks(task.job_id, owner_user_id)
            if item.id == task.id
        )

    def _retry_policy_for_task(self, task: ChapterTask) -> RetryPolicy:
        """Use the validated legacy URL retry limit without changing generic jobs."""
        job = self.repository.get_job_internal(task.job_id)
        if job is None:
            return self.retry_policy
        snapshot = job.config_snapshot
        retry_limit = snapshot.get("legacy_url_retry_limit")
        if isinstance(retry_limit, bool) or not isinstance(retry_limit, int):
            return self.retry_policy
        if not 0 <= retry_limit <= 5:
            return self.retry_policy
        return replace(self.retry_policy, max_attempts=retry_limit + 1)

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
        retry_policy = self._retry_policy_for_task(task)
        try:
            for stage in stages:
                if self._duration_limit_exceeded_for_task(task, owner_user_id):
                    raise SourceAdapterError(
                        "Import job exceeded the configured duration limit",
                        code=FetchErrorCode.IMPORT_FAILED,
                        retryable=False,
                        http_status=429,
                    )
                if self._cancel_claimed_task(task, owner_user_id):
                    return
                self.repository.renew_task_lease(
                    task.id,
                    owner_user_id,
                    lease_token=task.lease_token,
                    lease_seconds=self.lease_seconds,
                )
                completed_task = self.repository.transition_task(
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
                        if not retry_policy.should_retry(exc, attempt=retry_attempt, elapsed_seconds=elapsed):
                            raise
                        delay = retry_policy.delay_seconds(
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
                        self.observability.metrics.increment(
                            "import_task_retries_total",
                            labels={
                                "adapter_id": "unknown",
                                "fetch_method": task.fetch_method or "direct_http",
                                "stage": stage.value,
                                "operation": "retry",
                            },
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
                completed_task = self.repository.transition_task(
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
                self.observability.record_task(
                    status=TaskStatus.SUCCEEDED.value,
                    stage=TaskStage.SUCCEEDED.value,
                    operation=outcome.operation or "import",
                    job_id=task.job_id,
                    task_id=task.id,
                    fetch_method=outcome.fetch_method,
                    attempts=completed_task.attempts,
                    elapsed_ms=outcome.elapsed_ms,
                    parsed_text_length=outcome.text_length,
                    worker_id=self.worker_id,
                )
                self.observability.metrics.increment(
                    "import_operations_total",
                    labels={"operation": outcome.operation or "import"},
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
            failed_task = self.repository.transition_task(
                task.id,
                owner_user_id,
                status=status,
                stage=stage,
                error_code=exc.code.value,
                error_message=exc.safe_message,
                retryable=bool(exc.retryable),
                lease_token=task.lease_token,
            )
            self.observability.record_task(
                status=status.value,
                stage=stage.value,
                operation="import",
                job_id=task.job_id,
                task_id=task.id,
                error_code=exc.code.value,
                attempts=failed_task.attempts,
                worker_id=self.worker_id,
            )
        except Exception:
            failed_task = self.repository.transition_task(
                task.id,
                owner_user_id,
                status=TaskStatus.FAILED,
                stage=TaskStage.FAILED,
                error_code=FetchErrorCode.INTERNAL_ERROR.value,
                error_message="Import task failed",
                retryable=False,
                lease_token=task.lease_token,
            )
            self.observability.record_task(
                status=TaskStatus.FAILED.value,
                stage=TaskStage.FAILED.value,
                operation="import",
                job_id=task.job_id,
                task_id=task.id,
                error_code=FetchErrorCode.INTERNAL_ERROR.value,
                attempts=failed_task.attempts,
                worker_id=self.worker_id,
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
        cancelled_task = self.repository.transition_task(
            task.id,
            owner_user_id,
            status=TaskStatus.CANCELLED,
            stage=TaskStage.CANCELLED,
            error_code=FetchErrorCode.CANCELLED.value,
            lease_token=task.lease_token,
        )
        self.observability.record_task(
            status=TaskStatus.CANCELLED.value,
            stage=TaskStage.CANCELLED.value,
            operation="cancel",
            job_id=task.job_id,
            task_id=task.id,
            error_code=FetchErrorCode.CANCELLED.value,
            attempts=cancelled_task.attempts,
            worker_id=self.worker_id,
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

    def _duration_limit_exceeded(self, job: ImportJob) -> bool:
        if not job.started_at:
            return False
        try:
            started_at = datetime.fromisoformat(job.started_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - started_at).total_seconds() >= self.quota_policy.max_job_duration_seconds

    def _duration_limit_exceeded_for_task(self, task: ChapterTask, owner_user_id: str) -> bool:
        job = self.repository.get_job(task.job_id, owner_user_id)
        return bool(job and self._duration_limit_exceeded(job))

    def _refresh_workload_metrics(self) -> None:
        counts = self.repository.workload_counts()
        self.observability.set_workload(**counts)

    def _record_terminal_job(self, job: ImportJob, *, operation: str) -> None:
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            self.observability.record_job(status=job.status.value, operation=operation, job_id=job.id)
