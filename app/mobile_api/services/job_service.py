from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.database.db import (
    claim_mobile_job,
    get_chapter_by_id,
    get_mobile_job,
    heartbeat_mobile_job_lease,
    list_mobile_jobs,
    mark_interrupted_mobile_jobs,
    record_job_log,
    record_job_attempt,
    record_operational_event,
    release_mobile_job_lease,
    request_cancel_mobile_job,
    sanitize_job_error,
    save_mobile_job,
    save_qa_report,
)
from app.ingestion.source_adapters import SourceAdapterError, SourceBlockedError, validate_public_http_url
from app.ingestion.source_policies import chapter_url_matches_source_book, get_source_policy
from app.mobile_api.config import mobile_settings
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.job_states import is_valid_job_state_transition, normalize_job_state, state_for_stage
from app.services.tts.availability import require_tts_runtime_available
from app.translation.ollama_client import is_retryable_provider_error
from app.translation.presets import get_translation_preset

logger = logging.getLogger(__name__)
TRANSLATE_CHAPTER_MAX_RETRIES = 2
TRANSLATE_CHAPTER_RETRY_DELAYS = (5.0, 15.0)
TRANSLATED_CHAPTER_STATUSES = {"translated", "qa_low", "audio_done"}
GENERIC_JOB_FAILURE_DETAIL = "Job failed. Check server logs."
TRANSLATION_JOB_FAILURE_DETAIL = "Translation failed. Check provider settings and server logs."
TTS_JOB_FAILURE_DETAIL = "TTS job failed. Check TTS settings and server logs."
DAILY_JOB_FAILURE_DETAIL = "Daily job failed. Check provider settings and server logs."
QA_JOB_FAILURE_DETAIL = "QA failed. Check provider settings and server logs."
IMPORT_CHAPTER_FAILURE_DETAIL = "import failed; check server logs"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_stage_timings(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    safe_timings: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        safe_item = dict(item)
        if safe_item.get("error"):
            safe_item["error"] = "Stage failed. Check server logs."
        safe_timings.append(safe_item)
    return safe_timings


class JobStatus:
    def __init__(
        self,
        job_id: str,
        job_type: str,
        target_ids: List[int] | None = None,
        total: int = 0,
        params: dict | None = None,
        status: str = "queued",
        state: str = "",
        owner_user_id: str = "",
        progress: int = 0,
        message: str = "",
        error: str = "",
        created_at: str | None = None,
        updated_at: str | None = None,
        finished_at: str | None = None,
        current_book_id: int = 0,
        current_chapter_id: int = 0,
        current_chunk_index: int = 0,
        total_chunks: int = 0,
        current_step: str = "",
        provider: str = "",
        model: str = "",
        retry_count: int = 0,
        started_at: str = "",
        completed_at: str = "",
        failed_at: str = "",
        cancel_requested: bool = False,
        last_safe_error: str = "",
        internal_error_ref: str = "",
    ):
        self.job_id = job_id
        self.job_type = job_type  # translate, tts, daily, qa
        self.owner_user_id = owner_user_id
        self.status = status  # queued, running, failed, interrupted, retrying, completed, cancelled
        self.state = normalize_job_state(status, current_step=current_step, existing_state=state)
        self.progress = progress
        self.total = total
        self.target_ids = target_ids or []
        self.params = params or {}
        self.message = message
        self.error = error
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at
        self.finished_at: Optional[str] = finished_at
        self.current_book_id = current_book_id
        self.current_chapter_id = current_chapter_id
        self.current_chunk_index = current_chunk_index
        self.total_chunks = total_chunks
        self.current_step = current_step
        self.provider = provider
        self.model = model
        self.retry_count = retry_count
        self.started_at = started_at
        self.completed_at = completed_at
        self.failed_at = failed_at
        self.cancel_requested = cancel_requested
        self.last_safe_error = last_safe_error
        self.internal_error_ref = internal_error_ref

    def to_dict(self) -> dict:
        params = self.params or {}
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "owner_user_id": self.owner_user_id,
            "status": self.status,
            "state": self.state,
            "progress": self.progress,
            "total": self.total,
            "current_book_id": self.current_book_id,
            "current_chapter_id": self.current_chapter_id,
            "current_chunk_index": self.current_chunk_index,
            "total_chunks": self.total_chunks,
            "current_step": self.current_step,
            "provider": self.provider,
            "model": self.model,
            "target_ids": self.target_ids,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "last_safe_error": self.last_safe_error,
            "internal_error_ref": self.internal_error_ref,
            "preset_id": params.get("preset_id") or "",
            "chunk_size": params.get("chunk_size"),
            "active_stage": params.get("active_stage") or "",
            "stage_timings": _safe_stage_timings(params.get("stage_timings") or []),
            "retry_of_job_id": params.get("retry_of_job_id") or "",
            "retry_count": self.retry_count or _safe_int(params.get("retry_count"), 0),
            "previous_error": params.get("previous_error") or "",
            "last_retry_job_id": params.get("last_retry_job_id") or "",
            "skipped_completed_chapter_ids": params.get("skipped_completed_chapter_ids") or [],
        }

    def to_record(self) -> dict:
        record = self.to_dict()
        record["params"] = self.params
        return record

    @classmethod
    def from_record(cls, record: dict) -> "JobStatus":
        return cls(
            job_id=record["job_id"],
            job_type=record["job_type"],
            target_ids=record.get("target_ids") or [],
            total=int(record.get("total") or 0),
            params=record.get("params") or {},
            status=record.get("status") or "queued",
            state=record.get("state") or "",
            owner_user_id=record.get("owner_user_id") or "",
            progress=int(record.get("progress") or 0),
            message=record.get("message") or "",
            error=record.get("error") or "",
            created_at=record.get("created_at"),
            updated_at=record.get("updated_at"),
            finished_at=record.get("finished_at"),
            current_book_id=_safe_int(record.get("current_book_id"), 0),
            current_chapter_id=_safe_int(record.get("current_chapter_id"), 0),
            current_chunk_index=_safe_int(record.get("current_chunk_index"), 0),
            total_chunks=_safe_int(record.get("total_chunks"), 0),
            current_step=record.get("current_step") or "",
            provider=record.get("provider") or "",
            model=record.get("model") or "",
            retry_count=_safe_int(record.get("retry_count"), _safe_int((record.get("params") or {}).get("retry_count"), 0)),
            started_at=record.get("started_at") or "",
            completed_at=record.get("completed_at") or "",
            failed_at=record.get("failed_at") or "",
            cancel_requested=bool(record.get("cancel_requested")),
            last_safe_error=record.get("last_safe_error") or "",
            internal_error_ref=record.get("internal_error_ref") or "",
        )


