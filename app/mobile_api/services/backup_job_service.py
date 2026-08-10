from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.database.db import get_mobile_job, record_operational_event
from app.mobile_api.services.backup_service import BackupService
from app.mobile_api.services.job_service import JobTracker
from scripts.ops import BackupCancelled

logger = logging.getLogger(__name__)

BACKUP_TOTAL_STEPS = 6
BACKUP_FAILURE_DETAIL = "Backup failed. Check server logs."
BACKUP_SECRET_EXPIRED_DETAIL = "Backup encryption credential expired. Queue the backup again."
BACKUP_TERMINAL_EVENT_TYPE = "backup_job_terminal"
BACKUP_TERMINAL_EVENT_MESSAGE = "Backup job reached a terminal state"
BACKUP_DURATION_MAX_MS = 2_147_483_647
BACKUP_PROGRESS: dict[str, tuple[int, str, str]] = {
    "preparing": (0, "PREPARING_BACKUP", "Preparing backup"),
    "collecting": (1, "PREPARING_BACKUP", "Collecting backup files"),
    "writing": (2, "WRITING_BACKUP", "Writing backup archive"),
    "validating": (3, "VALIDATING_BACKUP", "Validating backup archive"),
    "encrypting": (4, "ENCRYPTING_BACKUP", "Encrypting backup archive"),
    "publishing": (5, "PUBLISHING_BACKUP", "Publishing backup archive"),
}


def _backup_basename(value: object) -> str:
    return Path(str(value or "").replace("\\", "/")).name


class BackupSecretStore:
    """Short-lived, process-local storage for backup encryption credentials."""

    __slots__ = ("_entries", "_lock", "_monotonic", "_ttl_seconds")

    def __init__(
        self,
        *,
        ttl_seconds: float = 300,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, str]] = {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<process-local>)"

    def __getstate__(self) -> None:
        raise TypeError("BackupSecretStore cannot be serialized")

    def put(self, job_id: str, value: str) -> None:
        with self._lock:
            self._entries[job_id] = (self._monotonic() + self._ttl_seconds, value)

    def take(self, job_id: str) -> str:
        with self._lock:
            entry = self._entries.pop(job_id, None)
        if entry is None:
            return ""
        expires_at, value = entry
        return value if self._monotonic() <= expires_at else ""

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._entries.pop(job_id, None)


