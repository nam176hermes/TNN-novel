"""Dedicated durable import/browser worker process.

The worker consumes the P05/P06 SQLite job store.  It owns source and browser
work in production; FastAPI may retain its legacy in-process execution mode for
local development only.  The heartbeat contains no job, source, cookie, or
credential data and is used solely by the container health check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import tempfile
import threading
import time
from typing import Callable, Sequence

from app.database.db import init_db
from app.database.import_jobs import ImportJob, JobStatus
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.services.import_job_factory import create_import_job_service
from app.services.import_job_service import ImportJobService
from app.utils.stealth_browser import close_stealth_browser
from app.runtime_identity import get_runtime_identity


_TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.PARTIALLY_SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class WorkerHeartbeat:
    """Atomically update one safe heartbeat timestamp file."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        worker_id: str = "",
    ) -> None:
        self.path = Path(path)
        self._clock = clock
        self.worker_id = str(worker_id or "")[:128]

    def touch(self) -> None:
        timestamp = self._clock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                identity = get_runtime_identity(component="import-worker")
                json.dump(
                    {
                        "updated_at": int(timestamp),
                        "worker_id": self.worker_id,
                        "release_id": identity.release_id,
                        "git_sha": identity.git_sha,
                        "component": identity.component,
                    },
                    handle,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary_path, 0o600)
            except (OSError, PermissionError):
                pass
            os.replace(temporary_path, self.path)
            try:
                os.utime(self.path, (timestamp, timestamp))
            except (OSError, PermissionError):
                pass
        finally:
            temporary_path.unlink(missing_ok=True)


def worker_healthcheck(
    db_path: Path,
    *,
    heartbeat_path: Path,
    now: float | None = None,
    max_age_seconds: float | None = None,
) -> bool:
    """Return whether an existing worker recently heartbeated and can reach SQLite."""

    resolved_now = time.time() if now is None else now
    max_age = (
        mobile_settings.import_worker_heartbeat_max_age_seconds
        if max_age_seconds is None
        else max_age_seconds
    )
    try:
        with sqlite3.connect(str(db_path)) as connection:
            connection.execute("SELECT 1").fetchone()
        modified_at = Path(heartbeat_path).stat().st_mtime
    except (OSError, sqlite3.Error):
        return False
    return max(0.0, resolved_now - modified_at) <= max(0.0, max_age)


class DurableImportWorker:
    """Poll one durable job at a time and recover expired leases before claim."""

    def __init__(
        self,
        service: ImportJobService,
        *,
        heartbeat_path: Path,
        poll_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
        close_browser: Callable[[], None] | None = None,
    ) -> None:
        self.service = service
        self.heartbeat = WorkerHeartbeat(
            heartbeat_path,
            clock=clock,
            worker_id=str(getattr(service, "worker_id", "")),
        )
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self._close_browser = close_browser or _close_browser_sync

    def run_once(self) -> int:
        """Recover eligible work and drain one claimed durable job batch."""

        self.heartbeat.touch()
        self.service.recover_interrupted_jobs()
        jobs = self.service.repository.list_runnable_jobs(limit=1)
        if not jobs:
            return 0
        self._drain_job(jobs[0])
        self.heartbeat.touch()
        return 1

    def run_forever(self, *, stop_event: threading.Event) -> None:
        """Stop accepting new jobs on SIGTERM and leave active leases recoverable."""

        try:
            while not stop_event.is_set():
                processed = self.run_once()
                if not processed:
                    stop_event.wait(self.poll_interval_seconds)
        finally:
            self._close_browser()

    def _drain_job(self, job: ImportJob) -> None:
        while True:
            before = self.service.get_job(job.id, job.owner_user_id)
            current = self.service.run_job(job.id, job.owner_user_id)
            if current.status in _TERMINAL_JOB_STATUSES:
                return
            if current.cancel_requested_at or current.queued_count == 0:
                return
            if current.version == before.version:
                return


def _close_browser_sync() -> None:
    asyncio.run(close_stealth_browser())


def _worker_id() -> str:
    configured = os.getenv("IMPORT_WORKER_ID", "").strip()
    if configured:
        return configured[:128]
    return f"import-worker-{socket.gethostname()}-{os.getpid()}"


def _heartbeat_path() -> Path:
    return get_data_dir() / "logs" / "runtime" / "import-worker.heartbeat"


def _install_shutdown_handlers(stop_event: threading.Event) -> None:
    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signal_name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_name, request_stop)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Novel-TNN durable import worker")
    parser.add_argument("--once", action="store_true", help="recover and process at most one durable job")
    parser.add_argument("--healthcheck", action="store_true", help="exit nonzero when the worker heartbeat is stale")
    args = parser.parse_args(argv)

    db_path = get_db_path()
    heartbeat_path = _heartbeat_path()
    if args.healthcheck:
        return 0 if worker_healthcheck(db_path, heartbeat_path=heartbeat_path) else 1

    init_db(db_path)
    service = create_import_job_service(worker_id=_worker_id(), db_path=db_path)
    worker = DurableImportWorker(
        service,
        heartbeat_path=heartbeat_path,
        poll_interval_seconds=mobile_settings.import_worker_poll_interval_seconds,
    )
    if args.once:
        worker.run_once()
        return 0
    stop_event = threading.Event()
    _install_shutdown_handlers(stop_event)
    worker.run_forever(stop_event=stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
