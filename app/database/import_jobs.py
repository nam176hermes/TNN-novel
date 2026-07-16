"""Durable persistence primitives for the future import-job worker.

P05 deliberately stops at persistence and state transitions.  Nothing in this
module claims, runs, retries, or streams jobs; later milestones can build those
behaviours on the transaction-safe repository below.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from app.database.connection import get_connection


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    USER_VERIFICATION_REQUIRED = "user_verification_required"


class TaskStage(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    WAITING_RETRY = "waiting_retry"
    PARSING = "parsing"
    VALIDATING = "validating"
    IMPORTING = "importing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    USER_VERIFICATION_REQUIRED = "user_verification_required"


class InvalidImportJobTransition(ValueError):
    """Raised before an invalid durable job or task transition is persisted."""


class ConcurrentImportJobUpdate(RuntimeError):
    """Raised when an optimistic compare-and-set update loses its race."""


_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.PARTIALLY_SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.SUCCEEDED: set(),
    JobStatus.PARTIALLY_SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}

_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_RETRY,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.USER_VERIFICATION_REQUIRED,
    },
    TaskStatus.WAITING_RETRY: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.USER_VERIFICATION_REQUIRED: set(),
}

_SENSITIVE_PAYLOAD_MARKERS = ("html", "content", "cookie", "token", "secret", "password", "authorization")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_loads(value: object) -> dict[str, Any]:
    try:
        loaded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def sanitize_import_job_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return metadata that can safely be persisted as config/event JSON.

    Import content and session credentials belong in neither durable job config
    nor events.  Drop such fields recursively instead of relying on callers to
    remember this operational boundary.
    """

    def clean(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): clean(child)
                for key, child in item.items()
                if not any(marker in str(key).lower() for marker in _SENSITIVE_PAYLOAD_MARKERS)
            }
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item]
        if isinstance(item, str):
            return item[:2_000]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(item)[:2_000]

    return clean(value or {})


@dataclass(frozen=True)
class ImportJob:
    id: str
    owner_user_id: str
    source: str
    source_url: str
    book_id: int | None
    status: JobStatus
    total: int
    queued_count: int
    running_count: int
    succeeded_count: int
    failed_count: int
    cancelled_count: int
    waiting_retry_count: int
    verification_required_count: int
    created_at: str
    started_at: str
    finished_at: str
    cancel_requested_at: str
    config_snapshot: dict[str, Any]
    error_summary: str
    version: int


@dataclass(frozen=True)
class ChapterTask:
    id: int
    job_id: str
    canonical_identity: str
    canonical_chapter_url: str
    chapter_number: int
    title: str
    status: TaskStatus
    stage: TaskStage
    attempts: int
    next_attempt_at: str
    error_code: str
    error_message: str
    fetch_method: str
    text_length: int
    content_hash: str
    elapsed_ms: int
    started_at: str
    finished_at: str
    book_id: int | None
    chapter_id: int | None
    retryable: bool
    lease_token: str
    lease_owner: str
    lease_expires_at: str
    version: int


@dataclass(frozen=True)
class ImportJobEvent:
    id: int
    sequence: int
    job_id: str
    task_id: int | None
    event_type: str
    payload: dict[str, Any]
    created_at: str


def _job_from_row(row: sqlite3.Row) -> ImportJob:
    return ImportJob(
        id=str(row["id"]),
        owner_user_id=str(row["owner_user_id"] or ""),
        source=str(row["source"] or ""),
        source_url=str(row["source_url"] or ""),
        book_id=int(row["book_id"]) if row["book_id"] is not None else None,
        status=JobStatus(str(row["status"])),
        total=int(row["total"] or 0),
        queued_count=int(row["queued_count"] or 0),
        running_count=int(row["running_count"] or 0),
        succeeded_count=int(row["succeeded_count"] or 0),
        failed_count=int(row["failed_count"] or 0),
        cancelled_count=int(row["cancelled_count"] or 0),
        waiting_retry_count=int(row["waiting_retry_count"] or 0),
        verification_required_count=int(row["verification_required_count"] or 0),
        created_at=str(row["created_at"] or ""),
        started_at=str(row["started_at"] or ""),
        finished_at=str(row["finished_at"] or ""),
        cancel_requested_at=str(row["cancel_requested_at"] or ""),
        config_snapshot=_safe_json_loads(row["config_snapshot_json"]),
        error_summary=str(row["error_summary"] or ""),
        version=int(row["version"] or 0),
    )


