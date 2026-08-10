"""Bounded asynchronous waiting for externally executed durable import jobs."""

from __future__ import annotations

import asyncio

from fastapi import Request

from app.database.import_jobs import ImportJob, JobStatus
from app.import_contracts import BrowserResultState, ImportOperationKind
from app.services.import_job_service import ImportJobService


_TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.PARTIALLY_SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class ImportJobWaitError(RuntimeError):
    """Expose only a stable wait outcome code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def wait_for_terminal_import_job(
    request: Request,
    service: ImportJobService,
    job_id: str,
    owner_user_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> ImportJob:
    """Poll durable state without executing import work in the API process."""

    loop = asyncio.get_running_loop()
    wait_deadline = loop.time() + timeout_seconds
    while True:
        job = await asyncio.to_thread(service.get_job, job_id, owner_user_id)
        if job.status in _TERMINAL_JOB_STATUSES:
            return job
        if await request.is_disconnected():
            await asyncio.to_thread(service.request_cancel, job_id, owner_user_id)
            raise ImportJobWaitError("client_disconnected")
        if loop.time() >= wait_deadline:
            if job.operation_kind is ImportOperationKind.PREVIEW:
                winner = await asyncio.to_thread(
                    service.repository.expire_browser_job,
                    job_id,
                    owner_user_id,
                )
                if winner.result_state is not BrowserResultState.TIMED_OUT:
                    return winner
            else:
                await asyncio.to_thread(service.request_cancel, job_id, owner_user_id)
            raise ImportJobWaitError("browser_task_timed_out")
        await asyncio.sleep(poll_seconds)