class JobTracker:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        lease_seconds: int = 120,
        stale_after_seconds: int = 300,
        heartbeat_interval_seconds: float = 30.0,
        worker_id: str | None = None,
    ):
        self.db_path = db_path
        self.jobs: Dict[str, JobStatus] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.lease_seconds = max(1, lease_seconds)
        self.stale_after_seconds = max(1, stale_after_seconds)
        self.heartbeat_interval_seconds = max(0.01, heartbeat_interval_seconds)
        self.worker_id = worker_id or f"pid-{__import__('os').getpid()}-{uuid.uuid4().hex[:8]}"
        if self.db_path is not None:
            interrupted = mark_interrupted_mobile_jobs(
                self.db_path,
                stale_after_seconds=self.stale_after_seconds,
                include_queued=True,
            )
            if interrupted:
                record_operational_event(
                    self.db_path,
                    event_type="job_interrupted",
                    severity="warning",
                    source="job_tracker",
                    message=f"{interrupted} stale or queued job(s) interrupted",
                    details={"count": interrupted},
                )

    def _persist_job(self, job: JobStatus) -> None:
        if self.db_path is not None:
            persisted = save_mobile_job(self.db_path, job.to_record())
            reconciled = JobStatus.from_record(persisted)
            job.__dict__.update(reconciled.__dict__)

    def _load_job(self, job_id: str) -> JobStatus | None:
        if self.db_path is None:
            return None
        record = get_mobile_job(self.db_path, job_id)
        if not record:
            return None
        job = JobStatus.from_record(record)
        self.jobs[job.job_id] = job
        return job

    def create_job(
        self,
        job_type: str,
        target_ids: List[int] | None = None,
        total: int = 0,
        params: dict | None = None,
        status: str = "queued",
    ) -> JobStatus:
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id,
            job_type,
            target_ids,
            total,
            params,
            status=status,
            retry_count=_safe_int((params or {}).get("retry_count"), 0),
            provider=str((params or {}).get("provider_id") or ""),
            model=str((params or {}).get("model") or ""),
        )
        self.jobs[job_id] = job
        self._persist_job(job)
        if self.db_path is not None:
            record_job_log(
                self.db_path,
                job_id=job_id,
                event_type="created",
                state=job.state,
                step=job.current_step,
                message=f"{job_type} job created",
                details={"job_type": job_type, "target_count": len(job.target_ids), "retry_count": job.retry_count},
            )
        return job

    def get_job(self, job_id: str) -> JobStatus | None:
        if self.db_path is not None:
            mark_interrupted_mobile_jobs(
                self.db_path,
                stale_after_seconds=self.stale_after_seconds,
                include_queued=True,
            )
        return self.jobs.get(job_id) or self._load_job(job_id)

    def list_jobs(self, limit: int = 50) -> List[JobStatus]:
        if self.db_path is not None:
            mark_interrupted_mobile_jobs(
                self.db_path,
                stale_after_seconds=self.stale_after_seconds,
                include_queued=True,
            )
            jobs = [JobStatus.from_record(record) for record in list_mobile_jobs(self.db_path, limit)]
            for job in jobs:
                self.jobs[job.job_id] = job
            return jobs
        jobs = list(self.jobs.values())
        jobs.sort(key=lambda x: x.created_at, reverse=True)
        return jobs[:limit]

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        error: str | None = None,
        params: dict | None = None,
        state: str | None = None,
        current_book_id: int | None = None,
        current_chapter_id: int | None = None,
        current_chunk_index: int | None = None,
        total_chunks: int | None = None,
        current_step: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        cancel_requested: bool | None = None,
        last_safe_error: str | None = None,
        internal_error_ref: str | None = None,
    ) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        previous_status = job.status
        previous_state = job.state
        previous_step = job.current_step
        next_status = status if status is not None else job.status
        next_step = current_step if current_step is not None else job.current_step
        existing_state = job.state if status is None and current_step is None else ""
        next_state = state or normalize_job_state(next_status, current_step=next_step, existing_state=existing_state)
        if not is_valid_job_state_transition(job.state, next_state):
            logger.warning("Rejected invalid job state transition %s -> %s for %s", job.state, next_state, job_id)
            if self.db_path is not None:
                record_job_log(
                    self.db_path,
                    job_id=job_id,
                    event_type="invalid_transition",
                    state=job.state,
                    step=job.current_step,
                    message="Invalid job state transition rejected",
                    details={"from": job.state, "to": next_state},
                )
            return False
        if status is not None:
            job.status = status
        job.state = next_state
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
            job.last_safe_error = sanitize_job_error(error)
        if params is not None:
            job.params = params
            job.retry_count = _safe_int(params.get("retry_count"), job.retry_count)
        if current_book_id is not None:
            job.current_book_id = max(0, int(current_book_id))
        if current_chapter_id is not None:
            job.current_chapter_id = max(0, int(current_chapter_id))
        if current_chunk_index is not None:
            job.current_chunk_index = max(0, int(current_chunk_index))
        if total_chunks is not None:
            job.total_chunks = max(0, int(total_chunks))
        if current_step is not None:
            job.current_step = current_step
        if provider is not None:
            job.provider = provider
        if model is not None:
            job.model = model
        if cancel_requested is not None:
            job.cancel_requested = cancel_requested
        if last_safe_error is not None:
            job.last_safe_error = sanitize_job_error(last_safe_error)
        if internal_error_ref is not None:
            job.internal_error_ref = internal_error_ref
        job.updated_at = datetime.now(timezone.utc).isoformat()
        if status == "running" and not job.started_at:
            job.started_at = job.updated_at
        if status == "completed":
            job.completed_at = job.updated_at
            job.finished_at = job.updated_at
        elif status == "failed":
            job.failed_at = job.updated_at
            job.finished_at = job.updated_at
        elif status in ("interrupted", "cancelled", "canceled"):
            job.finished_at = job.updated_at
        self._persist_job(job)
        if self.db_path is not None and (job.state != previous_state or job.current_step != previous_step or status is not None):
            record_job_log(
                self.db_path,
                job_id=job_id,
                event_type="state_transition",
                state=job.state,
                step=job.current_step,
                message=job.message or job.error or f"Job state {job.state}",
                details={
                    "from_status": previous_status,
                    "to_status": job.status,
                    "from_state": previous_state,
                    "to_state": job.state,
                    "progress": job.progress,
                    "total": job.total,
                    "chapter_id": job.current_chapter_id,
                    "provider": job.provider,
                    "model": job.model,
                },
            )
        if (
            self.db_path is not None
            and job.status in {"failed", "interrupted"}
            and previous_status != job.status
        ):
            record_operational_event(
                self.db_path,
                event_type="job_failure" if job.status == "failed" else "job_interrupted",
                severity="error" if job.status == "failed" else "warning",
                source="job_tracker",
                message=job.error or job.message or f"Job {job.status}",
                job_id=job_id,
                details={"job_type": job.job_type, "status": job.status},
            )
        return True

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        is_database_backed_backup = job.job_type == "backup" and self.db_path is not None
        if self.db_path is not None:
            request_cancel_mobile_job(
                self.db_path,
                job_id=job_id,
                terminal_if_pending=not is_database_backed_backup,
            )
            job.cancel_requested = True
            record_job_log(
                self.db_path,
                job_id=job_id,
                event_type="cancel_requested",
                state=job.state,
                step=job.current_step,
                message="Cancel requested",
            )
        if not is_database_backed_backup:
            self.update_job(job_id, cancel_requested=True)
        # Cancel the asyncio task if it exists
        task = self._tasks.get(job_id)
        if job.job_type == "backup":
            # Backup creation runs in a worker thread, which asyncio task
            # cancellation cannot stop. Let its cooperative callback observe
            # this durable flag before the directory lock is released.
            if is_database_backed_backup:
                # The owning coordinator must publish the dedicated terminal
                # event, even when this tracker has no process-local task.
                return True
            if task and not task.done():
                return True
            refreshed = self.get_job(job_id)
            if refreshed and refreshed.status in {"queued", "pending", "retrying"}:
                return self.update_job(
                    job_id,
                    status="cancelled",
                    message="Job cancelled before claim",
                    cancel_requested=True,
                )
            return True
        if task and not task.done():
            task.cancel()
            return True
        refreshed = self.get_job(job_id)
        if refreshed and refreshed.status in {"queued", "pending", "retrying"}:
            return self.update_job(job_id, status="cancelled", message="Job cancelled before claim", cancel_requested=True)
        return True

    def start_background_task(self, job_id: str, coro) -> None:
        lease_token = uuid.uuid4().hex

        async def heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(self.heartbeat_interval_seconds)
                if self.db_path is None:
                    continue
                ok = heartbeat_mobile_job_lease(
                    self.db_path,
                    job_id=job_id,
                    lease_token=lease_token,
                    lease_seconds=self.lease_seconds,
                )
                if not ok:
                    logger.warning("Job %s heartbeat lost lease", job_id)
                    return

        async def wrapper():
            heartbeat_task: asyncio.Task | None = None
            claimed = False
            try:
                if self.db_path is not None:
                    claimed = claim_mobile_job(
                        self.db_path,
                        job_id=job_id,
                        worker_id=self.worker_id,
                        lease_token=lease_token,
                        lease_seconds=self.lease_seconds,
                    )
                    if not claimed:
                        logger.warning("Job %s was not claimed by worker %s", job_id, self.worker_id)
                        record_operational_event(
                            self.db_path,
                            event_type="job_claim_skipped",
                            severity="warning",
                            source="job_tracker",
                            message="Duplicate job execution prevented",
                            job_id=job_id,
                            details={"worker_id": self.worker_id},
                        )
                        if hasattr(coro, "close"):
                            coro.close()
                        return
                    self.jobs.pop(job_id, None)
                    self._load_job(job_id)
                    heartbeat_task = asyncio.create_task(heartbeat_loop())
                else:
                    self.update_job(job_id, status="running")
                await coro
                # Update job to completed if not already failed/cancelled
                job = self.jobs.get(job_id)
                if job and job.status not in ("completed", "failed", "interrupted", "cancelled"):
                    self.update_job(job_id, status="completed", progress=job.total, message="Job completed")
            except asyncio.CancelledError:
                self.update_job(job_id, status="cancelled", message="Job cancelled", cancel_requested=True)
            except Exception:
                logger.exception("Background job %s failed", job_id)
                self.update_job(
                    job_id,
                    status="failed",
                    error=GENERIC_JOB_FAILURE_DETAIL,
                    message=GENERIC_JOB_FAILURE_DETAIL,
                )
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                if claimed and self.db_path is not None:
                    release_mobile_job_lease(self.db_path, job_id=job_id, lease_token=lease_token)
                self._tasks.pop(job_id, None)

        task = asyncio.create_task(wrapper())
        self._tasks[job_id] = task