class BackupJobCoordinator:
    def __init__(
        self,
        *,
        tracker: JobTracker,
        backup_service: BackupService,
        secret_store: BackupSecretStore | None = None,
    ) -> None:
        self.tracker = tracker
        self.backup_service = backup_service
        self.secret_store = secret_store or BackupSecretStore()
        self._directory_locks: dict[Path, asyncio.Lock] = {}

    def start_backup_job(
        self,
        *,
        include_audio: bool,
        include_exports: bool,
        include_job_logs: bool,
        include_secrets: bool,
        passphrase: str,
    ) -> str:
        credential = passphrase.strip()
        if include_secrets and not credential:
            raise ValueError("An encryption credential is required when including secrets")

        params = {
            "include_audio": bool(include_audio),
            "include_exports": bool(include_exports),
            "include_job_logs": bool(include_job_logs),
            "include_secrets": bool(include_secrets),
        }
        job = self.tracker.create_job("backup", total=BACKUP_TOTAL_STEPS, params=params)
        if include_secrets:
            self.secret_store.put(job.job_id, credential)
        self.tracker.start_background_task(job.job_id, self._run_backup_job(job.job_id))
        return job.job_id

    def _cancel_requested(self, job_id: str) -> bool:
        job = self.tracker.get_job(job_id)
        if self.tracker.db_path is not None:
            persisted = get_mobile_job(self.tracker.db_path, job_id)
            durable_cancel_requested = bool(
                persisted
                and (
                    persisted.get("cancel_requested")
                    or str(persisted.get("status") or "").lower() in {"cancelled", "canceled"}
                )
            )
            if durable_cancel_requested:
                if job is not None:
                    job.cancel_requested = True
                return True
        return bool(job and job.cancel_requested)

    def _terminal_result(self, job_id: str, *, fallback: str) -> str:
        job = self.tracker.get_job(job_id)
        if job is None:
            return fallback
        status = job.status.lower()
        if status in {"cancelled", "canceled"}:
            return "cancelled"
        if status in {"completed", "failed"}:
            return status
        return fallback

    def _publish_step(self, job_id: str, step: str) -> None:
        update = BACKUP_PROGRESS.get(step.strip().lower())
        if update is None:
            return
        progress, state, message = update
        job = self.tracker.get_job(job_id)
        if (
            state == "PUBLISHING_BACKUP"
            and job is not None
            and job.params.get("include_secrets")
            and job.state != "ENCRYPTING_BACKUP"
        ):
            # Secret-bearing backups may report this while publishing only
            # inside private staging; live publication stays suppressed until
            # encryption and READY-sidecar validation have completed.
            # Keep the durable state at validation until encryption begins.
            return
        self.tracker.update_job(
            job_id,
            status="running",
            progress=progress,
            state=state,
            current_step=state,
            message=message,
        )

    def _record_terminal_event(
        self,
        *,
        job_id: str,
        result: str,
        encrypted: bool,
        secrets_included: bool,
        started_at: float,
        backup_filename: str = "",
    ) -> None:
        if self.tracker.db_path is None:
            return

        elapsed_seconds = max(0.0, time.monotonic() - started_at)
        duration_ms = min(int(elapsed_seconds * 1000), BACKUP_DURATION_MAX_MS)
        details: dict[str, object] = {
            "result": result,
            "encrypted": encrypted,
            "secrets_included": secrets_included,
            "duration_ms": duration_ms,
        }
        if backup_filename:
            details["backup_filename"] = _backup_basename(backup_filename)

        severity = "info" if result == "completed" else "warning" if result == "cancelled" else "error"
        try:
            record_operational_event(
                self.tracker.db_path,
                event_type=BACKUP_TERMINAL_EVENT_TYPE,
                severity=severity,
                source="backup_job_coordinator",
                message=BACKUP_TERMINAL_EVENT_MESSAGE,
                job_id=job_id,
                details=details,
            )
        except Exception:
            logger.warning("Failed to record terminal backup event for job %s", job_id)

    def _update_terminal_job(self, job_id: str, *, status: str, **changes: object) -> str:
        cached_before = self.tracker.jobs.get(job_id)
        cached_status_before = cached_before.status.lower() if cached_before is not None else ""
        requested_status = status.lower()
        try:
            self.tracker.update_job(job_id, status=status, **changes)
        except Exception:
            persisted = get_mobile_job(self.tracker.db_path, job_id) if self.tracker.db_path else None
            persisted_status = str((persisted or {}).get("status") or "").lower()
            cached = self.tracker.jobs.get(job_id)
            cached_status = cached.status.lower() if cached is not None else ""
            cancellation_reconciled = bool(
                requested_status in {"completed", "failed"}
                and cached_status_before == "running"
                and persisted_status in {"cancelled", "canceled"}
                and (persisted or {}).get("cancel_requested")
                and cached_status in {"cancelled", "canceled"}
                and cached is not None
                and cached.cancel_requested
                and cached.updated_at == str((persisted or {}).get("updated_at") or "")
            )
            if not persisted or (persisted_status != requested_status and not cancellation_reconciled):
                raise
            logger.warning("Job %s terminal state persisted but auxiliary recording failed", job_id)
        return self._terminal_result(job_id, fallback=status)

    async def _run_backup_job(self, job_id: str) -> None:
        started_at = time.monotonic()
        directory = self.backup_service.backup_dir.resolve()
        lock = self._directory_locks.setdefault(directory, asyncio.Lock())
        try:
            async with lock:
                job = self.tracker.get_job(job_id)
                include_secrets = bool(job and job.params.get("include_secrets"))
                if self._cancel_requested(job_id):
                    self._record_terminal_event(
                        job_id=job_id,
                        result="cancelled",
                        # Cancellation has no completed artifact metadata, so
                        # request intent is the authoritative safe fallback.
                        encrypted=include_secrets,
                        secrets_included=include_secrets,
                        started_at=started_at,
                    )
                    self._update_terminal_job(
                        job_id,
                        status="cancelled",
                        message="Backup cancelled",
                        cancel_requested=True,
                    )
                    return

                credential = self.secret_store.take(job_id) if include_secrets else ""
                if include_secrets and not credential:
                    result = self._update_terminal_job(
                        job_id,
                        status="failed",
                        error=BACKUP_SECRET_EXPIRED_DETAIL,
                        message=BACKUP_SECRET_EXPIRED_DETAIL,
                    )
                    self._record_terminal_event(
                        job_id=job_id,
                        result=result,
                        encrypted=True,
                        secrets_included=True,
                        started_at=started_at,
                    )
                    return

                try:
                    params = dict(job.params) if job is not None else {}
                    local_cancel = threading.Event()
                    worker = asyncio.create_task(
                        asyncio.to_thread(
                            self.backup_service.create_backup,
                            include_audio=bool(params.get("include_audio", True)),
                            include_exports=bool(params.get("include_exports")),
                            include_job_logs=bool(params.get("include_job_logs")),
                            include_secrets=include_secrets,
                            passphrase=credential,
                            cancel_check=lambda: local_cancel.is_set() or self._cancel_requested(job_id),
                            progress_callback=lambda step: self._publish_step(job_id, step),
                        )
                    )
                    try:
                        item = await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        local_cancel.set()
                        self.tracker.update_job(job_id, cancel_requested=True)
                        while not worker.done():
                            try:
                                await asyncio.shield(worker)
                            except asyncio.CancelledError:
                                local_cancel.set()
                            except Exception:
                                break
                        if worker.done():
                            try:
                                worker.result()
                            except (asyncio.CancelledError, Exception):
                                pass
                        raise BackupCancelled("Backup cancelled") from None
                except BackupCancelled:
                    self._record_terminal_event(
                        job_id=job_id,
                        result="cancelled",
                        encrypted=include_secrets,
                        secrets_included=include_secrets,
                        started_at=started_at,
                    )
                    self._update_terminal_job(
                        job_id,
                        status="cancelled",
                        message="Backup cancelled",
                        cancel_requested=True,
                    )
                    return
                except Exception:
                    logger.error("Backup job %s failed", job_id)
                    result = self._update_terminal_job(
                        job_id,
                        status="failed",
                        error=BACKUP_FAILURE_DETAIL,
                        message=BACKUP_FAILURE_DETAIL,
                    )
                    self._record_terminal_event(
                        job_id=job_id,
                        result=result,
                        # Failure has no completed artifact metadata, so request
                        # intent is the authoritative safe fallback.
                        encrypted=include_secrets,
                        secrets_included=include_secrets,
                        started_at=started_at,
                    )
                    return

                filename = _backup_basename(item.get("filename"))
                completed_params = {**params, "backup_filename": filename}
                result = self._update_terminal_job(
                    job_id,
                    status="completed",
                    progress=BACKUP_TOTAL_STEPS,
                    params=completed_params,
                    current_step="PUBLISHING_BACKUP",
                    message=f"Backup completed: {filename}",
                )
                self._record_terminal_event(
                    job_id=job_id,
                    result=result,
                    encrypted=bool(item.get("encrypted")),
                    secrets_included=bool(item.get("secrets_included")),
                    started_at=started_at,
                    backup_filename=filename if result == "completed" else "",
                )
        except asyncio.CancelledError:
            job = self.tracker.get_job(job_id)
            include_secrets = bool(job and job.params.get("include_secrets"))
            self._record_terminal_event(
                job_id=job_id,
                result="cancelled",
                encrypted=include_secrets,
                secrets_included=include_secrets,
                started_at=started_at,
            )
            self._update_terminal_job(
                job_id,
                status="cancelled",
                message="Backup cancelled",
                cancel_requested=True,
            )
        finally:
            self.secret_store.discard(job_id)