def _task_from_row(row: sqlite3.Row) -> ChapterTask:
    return ChapterTask(
        id=int(row["id"]),
        job_id=str(row["job_id"]),
        canonical_identity=str(row["canonical_identity"] or ""),
        canonical_chapter_url=str(row["canonical_chapter_url"] or ""),
        chapter_number=int(row["chapter_number"] or 0),
        title=str(row["title"] or ""),
        status=TaskStatus(str(row["status"])),
        stage=TaskStage(str(row["stage"])),
        attempts=int(row["attempts"] or 0),
        next_attempt_at=str(row["next_attempt_at"] or ""),
        error_code=str(row["error_code"] or ""),
        error_message=str(row["error_message"] or ""),
        fetch_method=str(row["fetch_method"] or ""),
        text_length=int(row["text_length"] or 0),
        content_hash=str(row["content_hash"] or ""),
        elapsed_ms=int(row["elapsed_ms"] or 0),
        started_at=str(row["started_at"] or ""),
        finished_at=str(row["finished_at"] or ""),
        book_id=int(row["book_id"]) if row["book_id"] is not None else None,
        chapter_id=int(row["chapter_id"]) if row["chapter_id"] is not None else None,
        retryable=bool(int(row["retryable"] or 0)),
        lease_token=str(row["lease_token"] or ""),
        lease_owner=str(row["lease_owner"] or ""),
        lease_expires_at=str(row["lease_expires_at"] or ""),
        version=int(row["version"] or 0),
    )


def _event_from_row(row: sqlite3.Row) -> ImportJobEvent:
    return ImportJobEvent(
        id=int(row["id"]),
        sequence=int(row["sequence"]),
        job_id=str(row["job_id"]),
        task_id=int(row["task_id"]) if row["task_id"] is not None else None,
        event_type=str(row["event_type"]),
        payload=_safe_json_loads(row["payload_json"]),
        created_at=str(row["created_at"] or ""),
    )


