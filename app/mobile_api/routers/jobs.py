from __future__ import annotations

import json
import os
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.database.db import get_job_attempts, get_job_logs
from app.mobile_api.audit import record_audit_event
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.schemas import (
    CostEstimateRequest,
    CostEstimateResponse,
    JobListResponse,
    JobLogEntry,
    JobResponse,
    JobStart,
    JobStatus,
)
from app.mobile_api.services.job_service import JobService, JobTracker, get_shared_job_tracker as shared_tracker_for_db
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.provider_service import ProviderService
from app.services.tts.availability import TTSUnavailableError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
_SHARED_JOB_TRACKER: JobTracker | None = None
JOB_ATTEMPT_FAILURE_DETAIL = "Provider attempt failed. Check server logs."


def get_shared_job_tracker() -> JobTracker:
    global _SHARED_JOB_TRACKER
    db_path = get_db_path()
    if _SHARED_JOB_TRACKER is None or _SHARED_JOB_TRACKER.db_path != db_path:
        _SHARED_JOB_TRACKER = shared_tracker_for_db(db_path)
    return _SHARED_JOB_TRACKER


def get_job_service():
    return JobService(PipelineService(), tracker=get_shared_job_tracker())


def provider_params(params: dict | None) -> dict:
    resolved = dict(params or {})
    provider_id = resolved.get("provider_id")
    if not provider_id:
        return {
            "provider_id": None,
            "model": resolved.get("model"),
            "host": resolved.get("host"),
            "api_key": None,
        }

    provider = ProviderService().get_provider(str(provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")

    api_key_env = str(provider.get("api_key_env") or "").strip()
    api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
    if api_key_env and not api_key:
        raise HTTPException(status_code=400, detail=f"Provider {provider['id']} requires {api_key_env}")

    return {
        "provider_id": provider["id"],
        "model": provider["model"],
        "host": provider["base_url"],
        "api_key": api_key,
    }


def optional_positive_int(value: object, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a positive integer") from exc
    if resolved <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a positive integer")
    return resolved


def safe_job_attempts_for_response(attempts: list[dict]) -> list[dict]:
    safe_attempts: list[dict] = []
    for attempt in attempts:
        safe_attempt = dict(attempt)
        error = str(safe_attempt.get("error") or "")
        if _attempt_error_needs_redaction(error):
            safe_attempt["error"] = JOB_ATTEMPT_FAILURE_DETAIL
        safe_attempts.append(safe_attempt)
    return safe_attempts


def _attempt_error_needs_redaction(error: str) -> bool:
    lowered = error.lower()
    sensitive_markers = (
        "\n",
        "traceback",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "bearer ",
        "token",
        "/tmp/",
        "/home/",
        "\\users\\",
        "sk-",
    )
    return any(marker in lowered for marker in sensitive_markers)


@router.post("/translate", response_model=JobResponse)
async def start_translate_job(
    job: JobStart,
    request: Request,
    service: JobService = Depends(get_job_service),
):
    """Start translation job."""
    params = dict(job.params or {})
    preset_id = params.get("preset_id")
    resolved_provider = (
        {"provider_id": None, "model": None, "host": None, "api_key": None}
        if preset_id
        else provider_params(params)
    )
    job_id = service.start_translate_job(
        book_id=job.book_id,
        chapter_ids=job.chapter_ids,
        limit=job.limit,
        model=resolved_provider["model"],
        host=resolved_provider["host"],
        provider_id=resolved_provider["provider_id"],
        api_key=resolved_provider["api_key"],
        style_profile_id=params.get("style_profile_id"),
        preset_id=preset_id,
        chunk_size=optional_positive_int(params.get("chunk_size"), "chunk_size"),
    )
    get_job_status = getattr(service, "get_job_status", None)
    created_job = get_job_status(job_id) if callable(get_job_status) else None
    if (
        created_job
        and created_job.get("status") == "completed"
        and not created_job.get("target_ids")
        and created_job.get("message") == "No chapters to translate"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "No chapters to translate. Select chapters with source text, "
                "or refresh Raw chưa dịch and try again."
            ),
        )
    record_audit_event(
        event_type="job_start",
        severity="info",
        source="jobs",
        message="Translation job started",
        request=request,
        job_id=job_id,
        details={
            "job_type": "translate",
            "book_id": job.book_id,
            "chapter_count": len(job.chapter_ids or []),
            "limit": job.limit,
            "provider_id": resolved_provider["provider_id"] or "",
            "preset_id": preset_id or "",
        },
    )
    return JobResponse(job_id=job_id, status="pending", message="Translation job started")


@router.post("/tts", response_model=JobResponse)
async def start_tts_job(
    job: JobStart,
    request: Request,
    service: JobService = Depends(get_job_service),
):
    """Start TTS job."""
    try:
        job_id = service.start_tts_job(
            book_id=job.book_id,
            chapter_ids=job.chapter_ids,
            limit=job.limit,
            voice=job.params.get("voice") if job.params else None,
        )
    except TTSUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc
    record_audit_event(
        event_type="job_start",
        severity="info",
        source="jobs",
        message="TTS job started",
        request=request,
        job_id=job_id,
        details={
            "job_type": "tts",
            "book_id": job.book_id,
            "chapter_count": len(job.chapter_ids or []),
            "limit": job.limit,
        },
    )
    return JobResponse(job_id=job_id, status="pending", message="TTS job started")


@router.post("/daily", response_model=JobResponse)
async def start_daily_job(
    request: Request,
    limit: int = Query(15),
    service: JobService = Depends(get_job_service),
):
    """Start daily batch job."""
    job_id = service.start_daily_job(limit=limit)
    record_audit_event(
        event_type="job_start",
        severity="info",
        source="jobs",
        message="Daily batch job started",
        request=request,
        job_id=job_id,
        details={"job_type": "daily", "limit": limit},
    )
    return JobResponse(job_id=job_id, status="pending", message="Daily batch job started")


@router.post("/qa", response_model=JobResponse)
async def start_qa_job(
    job: JobStart,
    request: Request,
    service: JobService = Depends(get_job_service),
):
    """Start QA job."""
    qa_params = dict(job.params or {})
    if not qa_params.get("provider_id"):
        default_provider_id = ProviderService().get_defaults().get("qa")
        if default_provider_id:
            qa_params["provider_id"] = default_provider_id
    resolved_provider = provider_params(qa_params)
    job_id = service.start_qa_job(
        book_id=job.book_id,
        chapter_ids=job.chapter_ids,
        limit=job.limit,
        model=resolved_provider["model"],
        host=resolved_provider["host"],
        api_key=resolved_provider["api_key"],
        provider_id=resolved_provider["provider_id"],
    )
    record_audit_event(
        event_type="job_start",
        severity="info",
        source="jobs",
        message="QA job started",
        request=request,
        job_id=job_id,
        details={
            "job_type": "qa",
            "book_id": job.book_id,
            "chapter_count": len(job.chapter_ids or []),
            "limit": job.limit,
            "provider_id": resolved_provider["provider_id"] or "",
        },
    )
    return JobResponse(job_id=job_id, status="pending", message="QA job started")


@router.post("/retry", response_model=JobResponse)
async def retry_failed_jobs(
    request: Request,
    limit: int = Query(15),
    service: JobService = Depends(get_job_service),
):
    """Retry failed jobs."""
    job_id = service.retry_failed_jobs(limit=limit)
    record_audit_event(
        event_type="job_start",
        severity="info",
        source="jobs",
        message="Bulk retry job started",
        request=request,
        job_id=job_id,
        details={"job_type": "retry_failed", "limit": limit},
    )
    return JobResponse(job_id=job_id, status="pending", message="Retry job started")


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_failed_translation_job(
    job_id: str,
    request: Request,
    service: JobService = Depends(get_job_service),
):
    """Retry one failed translation job using its saved targets and config."""
    api_key = None
    tracker = getattr(service, "tracker", None)
    if tracker is not None:
        job = tracker.get_job(job_id)
        params = dict(job.params or {}) if job else {}
        provider_id = str(params.get("provider_id") or "").strip()
        if provider_id and not params.get("preset_id"):
            api_key = provider_params({"provider_id": provider_id})["api_key"]

    try:
        retry_job_id = service.retry_failed_translation_job(job_id, api_key=api_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Retry could not start. Check the failed job and provider settings.",
        ) from exc
    record_audit_event(
        event_type="job_retry",
        severity="info",
        source="jobs",
        message="Translation job retry started",
        request=request,
        job_id=retry_job_id,
        details={"retry_of_job_id": job_id, "job_type": "translate"},
    )
    return JobResponse(job_id=retry_job_id, status="pending", message="Retry job started")


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_job_cost(request: CostEstimateRequest):
    """Estimate provider cost for a job."""
    try:
        return ProviderService().estimate_cost(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=JobListResponse)
async def list_jobs(
    limit: int = Query(50),
    service: JobService = Depends(get_job_service),
):
    """List active jobs."""
    jobs = service.list_active_jobs(limit=limit)
    return JobListResponse(jobs=jobs)


@router.get("/{job_id}/attempts")
async def list_job_attempts(
    job_id: str,
    limit: int = Query(50),
):
    """List provider attempts recorded for a job."""
    attempts = get_job_attempts(get_db_path(), job_id=job_id, limit=limit)
    return {"attempts": safe_job_attempts_for_response(attempts)}


@router.get("/{job_id}/logs", response_model=list[JobLogEntry])
async def list_job_logs(
    job_id: str,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
):
    """List sanitized job logs."""
    return get_job_logs(get_db_path(), job_id=job_id, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    service: JobService = Depends(get_job_service),
):
    """Get job status."""
    job = service.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**job)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    service: JobService = Depends(get_job_service),
):
    """SSE stream for job progress."""
    job = service.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream() -> AsyncGenerator:
        yield json.dumps({"job_id": job_id, "status": "connected"})

        job_obj = service.tracker.get_job(job_id)
        if not job_obj:
            return

        last_progress = -1
        while job_obj.status not in ("completed", "failed", "cancelled", "canceled", "interrupted"):
            current = service.get_job_status(job_id)
            if current and current["progress"] != last_progress:
                yield json.dumps(current)
                last_progress = current["progress"]
            import asyncio
            await asyncio.sleep(0.5)

        # Final status
        final = service.get_job_status(job_id)
        if final:
            yield json.dumps(final)

    return EventSourceResponse(event_stream())


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    service: JobService = Depends(get_job_service),
):
    """Cancel a job."""
    success = service.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    record_audit_event(
        event_type="job_cancel",
        severity="info",
        source="jobs",
        message="Job cancelled",
        request=request,
        job_id=job_id,
        details={"result": "success"},
    )
    return {"message": "Job cancelled"}