_SHARED_TRACKERS: dict[str, JobTracker] = {}
_SOURCE_IMPORT_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def get_shared_job_tracker(db_path: Path) -> JobTracker:
    key = str(db_path)
    tracker = _SHARED_TRACKERS.get(key)
    if tracker is None or tracker.db_path != db_path:
        tracker = JobTracker(
            db_path=db_path,
            stale_after_seconds=mobile_settings.job_stale_after_seconds,
            heartbeat_interval_seconds=mobile_settings.job_heartbeat_interval_seconds,
        )
        _SHARED_TRACKERS[key] = tracker
    return tracker


def _get_source_import_semaphore(source_id: str, max_concurrency: int) -> asyncio.Semaphore:
    semaphore = _SOURCE_IMPORT_SEMAPHORES.get(source_id)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, max_concurrency))
        _SOURCE_IMPORT_SEMAPHORES[source_id] = semaphore
    return semaphore


class JobService:
    def __init__(self, pipeline_service: PipelineService, tracker: JobTracker | None = None):
        self.pipeline = pipeline_service
        self.tracker = tracker or JobTracker()

    @staticmethod
    def _resolve_preset_chunk_size(preset_id: str | None, chunk_size: int | None) -> int | None:
        if chunk_size is not None:
            if chunk_size <= 0:
                raise ValueError("chunk_size must be greater than 0")
            return chunk_size
        if not preset_id:
            return None
        return get_translation_preset(preset_id).chunk_size

    @staticmethod
    def _initial_stage_timings(preset_id: str | None) -> list[dict]:
        if not preset_id:
            return [{"stage": "translate", "status": "pending", "elapsed_ms": 0}]

        preset = get_translation_preset(preset_id)
        stages = ["translate"]
        if preset.polish_enabled:
            stages.append("polish")
        if preset.qa_enabled:
            stages.append("qa")
        if preset.rewrite_failed:
            stages.append("rewrite")
        return [{"stage": stage, "status": "pending", "elapsed_ms": 0} for stage in stages]

    def _update_stage_timing(
        self,
        job_id: str,
        *,
        stage: str,
        status: str,
        provider_id: str = "",
        model: str = "",
        elapsed_ms: int = 0,
        error: str = "",
    ) -> None:
        job = self.tracker.get_job(job_id)
        if not job:
            return

        next_params = dict(job.params or {})
        timings = [dict(item) for item in next_params.get("stage_timings") or []]
        entry = next((item for item in timings if item.get("stage") == stage), None)
        if entry is None:
            entry = {"stage": stage, "status": "pending", "elapsed_ms": 0}
            timings.append(entry)

        entry["status"] = status
        entry["provider_id"] = provider_id
        entry["model"] = model
        entry["error"] = error
        if elapsed_ms > 0:
            entry["elapsed_ms"] = max(0, int(entry.get("elapsed_ms") or 0)) + elapsed_ms
        else:
            entry["elapsed_ms"] = max(0, int(entry.get("elapsed_ms") or 0))

        next_params["stage_timings"] = timings
        next_params["active_stage"] = stage if status == "running" else ""
        self.tracker.update_job(job_id, params=next_params)

    def _stage_timing_callback(self, job_id: str):
        def callback(event: dict) -> None:
            stage = str(event.get("stage") or "unknown")
            status = str(event.get("status") or "unknown")
            self._update_stage_timing(
                job_id,
                stage=stage,
                status=status,
                provider_id=str(event.get("provider_id") or ""),
                model=str(event.get("model") or ""),
                elapsed_ms=int(event.get("elapsed_ms") or 0),
                error=str(event.get("error") or ""),
            )
            self.tracker.update_job(
                job_id,
                current_step=state_for_stage(stage, status),
                provider=str(event.get("provider_id") or ""),
                model=str(event.get("model") or ""),
            )

        return callback

    def _job_cancel_requested(self, job_id: str) -> bool:
        job = self.tracker.get_job(job_id)
        if self.tracker.db_path is not None:
            persisted = get_mobile_job(self.tracker.db_path, job_id)
            if persisted is not None and (
                bool(persisted.get("cancel_requested"))
                or str(persisted.get("status") or "").lower() in {"cancelled", "canceled"}
            ):
                if job is not None:
                    job.cancel_requested = True
                return True
        if not job:
            return True
        return bool(job.cancel_requested or job.status in {"cancelled", "canceled"})

    def _cancel_if_requested(self, job_id: str, message: str = "Job cancelled by user") -> bool:
        if not self._job_cancel_requested(job_id):
            return False
        self.tracker.update_job(job_id, status="cancelled", message=message, cancel_requested=True)
        return True

    def _estimate_chapter_chunks(self, chapter_id: int, chunk_size: int | None) -> int:
        if not chunk_size or chunk_size <= 0:
            return 0
        try:
            source_text = self.pipeline.get_chapter_source(chapter_id)
        except Exception:
            return 0
        return max(1, (len(source_text) + chunk_size - 1) // chunk_size) if source_text else 0

    def _record_provider_attempt(
        self,
        *,
        job_id: str,
        chapter_id: int | None,
        provider_id: str | None,
        model: str | None,
        status: str,
        error: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        db_path = getattr(self.pipeline, "db_path", None)
        if db_path is None:
            return

        try:
            record_job_attempt(
                Path(db_path),
                job_id=job_id,
                chapter_id=chapter_id,
                provider_id=provider_id or "default",
                model=model or "default",
                status=status,
                error=error,
                elapsed_ms=max(0, elapsed_ms),
            )
            if status in {"failed", "retrying"}:
                record_operational_event(
                    Path(db_path),
                    event_type="provider_failure",
                    severity="error" if status == "failed" else "warning",
                    source="job_service",
                    message="Provider attempt failed. Check server logs.",
                    job_id=job_id,
                    details={
                        "chapter_id": chapter_id,
                        "provider_id": provider_id or "default",
                        "model": model or "default",
                        "status": status,
                    },
                )
        except Exception:
            logger.warning("Failed to record provider attempt for job %s", job_id, exc_info=True)

    def start_translate_job(
        self,
        book_id: int | None = None,
        chapter_ids: List[int] | None = None,
        limit: int = 15,
        model: str | None = None,
        host: str | None = None,
        provider_id: str | None = None,
        api_key: str | None = None,
        style_profile_id: str | None = None,
        preset_id: str | None = None,
        chunk_size: int | None = None,
        retry_of_job_id: str = "",
        retry_count: int = 0,
        previous_error: str = "",
        skipped_completed_chapter_ids: List[int] | None = None,
    ) -> str:
        resolved_chunk_size = self._resolve_preset_chunk_size(preset_id, chunk_size)

        # Determine target chapters
        if chapter_ids:
            target_ids = chapter_ids
        elif book_id is not None:
            chapters = self._chapters_in_batch_order(self.pipeline.list_chapters(book_id))
            target_ids = [c["id"] for c in chapters if self._chapter_needs_translation(c)][:limit]
        else:
            chapters = self._chapters_in_batch_order(self.pipeline.list_chapters())
            target_ids = [c["id"] for c in chapters if self._chapter_needs_translation(c)][:limit]

        if not target_ids:
            # Create a dummy job that completes immediately
            job = self.tracker.create_job("translate", [], 0)
            self.tracker.update_job(job.job_id, status="completed", message="No chapters to translate")
            return job.job_id

        job = self.tracker.create_job(
            "translate",
            target_ids,
            len(target_ids),
            {
                "model": model,
                "host": host,
                "provider_id": provider_id,
                "style_profile_id": style_profile_id,
                "preset_id": preset_id,
                "chunk_size": resolved_chunk_size,
                "stage_timings": self._initial_stage_timings(preset_id),
                "retry_of_job_id": retry_of_job_id,
                "retry_count": max(0, retry_count),
                "previous_error": previous_error,
                "skipped_completed_chapter_ids": skipped_completed_chapter_ids or [],
            },
            status="retrying" if retry_of_job_id else "queued",
        )
        self.tracker.start_background_task(
            job.job_id,
            self._run_translate_job(
                job.job_id,
                target_ids,
                model,
                host,
                api_key,
                style_profile_id,
                preset_id,
                resolved_chunk_size,
            ),
        )
        return job.job_id

    @staticmethod
    def _chapter_has_completed_translation(chapter: dict | None) -> bool:
        if not chapter:
            return False
        if str(chapter.get("status") or "") not in TRANSLATED_CHAPTER_STATUSES:
            return False
        translated_path = str(chapter.get("translated_text_path") or "").strip()
        return bool(translated_path and Path(translated_path).exists())

    @staticmethod
    def _chapters_in_batch_order(chapters: list[dict]) -> list[dict]:
        return sorted(
            chapters,
            key=lambda chapter: (
                _safe_int(chapter.get("book_id"), 0),
                _safe_int(chapter.get("chapter_number"), 0),
                _safe_int(chapter.get("id"), 0),
            ),
        )

    @classmethod
    def _chapter_needs_translation(cls, chapter: dict | None) -> bool:
        if not chapter or cls._chapter_has_completed_translation(chapter):
            return False

        source_path = str(chapter.get("cleaned_text_path") or chapter.get("raw_text_path") or "").strip()
        if source_path:
            return Path(source_path).exists()

        status = str(chapter.get("status") or "").lower()
        return status in {"cleaned", "raw", "imported"}

    def retry_failed_translation_job(self, job_id: str, api_key: str | None = None) -> str:
        failed_job = self.tracker.get_job(job_id)
        if failed_job is None:
            raise LookupError("Job not found")
        if failed_job.job_type != "translate":
            raise ValueError("Only translation jobs can be retried")
        if failed_job.status not in {"failed", "interrupted"}:
            raise ValueError("Only failed or interrupted translation jobs can be retried")
        if not failed_job.target_ids:
            raise ValueError("Failed job has no saved chapter targets")

        original_params = dict(failed_job.params or {})
        previous_error = failed_job.error or failed_job.message or str(original_params.get("previous_error") or "")
        retry_count = _safe_int(original_params.get("retry_count"), 0) + 1
        retry_root_job_id = str(original_params.get("retry_of_job_id") or failed_job.job_id)

        retry_chapter_ids: list[int] = []
        skipped_completed_chapter_ids: list[int] = []
        for chapter_id in failed_job.target_ids:
            chapter = self.pipeline.get_chapter(chapter_id)
            if self._chapter_has_completed_translation(chapter):
                skipped_completed_chapter_ids.append(chapter_id)
                continue
            if chapter is not None:
                retry_chapter_ids.append(chapter_id)

        retry_metadata = {
            "retry_of_job_id": retry_root_job_id,
            "retry_count": retry_count,
            "previous_error": previous_error,
            "skipped_completed_chapter_ids": skipped_completed_chapter_ids,
        }

        if not retry_chapter_ids:
            retry_job = self.tracker.create_job("translate", [], 0, retry_metadata)
            self.tracker.update_job(
                retry_job.job_id,
                status="completed",
                message="No incomplete chapters to retry",
            )
            retry_job_id = retry_job.job_id
        else:
            retry_job_id = self.start_translate_job(
                chapter_ids=retry_chapter_ids,
                model=original_params.get("model"),
                host=original_params.get("host"),
                provider_id=original_params.get("provider_id"),
                api_key=api_key,
                style_profile_id=original_params.get("style_profile_id"),
                preset_id=original_params.get("preset_id"),
                chunk_size=original_params.get("chunk_size"),
                **retry_metadata,
            )
            self.tracker.update_job(
                retry_job_id,
                message=f"Retry attempt {retry_count} for job {failed_job.job_id}",
            )

        next_original_params = dict(original_params)
        next_original_params["retry_count"] = retry_count
        next_original_params["last_retry_job_id"] = retry_job_id
        self.tracker.update_job(failed_job.job_id, params=next_original_params)
        return retry_job_id

    def start_import_url_job(
        self,
        *,
        url: str,
        chapters: list[dict],
        managed_source_id: str = "",
        title: str = "",
        author: str = "",
        source: str = "",
        retry_limit: int = 2,
    ) -> str:
        source_url = validate_public_http_url(url)
        source_policy = get_source_policy(source_url)
        if source_policy is None:
            raise SourceAdapterError("Unsupported source domain")

        normalized_chapters: list[dict] = []
        for chapter in chapters:
            chapter_data = dict(chapter)
            chapter_url = validate_public_http_url(str(chapter_data.get("url") or ""))
            chapter_policy = get_source_policy(chapter_url)
            if chapter_policy is None or chapter_policy.source_id != source_policy.source_id:
                raise SourceAdapterError("Selected chapters must belong to the same supported source")
            if not chapter_url_matches_source_book(source_url, chapter_url):
                raise SourceAdapterError("Selected chapters must belong to the same source book")
            chapter_data["url"] = chapter_url
            normalized_chapters.append(chapter_data)
        chapters = normalized_chapters
        retry_limit = min(retry_limit, source_policy.retry_limit)

        target_ids = list(range(len(chapters)))
        job = self.tracker.create_job(
            "import_url",
            target_ids,
            len(chapters),
            {
                "url": source_url,
                "managed_source_id": managed_source_id,
                "title": title,
                "author": author,
                "source": source,
                "chapters": chapters,
                "retry_limit": retry_limit,
            },
        )
        if not chapters:
            self.tracker.update_job(job.job_id, status="completed", message="No source chapters selected")
            return job.job_id

        self.tracker.start_background_task(
            job.job_id,
            self._run_import_url_job(
                job.job_id,
                source_url=source_url,
                chapters=chapters,
                title=title,
                author=author,
                source=source,
                retry_limit=retry_limit,
            ),
        )
        return job.job_id

    async def _run_import_url_job(
        self,
        job_id: str,
        *,
        source_url: str,
        chapters: list[dict],
        title: str,
        author: str,
        source: str,
        retry_limit: int,
    ) -> None:
        imported_ids: list[int] = []
        errors: list[str] = []
        policy = get_source_policy(source_url)
        semaphore = _get_source_import_semaphore(policy.source_id, policy.max_concurrency) if policy else None
        if semaphore is not None:
            await semaphore.acquire()
        self.tracker.update_job(job_id, status="running", progress=0, message="Starting URL import", current_step="LOADING_SOURCE")

        try:
            for idx, chapter in enumerate(chapters):
                if self._cancel_if_requested(job_id):
                    return

                chapter_url = str(chapter.get("url") or "")
                chapter_title = str(chapter.get("title") or "")
                chapter_number = int(chapter.get("chapter_number") or idx + 1)
                last_error = ""

                for attempt in range(retry_limit + 1):
                    if self._cancel_if_requested(job_id):
                        return
                    try:
                        self.tracker.update_job(
                            job_id,
                            progress=idx,
                            message=f"Importing chapter {chapter_number}: {chapter_title or chapter_url}",
                            current_step="LOADING_SOURCE",
                            current_chunk_index=idx,
                            total_chunks=len(chapters),
                        )
                        result = await asyncio.to_thread(
                            self.pipeline.import_from_source_url,
                            book_title=title,
                            author=author,
                            source=source,
                            source_url=source_url,
                            chapter_url=chapter_url,
                            chapter_number=chapter_number,
                            chapter_title=chapter_title,
                        )
                        imported_ids.append(int(result["chapter_id"]))
                        self.tracker.update_job(job_id, current_step="SAVING_CHAPTER")
                        last_error = ""
                        break
                    except SourceBlockedError as exc:
                        self.tracker.update_job(
                            job_id,
                            status="failed",
                            progress=idx,
                            message="Source blocked; import stopped",
                            error=str(exc),
                        )
                        return
                    except Exception as exc:
                        last_error = str(exc)
                        logger.warning(
                            "URL import job %s failed on chapter %s attempt %s",
                            job_id,
                            chapter_number,
                            attempt + 1,
                            exc_info=True,
                        )
                        if attempt < retry_limit:
                            await asyncio.sleep(min(2.0, 0.25 * (attempt + 1)))

                if last_error:
                    errors.append(f"chapter {chapter_number}: {IMPORT_CHAPTER_FAILURE_DETAIL}")
                self.tracker.update_job(job_id, progress=idx + 1)
                if not last_error and policy and idx < len(chapters) - 1:
                    await asyncio.sleep(policy.delay_seconds)

            if errors:
                message = f"Imported {len(imported_ids)}/{len(chapters)} chapters; {len(errors)} failed"
                self.tracker.update_job(
                    job_id,
                    status="failed" if not imported_ids else "completed",
                    progress=len(chapters),
                    message=message,
                    error="\n".join(errors[:5]),
                )
                return

            self.tracker.update_job(
                job_id,
                status="completed",
                progress=len(chapters),
                message=f"Imported {len(imported_ids)} chapters",
            )
        finally:
            if semaphore is not None:
                semaphore.release()

    async def _run_translate_job(
        self,
        job_id: str,
        chapter_ids: List[int],
        model: str | None,
        host: str | None,
        api_key: str | None,
        style_profile_id: str | None,
        preset_id: str | None,
        chunk_size: int | None,
    ) -> None:
        for idx, chapter_id in enumerate(chapter_ids):
            if self._cancel_if_requested(job_id):
                break
            job = self.tracker.get_job(job_id)
            if not job:
                break
            for attempt in range(TRANSLATE_CHAPTER_MAX_RETRIES + 1):
                if self._cancel_if_requested(job_id):
                    return
                started_at = time.monotonic()
                resolved_preset_id = preset_id or job.params.get("preset_id")
                try:
                    chapter = self.pipeline.get_chapter(chapter_id)
                    book_id = chapter["book_id"] if chapter else 0
                    total_chunks = self._estimate_chapter_chunks(chapter_id, chunk_size)
                    self.tracker.update_job(
                        job_id,
                        status="running",
                        progress=idx,
                        message=f"Translating chapter {chapter_id}",
                        current_book_id=book_id,
                        current_chapter_id=chapter_id,
                        current_chunk_index=0,
                        total_chunks=total_chunks,
                        current_step="TRANSLATING",
                        provider=str(job.params.get("provider_id") or ""),
                        model=model or "",
                    )
                    resolved_style_profile_id = style_profile_id or job.params.get("style_profile_id")
                    if resolved_preset_id:
                        await asyncio.to_thread(
                            self.pipeline.translate_chapter_with_pipeline,
                            book_id=book_id,
                            chapter_id=chapter_id,
                            preset_id=resolved_preset_id,
                            job_id=job_id,
                            style_profile_id=resolved_style_profile_id,
                            chunk_size=chunk_size,
                            stage_callback=self._stage_timing_callback(job_id),
                            cancel_check=lambda: self._job_cancel_requested(job_id),
                        )
                    else:
                        self._update_stage_timing(
                            job_id,
                            stage="translate",
                            status="running",
                            provider_id=str(job.params.get("provider_id") or ""),
                            model=model or "",
                        )
                        await asyncio.to_thread(
                            self.pipeline.translate_chapter,
                            book_id=book_id,
                            chapter_id=chapter_id,
                            model=model,
                            host=host,
                            api_key=api_key,
                            provider_id=job.params.get("provider_id"),
                            job_id=job_id,
                            style_profile_id=resolved_style_profile_id,
                            chunk_size=chunk_size,
                            cancel_check=lambda: self._job_cancel_requested(job_id),
                        )
                    if self._cancel_if_requested(job_id):
                        return
                    db_chapter = get_chapter_by_id(self.pipeline.db_path, chapter_id)
                    if db_chapter:
                        try:
                            from app.mobile_api.services.glossary_service import GlossaryService
                            from app.mobile_api.services.qa_service import QAService

                            self.tracker.update_job(
                                job_id,
                                status="running",
                                progress=idx,
                                message=f"Running glossary and QA follow-up for chapter {chapter_id}",
                                current_step="QA_CHECKING",
                            )
                            extracted = await asyncio.to_thread(
                                GlossaryService.from_db_path(self.pipeline.db_path).extract_chapter_terms,
                                book_id,
                                chapter_id,
                            )
                            qa_report = await asyncio.to_thread(
                                QAService(self.pipeline).run_deterministic_qa,
                                book_id,
                                chapter_id,
                                job_id,
                            )
                            record_job_log(
                                self.pipeline.db_path,
                                job_id=job_id,
                                event_type="qa_completed",
                                state="QA_CHECKING",
                                step="QA_CHECKING",
                                message="QA and glossary follow-up completed",
                                details={
                                    "chapter_id": chapter_id,
                                    "overall_status": qa_report.get("overall_status"),
                                    "warning_count": len(qa_report.get("issues") or []),
                                    "glossary_candidates_created": extracted.get("created", 0),
                                    "glossary_candidates_updated": extracted.get("updated", 0),
                                },
                            )
                        except Exception:
                            logger.exception("QA/glossary follow-up failed for job %s chapter %s", job_id, chapter_id)
                            record_job_log(
                                self.pipeline.db_path,
                                job_id=job_id,
                                event_type="qa_followup_failed",
                                state="QA_CHECKING",
                                step="QA_CHECKING",
                                message="QA/glossary follow-up failed; translation remains saved",
                                details={"chapter_id": chapter_id},
                            )
                    if not resolved_preset_id:
                        elapsed_ms = int((time.monotonic() - started_at) * 1000)
                        self._update_stage_timing(
                            job_id,
                            stage="translate",
                            status="success",
                            provider_id=str(job.params.get("provider_id") or ""),
                            model=model or "",
                            elapsed_ms=elapsed_ms,
                        )
                        self._record_provider_attempt(
                            job_id=job_id,
                            chapter_id=chapter_id,
                            provider_id=job.params.get("provider_id"),
                            model=model,
                            status="success",
                            elapsed_ms=elapsed_ms,
                        )
                    self.tracker.update_job(job_id, progress=idx + 1, current_chunk_index=total_chunks)
                    break
                except Exception as exc:
                    if self._job_cancel_requested(job_id):
                        self.tracker.update_job(job_id, status="cancelled", message="Job cancelled", cancel_requested=True)
                        return
                    if attempt < TRANSLATE_CHAPTER_MAX_RETRIES and is_retryable_provider_error(exc):
                        if not resolved_preset_id:
                            elapsed_ms = int((time.monotonic() - started_at) * 1000)
                            self._update_stage_timing(
                                job_id,
                                stage="translate",
                                status="retrying",
                                provider_id=str(job.params.get("provider_id") or ""),
                                model=model or "",
                                elapsed_ms=elapsed_ms,
                                error=str(exc),
                            )
                            self._record_provider_attempt(
                                job_id=job_id,
                                chapter_id=chapter_id,
                                provider_id=job.params.get("provider_id"),
                                model=model,
                                status="retrying",
                                error=str(exc),
                                elapsed_ms=elapsed_ms,
                            )
                        delay = TRANSLATE_CHAPTER_RETRY_DELAYS[
                            min(attempt, len(TRANSLATE_CHAPTER_RETRY_DELAYS) - 1)
                        ]
                        self.tracker.update_job(
                            job_id,
                            progress=idx,
                            message=(
                                f"Provider temporarily unavailable on chapter {chapter_id}; "
                                f"retrying in {delay:.0f}s ({attempt + 1}/{TRANSLATE_CHAPTER_MAX_RETRIES})"
                            ),
                        )
                        await asyncio.sleep(delay)
                        continue

                    if not resolved_preset_id:
                        elapsed_ms = int((time.monotonic() - started_at) * 1000)
                        self._update_stage_timing(
                            job_id,
                            stage="translate",
                            status="failed",
                            provider_id=str(job.params.get("provider_id") or ""),
                            model=model or "",
                            elapsed_ms=elapsed_ms,
                            error=str(exc),
                        )
                        self._record_provider_attempt(
                            job_id=job_id,
                            chapter_id=chapter_id,
                            provider_id=job.params.get("provider_id"),
                            model=model,
                            status="failed",
                            error=str(exc),
                            elapsed_ms=elapsed_ms,
                        )
                    logger.exception("Translation job %s failed on chapter %s", job_id, chapter_id)
                    self.tracker.update_job(
                        job_id,
                        status="failed",
                        error=TRANSLATION_JOB_FAILURE_DETAIL,
                        message=(
                            f"Translation failed on chapter {chapter_id}. "
                            "Check provider settings and server logs."
                        ),
                    )
                    return

    def start_tts_job(
        self,
        book_id: int | None = None,
        chapter_ids: List[int] | None = None,
        limit: int = 15,
        voice: str | None = None,
        rate: str = "-5%",
        volume: str = "+0%",
    ) -> str:
        require_tts_runtime_available()

        # Determine target chapters with translations
        if chapter_ids:
            target_ids = chapter_ids
        elif book_id is not None:
            chapters = self._chapters_in_batch_order(self.pipeline.list_chapters(book_id))
            target_ids = [c["id"] for c in chapters if c.get("translated_text_path") and not c.get("audio_path")][:limit]
        else:
            chapters = self._chapters_in_batch_order(self.pipeline.list_chapters())
            target_ids = [c["id"] for c in chapters if c.get("translated_text_path") and not c.get("audio_path")][:limit]

        if not target_ids:
            job = self.tracker.create_job("tts", [], 0)
            self.tracker.update_job(job.job_id, status="completed", message="No chapters for TTS")
            return job.job_id

        job = self.tracker.create_job("tts", target_ids, len(target_ids), {"voice": voice, "rate": rate, "volume": volume})
        self.tracker.start_background_task(
            job.job_id,
            self._run_tts_job(job.job_id, target_ids, voice, rate, volume),
        )
        return job.job_id

    async def _run_tts_job(
        self,
        job_id: str,
        chapter_ids: List[int],
        voice: str | None,
        rate: str,
        volume: str,
    ) -> None:
        for idx, chapter_id in enumerate(chapter_ids):
            if self._cancel_if_requested(job_id):
                break
            try:
                chapter = self.pipeline.get_chapter(chapter_id)
                book_id = chapter["book_id"] if chapter else 0
                self.tracker.update_job(
                    job_id,
                    status="running",
                    progress=idx,
                    message=f"Generating audio for chapter {chapter_id}",
                    current_book_id=book_id,
                    current_chapter_id=chapter_id,
                    current_step="GENERATING_TTS",
                )
                if chapter:
                    await asyncio.to_thread(
                        self.pipeline.generate_audio,
                        book_id=chapter["book_id"],
                        chapter_id=chapter_id,
                        voice=voice,
                        rate=rate,
                        volume=volume,
                        job_id=job_id,
                        cancel_check=lambda: self._job_cancel_requested(job_id),
                        progress_callback=lambda percent, note: self.tracker.update_job(
                            job_id,
                            progress=max(idx, min(idx + 1, idx + percent // 100)),
                            current_step="GENERATING_TTS",
                            message=note,
                        ),
                    )
                if self._cancel_if_requested(job_id):
                    return
                self.tracker.update_job(job_id, progress=idx + 1)
            except Exception:
                logger.exception("TTS job %s failed on chapter %s", job_id, chapter_id)
                self.tracker.update_job(
                    job_id,
                    status="failed",
                    error=TTS_JOB_FAILURE_DETAIL,
                    message=f"TTS failed on chapter {chapter_id}. Check TTS settings and server logs.",
                )
                return

    def start_daily_job(self, limit: int = 15) -> str:
        job = self.tracker.create_job("daily", None, limit)
        self.tracker.start_background_task(
            job.job_id,
            self._run_daily_job(job.job_id, limit),
        )
        return job.job_id

    async def _run_daily_job(self, job_id: str, limit: int) -> None:
        job = self.tracker.get_job(job_id)
        if not job:
            return
        try:
            self.tracker.update_job(job_id, status="running", progress=0, message="Starting daily batch")
            # Get pending chapters
            pending = self.pipeline.get_pending_chapters(limit=limit)
            self.tracker.update_job(job_id, progress=10, message=f"Found {len(pending)} pending chapters")
            # Translate them
            for idx, chapter in enumerate(pending):
                if self._cancel_if_requested(job_id):
                    return
                chapter_id = chapter["id"]
                started_at = time.monotonic()
                chapter_started = self.tracker.update_job(
                    job_id,
                    status="running",
                    progress=10 + int((idx / len(pending)) * 80) if pending else 90,
                    message=f"Translating chapter {chapter_id}",
                    current_book_id=chapter["book_id"],
                    current_chapter_id=chapter_id,
                    current_step="TRANSLATING",
                )
                if not chapter_started or self._cancel_if_requested(job_id):
                    return
                try:
                    await asyncio.to_thread(
                        self.pipeline.translate_chapter,
                        book_id=chapter["book_id"],
                        chapter_id=chapter_id,
                        job_id=job_id,
                    )
                    self._record_provider_attempt(
                        job_id=job_id,
                        chapter_id=chapter_id,
                        provider_id=None,
                        model=None,
                        status="success",
                        elapsed_ms=int((time.monotonic() - started_at) * 1000),
                    )
                    if self._cancel_if_requested(job_id):
                        return
                except Exception as exc:
                    self._record_provider_attempt(
                        job_id=job_id,
                        chapter_id=chapter_id,
                        provider_id=None,
                        model=None,
                        status="failed",
                        error=str(exc),
                        elapsed_ms=int((time.monotonic() - started_at) * 1000),
                    )
                    if self._cancel_if_requested(job_id):
                        return
                    raise
            if self._cancel_if_requested(job_id):
                return
            self.tracker.update_job(job_id, status="completed", progress=100, message="Daily batch completed")
        except Exception:
            logger.exception("Daily job %s failed", job_id)
            self.tracker.update_job(
                job_id,
                status="failed",
                error=DAILY_JOB_FAILURE_DETAIL,
                message=DAILY_JOB_FAILURE_DETAIL,
            )

    def start_qa_job(
        self,
        book_id: int | None = None,
        chapter_ids: List[int] | None = None,
        limit: int = 15,
        model: str | None = None,
        host: str | None = None,
        api_key: str | None = None,
        provider_id: str | None = None,
    ) -> str:
        # Determine target chapters with translations but no QA
        if chapter_ids:
            target_ids = chapter_ids
        elif book_id is not None:
            chapters = self.pipeline.list_chapters(book_id)
            target_ids = [c["id"] for c in chapters if c.get("translated_text_path")][:limit]
        else:
            chapters = self.pipeline.list_chapters()
            target_ids = [c["id"] for c in chapters if c.get("translated_text_path")][:limit]

        if not target_ids:
            job = self.tracker.create_job("qa", [], 0)
            self.tracker.update_job(job.job_id, status="completed", message="No chapters for QA")
            return job.job_id

        job = self.tracker.create_job(
            "qa",
            target_ids,
            len(target_ids),
            {"model": model, "host": host, "provider_id": provider_id},
        )
        self.tracker.start_background_task(
            job.job_id,
            self._run_qa_job(job.job_id, target_ids, model, host, api_key, provider_id),
        )
        return job.job_id

    async def _run_qa_job(
        self,
        job_id: str,
        chapter_ids: List[int],
        model: str | None,
        host: str | None,
        api_key: str | None,
        provider_id: str | None,
    ) -> None:
        for idx, chapter_id in enumerate(chapter_ids):
            if self._cancel_if_requested(job_id):
                break
            started_at = time.monotonic()
            try:
                chapter = self.pipeline.get_chapter(chapter_id)
                book_id = chapter["book_id"] if chapter else 0
                self.tracker.update_job(
                    job_id,
                    status="running",
                    progress=idx,
                    message=f"Running QA on chapter {chapter_id}",
                    current_book_id=book_id,
                    current_chapter_id=chapter_id,
                    current_step="QA_CHECKING",
                    provider=provider_id or "",
                    model=model or "",
                )
                if chapter:
                    report = await asyncio.to_thread(
                        self.pipeline.run_qa_check,
                        book_id=chapter["book_id"],
                        chapter_id=chapter_id,
                        model=model,
                        host=host,
                        api_key=api_key,
                        provider_id=provider_id,
                        job_id=job_id,
                    )
                    save_qa_report(
                        self.pipeline.db_path,
                        book_id=chapter["book_id"],
                        chapter_id=chapter_id,
                        quality_score=report.get("quality_score", 0),
                        fidelity_score=report.get("fidelity_score", 0),
                        style_score=report.get("style_score", 0),
                        glossary_score=report.get("glossary_score", 0),
                        audiobook_score=report.get("audiobook_score", 0),
                        verdict=report.get("verdict", "UNKNOWN"),
                        report_json=json.dumps(report, ensure_ascii=False),
                    )
                    self._record_provider_attempt(
                        job_id=job_id,
                        chapter_id=chapter_id,
                        provider_id=provider_id,
                        model=model,
                        status="success",
                        elapsed_ms=int((time.monotonic() - started_at) * 1000),
                    )
                self.tracker.update_job(job_id, progress=idx + 1)
            except Exception as exc:
                self._record_provider_attempt(
                    job_id=job_id,
                    chapter_id=chapter_id,
                    provider_id=provider_id,
                    model=model,
                    status="failed",
                    error=str(exc),
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
                logger.exception("QA job %s failed on chapter %s", job_id, chapter_id)
                self.tracker.update_job(
                    job_id,
                    status="failed",
                    error=QA_JOB_FAILURE_DETAIL,
                    message=f"QA failed on chapter {chapter_id}. Check provider settings and server logs.",
                )
                return

    def retry_failed_jobs(self, limit: int = 15) -> str:
        # Get failed chapters and retry translation
        failed = self.pipeline.get_failed_chapters(limit=limit)
        chapter_ids = [c["id"] for c in failed]
        if not chapter_ids:
            job = self.tracker.create_job("retry", [], 0)
            self.tracker.update_job(job.job_id, status="completed", message="No failed chapters to retry")
            return job.job_id
        return self.start_translate_job(chapter_ids=chapter_ids)

    def get_job_status(self, job_id: str) -> dict | None:
        job = self.tracker.get_job(job_id)
        return job.to_dict() if job else None

    def list_active_jobs(self, limit: int = 50) -> list[dict]:
        jobs = self.tracker.list_jobs(limit)
        return [job.to_dict() for job in jobs]

    def cancel_job(self, job_id: str) -> bool:
        return self.tracker.cancel_job(job_id)
