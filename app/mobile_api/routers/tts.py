from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.mobile_api.routers.jobs import get_job_service, get_shared_job_tracker
from app.mobile_api.public_mode import is_public_request, sanitize_public_payload
from app.mobile_api.services.job_service import JobService
from app.services.tts.tts_pipeline import TTSPipeline

router = APIRouter(prefix="/api/tts", tags=["tts"])


class TTSChapterRequest(BaseModel):
    book_id: int
    chapter_id: int
    voice_config: dict[str, Any] = Field(default_factory=dict)


class TTSJobResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""


def get_tts_pipeline() -> TTSPipeline:
    return TTSPipeline(get_db_path(), get_data_dir())


@router.post("/chapter", response_model=TTSJobResponse)
async def start_tts_chapter(
    payload: TTSChapterRequest,
    service: JobService = Depends(get_job_service),
):
    """Start TTS for one translated chapter using the existing job runner."""
    job_id = service.start_tts_job(
        book_id=payload.book_id,
        chapter_ids=[payload.chapter_id],
        limit=1,
        voice=payload.voice_config.get("voice") or payload.voice_config.get("voice_id"),
        rate=payload.voice_config.get("rate") or "-5%",
        volume=payload.voice_config.get("volume") or "+0%",
    )
    return TTSJobResponse(job_id=job_id, status="pending", message="TTS job started")


@router.get("/jobs/{job_id}")
async def get_tts_job(
    job_id: str,
    request: Request,
    pipeline: TTSPipeline = Depends(get_tts_pipeline),
):
    job = pipeline.get_job_status(job_id)
    if job:
        return sanitize_public_payload(job) if is_public_request(request) else job
    mobile_job = get_shared_job_tracker().get_job(job_id)
    if mobile_job and mobile_job.job_type == "tts":
        payload = mobile_job.to_dict()
        payload["chunks"] = []
        return sanitize_public_payload(payload) if is_public_request(request) else payload
    raise HTTPException(status_code=404, detail="TTS job not found")


def _retry_job(job_id: str) -> None:
    TTSPipeline(get_db_path(), get_data_dir()).retry_failed_chunks(job_id)


@router.post("/jobs/{job_id}/retry", response_model=TTSJobResponse)
async def retry_tts_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    pipeline: TTSPipeline = Depends(get_tts_pipeline),
):
    if not pipeline.get_job_status(job_id):
        raise HTTPException(status_code=404, detail="TTS job not found")
    background_tasks.add_task(_retry_job, job_id)
    return TTSJobResponse(job_id=job_id, status="retrying", message="TTS retry started")


@router.post("/jobs/{job_id}/cancel", response_model=TTSJobResponse)
async def cancel_tts_job(job_id: str, pipeline: TTSPipeline = Depends(get_tts_pipeline)):
    cancelled = pipeline.cancel_job(job_id)
    mobile_cancelled = get_shared_job_tracker().cancel_job(job_id)
    if not cancelled and not mobile_cancelled:
        raise HTTPException(status_code=404, detail="TTS job not found")
    return TTSJobResponse(job_id=job_id, status="cancelled", message="TTS job cancelled")


@router.get("/jobs/{job_id}/download")
async def download_tts_output(
    job_id: str,
    format: str = Query("mp3", pattern="^(mp3|m4b)$"),
    pipeline: TTSPipeline = Depends(get_tts_pipeline),
):
    path = pipeline.get_download_path(job_id, format)
    if path is None:
        raise HTTPException(status_code=404, detail="TTS output not found")
    media_type = "audio/mp4" if format == "m4b" else "audio/mpeg"
    return FileResponse(Path(path), media_type=media_type, filename=Path(path).name)