class ImportJobRepository:
    """Repository with owner-scoped reads and compare-and-set transitions."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def create_job(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_url: str,
        total: int = 0,
        book_id: int | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> ImportJob:
        now = _now()
        job_id = uuid.uuid4().hex
        snapshot = sanitize_import_job_payload(config_snapshot)
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO import_jobs (
                    id, owner_user_id, source, source_url, book_id, status, total,
                    created_at, config_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, owner_user_id, source, source_url, book_id, JobStatus.QUEUED.value, max(0, total), now, json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
            )
            self._append_event(conn, job_id, None, "job_created", {"status": JobStatus.QUEUED.value})
            row = self._job_row(conn, job_id, owner_user_id)
        return _job_from_row(row)

    def get_job(self, job_id: str, owner_user_id: str) -> ImportJob | None:
        with get_connection(self.db_path) as conn:
            row = self._job_row(conn, job_id, owner_user_id, required=False)
        return _job_from_row(row) if row is not None else None

    def get_job_internal(self, job_id: str) -> ImportJob | None:
        """Load trusted worker context without exposing an unscoped API read.

        HTTP callers must continue to use :meth:`get_job`.  A claimed chapter
        task already carries a database-owned ``job_id``; the source pipeline
        uses this method only to recover its sanitized durable config after a
        process restart.
        """
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row is not None else None

    def count_active_jobs(self, owner_user_id: str) -> int:
        """Count non-terminal durable import jobs for one owner."""

        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM import_jobs
                WHERE owner_user_id = ? AND status IN (?, ?)
                """,
                (owner_user_id, JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchone()
        return int(row["count"] if row else 0)

    def workload_counts(self) -> dict[str, int]:
        """Return bounded global gauges without returning owner or task content."""

        with get_connection(self.db_path) as conn:
            jobs = conn.execute(
                "SELECT COUNT(*) AS count FROM import_jobs WHERE status IN (?, ?)",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchone()
            tasks = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM chapter_tasks
                WHERE status IN (?, ?)
                """,
                (TaskStatus.QUEUED.value, TaskStatus.WAITING_RETRY.value),
            ).fetchone()
        return {
            "active_jobs": int(jobs["count"] if jobs else 0),
            "queue_depth": int(tasks["count"] if tasks else 0),
        }

    def list_runnable_jobs(self, *, limit: int = 1) -> list[ImportJob]:
        """Return trusted worker candidates without exposing an unscoped API read.

        Claims remain atomic at the task level.  This query merely lets a
        process discover a durable queue after an API restart; a competing
        worker that sees the same job cannot process the same task lease.
        """

        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM import_jobs
                WHERE status IN (?, ?)
                  AND (
                    status = ?
                    OR EXISTS (
                        SELECT 1
                        FROM chapter_tasks
                        WHERE chapter_tasks.job_id = import_jobs.id
                          AND chapter_tasks.status = ?
                    )
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.QUEUED.value,
                    TaskStatus.QUEUED.value,
                    max(1, limit),
                ),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def fail_pending_tasks(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> int:
        """Fail queued/retry tasks when a job-wide hard limit expires."""

        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._job_row(conn, job_id, owner_user_id)
            rows = conn.execute(
                """
                SELECT id FROM chapter_tasks
                WHERE job_id = ? AND status IN (?, ?)
                ORDER BY id ASC
                """,
                (job_id, TaskStatus.QUEUED.value, TaskStatus.WAITING_RETRY.value),
            ).fetchall()
            now = _now()
            for row in rows:
                task_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE chapter_tasks
                    SET status = ?, stage = ?, error_code = ?, error_message = ?,
                        retryable = 0, finished_at = ?, updated_at = ?, version = version + 1
                    WHERE id = ?
                    """,
                    (
                        TaskStatus.FAILED.value,
                        TaskStage.FAILED.value,
                        error_code[:96],
                        error_message[:2_000],
                        now,
                        now,
                        task_id,
                    ),
                )
                self._append_event(
                    conn,
                    job_id,
                    task_id,
                    "task_failed_by_quota",
                    {"error_code": error_code[:96]},
                )
            self._sync_job_counters(conn, job_id)
            conn.commit()
        return len(rows)

    def create_task(
        self,
        *,
        job_id: str,
        owner_user_id: str,
        canonical_identity: str,
        canonical_chapter_url: str,
        chapter_number: int,
        title: str,
        book_id: int | None = None,
    ) -> ChapterTask:
        if not canonical_identity or not canonical_chapter_url:
            raise ValueError("canonical task identity and URL are required")
        now = _now()
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._job_row(conn, job_id, owner_user_id)
            cursor = conn.execute(
                """
                INSERT INTO chapter_tasks (
                    job_id, canonical_identity, canonical_chapter_url, chapter_number,
                    title, status, stage, book_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    canonical_identity,
                    canonical_chapter_url,
                    chapter_number,
                    title,
                    TaskStatus.QUEUED.value,
                    TaskStage.QUEUED.value,
                    book_id,
                    now,
                    now,
                ),
            )
            task_id = int(cursor.lastrowid)
            self._sync_job_counters(conn, job_id)
            self._append_event(conn, job_id, task_id, "task_created", {"status": TaskStatus.QUEUED.value})
            row = self._task_row(conn, task_id, owner_user_id)
        return _task_from_row(row)

    def list_tasks(self, job_id: str, owner_user_id: str) -> list[ChapterTask]:
        with get_connection(self.db_path) as conn:
            if self._job_row(conn, job_id, owner_user_id, required=False) is None:
                return []
            rows = conn.execute(
                "SELECT * FROM chapter_tasks WHERE job_id = ? ORDER BY id ASC", (job_id,)
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def transition_job(
        self,
        job_id: str,
        owner_user_id: str,
        status: JobStatus,
        *,
        error_summary: str = "",
    ) -> ImportJob:
        next_status = JobStatus(status)
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _job_from_row(self._job_row(conn, job_id, owner_user_id))
            if current.status != next_status and next_status not in _JOB_TRANSITIONS[current.status]:
                raise InvalidImportJobTransition(f"job {current.status.value} cannot transition to {next_status.value}")
            now = _now()
            started_at = current.started_at or (now if next_status is JobStatus.RUNNING else "")
            finished_at = now if next_status in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED} else current.finished_at
            result = conn.execute(
                """
                UPDATE import_jobs
                SET status = ?, started_at = ?, finished_at = ?, error_summary = ?, version = version + 1
                WHERE id = ? AND owner_user_id = ? AND version = ?
                """,
                (next_status.value, started_at, finished_at, error_summary[:2_000], job_id, owner_user_id, current.version),
            )
            if result.rowcount != 1:
                raise ConcurrentImportJobUpdate(job_id)
            self._append_event(conn, job_id, None, "job_transitioned", {"status": next_status.value})
            row = self._job_row(conn, job_id, owner_user_id)
        return _job_from_row(row)

    def transition_task(
        self,
        task_id: int,
        owner_user_id: str,
        *,
        status: TaskStatus,
        stage: TaskStage,
        next_attempt_at: str = "",
        error_code: str = "",
        error_message: str = "",
        fetch_method: str = "",
        text_length: int | None = None,
        content_hash: str = "",
        elapsed_ms: int | None = None,
        book_id: int | None = None,
        chapter_id: int | None = None,
        retryable: bool | None = None,
        lease_token: str | None = None,
    ) -> ChapterTask:
        next_status = TaskStatus(status)
        next_stage = TaskStage(stage)
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _task_from_row(self._task_row(conn, task_id, owner_user_id))
            if current.status != next_status and next_status not in _TASK_TRANSITIONS[current.status]:
                raise InvalidImportJobTransition(f"task {current.status.value} cannot transition to {next_status.value}")
            if lease_token is not None and current.lease_token != lease_token:
                raise ConcurrentImportJobUpdate(str(task_id))
            now = _now()
            attempts = current.attempts + int(current.status is not TaskStatus.RUNNING and next_status is TaskStatus.RUNNING)
            started_at = current.started_at or (now if next_status is TaskStatus.RUNNING else "")
            finished_at = now if next_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.USER_VERIFICATION_REQUIRED} else current.finished_at
            result = conn.execute(
                """
                UPDATE chapter_tasks
                SET status = ?, stage = ?, attempts = ?, next_attempt_at = ?,
                    error_code = ?, error_message = ?, fetch_method = ?,
                    text_length = ?, content_hash = ?, elapsed_ms = ?, started_at = ?,
                    finished_at = ?, book_id = ?, chapter_id = ?, retryable = ?,
                    lease_token = ?, lease_owner = ?, lease_expires_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (
                    next_status.value,
                    next_stage.value,
                    attempts,
                    next_attempt_at,
                    error_code[:255],
                    error_message[:2_000],
                    fetch_method[:128],
                    current.text_length if text_length is None else max(0, text_length),
                    content_hash or current.content_hash,
                    current.elapsed_ms if elapsed_ms is None else max(0, elapsed_ms),
                    started_at,
                    finished_at,
                    current.book_id if book_id is None else book_id,
                    current.chapter_id if chapter_id is None else chapter_id,
                    int(current.retryable if retryable is None else retryable),
                    "" if next_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.USER_VERIFICATION_REQUIRED} else current.lease_token,
                    "" if next_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.USER_VERIFICATION_REQUIRED} else current.lease_owner,
                    "" if next_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.USER_VERIFICATION_REQUIRED} else current.lease_expires_at,
                    now,
                    task_id,
                    current.version,
                ),
            )
            if result.rowcount != 1:
                raise ConcurrentImportJobUpdate(str(task_id))
            self._sync_job_counters(conn, current.job_id)
            self._append_event(
                conn,
                current.job_id,
                task_id,
                "task_transitioned",
                {"status": next_status.value, "stage": next_stage.value, "error_code": error_code},
            )
            row = self._task_row(conn, task_id, owner_user_id)
        return _task_from_row(row)

    def retry_task(self, task_id: int, owner_user_id: str) -> ChapterTask:
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _task_from_row(self._task_row(conn, task_id, owner_user_id))
            if current.status not in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.USER_VERIFICATION_REQUIRED,
            }:
                raise InvalidImportJobTransition(f"task {current.status.value} cannot be retried")
            now = _now()
            result = conn.execute(
                """
                UPDATE chapter_tasks
                SET status = ?, stage = ?, next_attempt_at = '', error_code = '',
                    error_message = '', retryable = 0, finished_at = '',
                    lease_token = '', lease_owner = '', lease_expires_at = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (TaskStatus.QUEUED.value, TaskStage.QUEUED.value, now, task_id, current.version),
            )
            if result.rowcount != 1:
                raise ConcurrentImportJobUpdate(str(task_id))
            self._sync_job_counters(conn, current.job_id)
            self._append_event(conn, current.job_id, task_id, "task_retry_requested", {})
            row = self._task_row(conn, task_id, owner_user_id)
        return _task_from_row(row)

    def enqueue_job(self, job_id: str, owner_user_id: str) -> ImportJob:
        """Record an enqueue request without starting any worker."""
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _job_from_row(self._job_row(conn, job_id, owner_user_id))
            if current.status is not JobStatus.QUEUED:
                raise InvalidImportJobTransition(f"job {current.status.value} cannot be enqueued")
            self._append_event(conn, job_id, None, "job_enqueued", {})
            row = self._job_row(conn, job_id, owner_user_id)
        return _job_from_row(row)

    def is_cancel_requested(self, job_id: str, owner_user_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            row = self._job_row(conn, job_id, owner_user_id, required=False)
        return bool(row and row["cancel_requested_at"])

    def claim_next_task(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> ChapterTask | None:
        """Atomically claim a queued task so concurrent workers cannot share it."""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        token = uuid.uuid4().hex
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = _job_from_row(self._job_row(conn, job_id, owner_user_id))
            if job.cancel_requested_at or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return None
            row = conn.execute(
                """
                SELECT * FROM chapter_tasks
                WHERE job_id = ? AND status = ? AND COALESCE(lease_token, '') = ''
                ORDER BY id ASC LIMIT 1
                """,
                (job_id, TaskStatus.QUEUED.value),
            ).fetchone()
            if row is None:
                return None
            task = _task_from_row(row)
            updated = conn.execute(
                """
                UPDATE chapter_tasks
                SET status = ?, attempts = attempts + 1,
                    started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                    lease_token = ?, lease_owner = ?, lease_expires_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = ? AND version = ? AND COALESCE(lease_token, '') = ''
                """,
                (
                    TaskStatus.RUNNING.value,
                    now_text,
                    token,
                    worker_id,
                    expires_at,
                    now_text,
                    task.id,
                    TaskStatus.QUEUED.value,
                    task.version,
                ),
            )
            if updated.rowcount != 1:
                return None
            self._sync_job_counters(conn, job_id)
            self._append_event(conn, job_id, task.id, "task_claimed", {"worker_id": worker_id})
            claimed = self._task_row(conn, task.id, owner_user_id)
        return _task_from_row(claimed)

    def renew_task_lease(
        self,
        task_id: int,
        owner_user_id: str,
        *,
        lease_token: str,
        lease_seconds: int = 120,
    ) -> ChapterTask:
        """Refresh a claimed task lease without changing its stage or event stream."""
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _task_from_row(self._task_row(conn, task_id, owner_user_id))
            updated = conn.execute(
                """
                UPDATE chapter_tasks
                SET lease_expires_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = ? AND lease_token = ? AND version = ?
                """,
                (
                    expires_at,
                    now.isoformat(),
                    task_id,
                    TaskStatus.RUNNING.value,
                    lease_token,
                    current.version,
                ),
            )
            if updated.rowcount != 1:
                raise ConcurrentImportJobUpdate(str(task_id))
            row = self._task_row(conn, task_id, owner_user_id)
        return _task_from_row(row)

    def schedule_task_retry(
        self,
        task_id: int,
        owner_user_id: str,
        *,
        lease_token: str,
        next_attempt_at: str,
        error_code: str,
        error_message: str,
    ) -> ChapterTask:
        """Persist a retry wait and event without running a scheduler."""
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _task_from_row(self._task_row(conn, task_id, owner_user_id))
            if current.status is not TaskStatus.RUNNING or current.lease_token != lease_token:
                raise ConcurrentImportJobUpdate(str(task_id))
            now = _now()
            updated = conn.execute(
                """
                UPDATE chapter_tasks
                SET status = ?, stage = ?, next_attempt_at = ?, error_code = ?, error_message = ?,
                    retryable = 1, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ? AND lease_token = ?
                """,
                (TaskStatus.WAITING_RETRY.value, TaskStage.WAITING_RETRY.value, next_attempt_at,
                 error_code[:255], error_message[:2000], now, task_id, current.version, lease_token),
            )
            if updated.rowcount != 1:
                raise ConcurrentImportJobUpdate(str(task_id))
            self._sync_job_counters(conn, current.job_id)
            self._append_event(conn, current.job_id, task_id, "task_retry_scheduled", {
                "error_code": error_code, "next_attempt_at": next_attempt_at,
            })
            row = self._task_row(conn, task_id, owner_user_id)
        return _task_from_row(row)

    def cancel_queued_tasks(self, job_id: str, owner_user_id: str) -> int:
        """Cancel work that has not been claimed yet, transactionally with events."""
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._job_row(conn, job_id, owner_user_id)
            rows = conn.execute(
                "SELECT id FROM chapter_tasks WHERE job_id = ? AND status = ?",
                (job_id, TaskStatus.QUEUED.value),
            ).fetchall()
            now = _now()
            for row in rows:
                task_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE chapter_tasks
                    SET status = ?, stage = ?, error_code = ?, error_message = '',
                        finished_at = ?, updated_at = ?, version = version + 1
                    WHERE id = ? AND status = ?
                    """,
                    (
                        TaskStatus.CANCELLED.value,
                        TaskStage.CANCELLED.value,
                        "cancelled",
                        now,
                        now,
                        task_id,
                        TaskStatus.QUEUED.value,
                    ),
                )
                self._append_event(conn, job_id, task_id, "task_cancelled", {"reason": "cancel_requested"})
            self._sync_job_counters(conn, job_id)
        return len(rows)

    def recover_expired_tasks(self) -> list[tuple[str, str, int]]:
        """Requeue expired running or retry leases after a process interruption."""
        now = _now()
        recovered: list[tuple[str, str, int]] = []
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT chapter_tasks.id, chapter_tasks.job_id, import_jobs.owner_user_id,
                       chapter_tasks.status
                FROM chapter_tasks JOIN import_jobs ON import_jobs.id = chapter_tasks.job_id
                WHERE (
                    chapter_tasks.status = ?
                    AND COALESCE(chapter_tasks.lease_expires_at, '') != ''
                    AND chapter_tasks.lease_expires_at <= ?
                ) OR (
                    chapter_tasks.status = ?
                    AND COALESCE(chapter_tasks.next_attempt_at, '') != ''
                    AND chapter_tasks.next_attempt_at <= ?
                    AND COALESCE(chapter_tasks.lease_expires_at, '') != ''
                    AND chapter_tasks.lease_expires_at <= ?
                )
                ORDER BY chapter_tasks.id ASC
                """,
                (
                    TaskStatus.RUNNING.value,
                    now,
                    TaskStatus.WAITING_RETRY.value,
                    now,
                    now,
                ),
            ).fetchall()
            affected_jobs: set[str] = set()
            for row in rows:
                task_id = int(row["id"])
                job_id = str(row["job_id"])
                conn.execute(
                    """
                    UPDATE chapter_tasks
                    SET status = ?, stage = ?, next_attempt_at = '', lease_token = '',
                        lease_owner = '', lease_expires_at = '', updated_at = ?, version = version + 1
                    WHERE id = ? AND status IN (?, ?)
                    """,
                    (
                        TaskStatus.QUEUED.value,
                        TaskStage.QUEUED.value,
                        now,
                        task_id,
                        TaskStatus.RUNNING.value,
                        TaskStatus.WAITING_RETRY.value,
                    ),
                )
                reason = (
                    "retry_lease_expired"
                    if str(row["status"]) == TaskStatus.WAITING_RETRY.value
                    else "lease_expired"
                )
                self._append_event(conn, job_id, task_id, "task_recovered", {"reason": reason})
                recovered.append((job_id, str(row["owner_user_id"]), task_id))
                affected_jobs.add(job_id)
            for job_id in affected_jobs:
                self._sync_job_counters(conn, job_id)
                conn.execute(
                    """
                    UPDATE import_jobs
                    SET status = ?, finished_at = '', error_summary = '', version = version + 1
                    WHERE id = ? AND status = ?
                    """,
                    (JobStatus.QUEUED.value, job_id, JobStatus.RUNNING.value),
                )
                self._append_event(conn, job_id, None, "job_recovered", {"reason": "lease_expired"})
        return recovered

    def restart_job_for_retry(self, job_id: str, owner_user_id: str) -> ImportJob:
        """Explicitly reopen a terminal job after its retryable tasks were reset."""
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _job_from_row(self._job_row(conn, job_id, owner_user_id))
            if current.status not in {
                JobStatus.FAILED,
                JobStatus.PARTIALLY_SUCCEEDED,
                JobStatus.CANCELLED,
            }:
                raise InvalidImportJobTransition(f"job {current.status.value} cannot be retried")
            now = _now()
            updated = conn.execute(
                """
                UPDATE import_jobs
                SET status = ?, finished_at = '', error_summary = '', cancel_requested_at = '',
                    version = version + 1
                WHERE id = ? AND owner_user_id = ? AND version = ?
                """,
                (JobStatus.QUEUED.value, job_id, owner_user_id, current.version),
            )
            if updated.rowcount != 1:
                raise ConcurrentImportJobUpdate(job_id)
            self._append_event(conn, job_id, None, "job_retry_requested", {"at": now})
            row = self._job_row(conn, job_id, owner_user_id)
        return _job_from_row(row)

    def request_cancel(self, job_id: str, owner_user_id: str) -> ImportJob:
        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _job_from_row(self._job_row(conn, job_id, owner_user_id))
            if not current.cancel_requested_at:
                requested_at = _now()
                result = conn.execute(
                    """
                    UPDATE import_jobs
                    SET cancel_requested_at = ?, version = version + 1
                    WHERE id = ? AND owner_user_id = ? AND version = ? AND cancel_requested_at = ''
                    """,
                    (requested_at, job_id, owner_user_id, current.version),
                )
                if result.rowcount != 1:
                    raise ConcurrentImportJobUpdate(job_id)
                self._append_event(conn, job_id, None, "cancel_requested", {})
            row = self._job_row(conn, job_id, owner_user_id)
        return _job_from_row(row)

    def list_events(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[ImportJobEvent]:
        with get_connection(self.db_path) as conn:
            if self._job_row(conn, job_id, owner_user_id, required=False) is None:
                return []
            rows = conn.execute(
                """
                SELECT * FROM import_job_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (job_id, max(0, int(after_sequence)), max(1, min(int(limit), 1_000))),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        job_id: str,
        task_id: int | None,
        event_type: str,
        payload: Mapping[str, Any] | None,
    ) -> None:
        sequence = int(
            conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM import_job_events WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO import_job_events (job_id, task_id, sequence, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                task_id,
                sequence,
                event_type,
                json.dumps(sanitize_import_job_payload(payload), ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )

    @staticmethod
    def _job_row(
        conn: sqlite3.Connection,
        job_id: str,
        owner_user_id: str,
        *,
        required: bool = True,
    ) -> sqlite3.Row | None:
        row = conn.execute(
            "SELECT * FROM import_jobs WHERE id = ? AND owner_user_id = ?", (job_id, owner_user_id)
        ).fetchone()
        if row is not None or not required:
            return row
        existing = conn.execute("SELECT 1 FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
        if existing:
            raise PermissionError("import job is not owned by this user")
        raise LookupError("import job not found")

    @staticmethod
    def _task_row(conn: sqlite3.Connection, task_id: int, owner_user_id: str) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT chapter_tasks.*
            FROM chapter_tasks
            JOIN import_jobs ON import_jobs.id = chapter_tasks.job_id
            WHERE chapter_tasks.id = ? AND import_jobs.owner_user_id = ?
            """,
            (task_id, owner_user_id),
        ).fetchone()
        if row is not None:
            return row
        existing = conn.execute("SELECT 1 FROM chapter_tasks WHERE id = ?", (task_id,)).fetchone()
        if existing:
            raise PermissionError("chapter task is not owned by this user")
        raise LookupError("chapter task not found")

    @staticmethod
    def _sync_job_counters(conn: sqlite3.Connection, job_id: str) -> None:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM chapter_tasks WHERE job_id = ? GROUP BY status", (job_id,)
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        conn.execute(
            """
            UPDATE import_jobs
            SET total = ?, queued_count = ?, running_count = ?, succeeded_count = ?,
                failed_count = ?, cancelled_count = ?, waiting_retry_count = ?,
                verification_required_count = ?
            WHERE id = ?
            """,
            (
                sum(counts.values()),
                counts.get(TaskStatus.QUEUED.value, 0),
                counts.get(TaskStatus.RUNNING.value, 0),
                counts.get(TaskStatus.SUCCEEDED.value, 0),
                counts.get(TaskStatus.FAILED.value, 0),
                counts.get(TaskStatus.CANCELLED.value, 0),
                counts.get(TaskStatus.WAITING_RETRY.value, 0),
                counts.get(TaskStatus.USER_VERIFICATION_REQUIRED.value, 0),
                job_id,
            ),
        )
