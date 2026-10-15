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
from app.services.tts.availability import TTSUnavailableError
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


def _tts_download_url(job_id: str, format: str) -> str:
    return f"/api/tts/jobs/{job_id}/download?format={format}"


def _api_tts_job_payload(job: dict[str, Any], *, request: Request) -> dict[str, Any]:
    payload = dict(job)
    resolved_job_id = str(payload.get("job_id") or payload.get("id") or "")
    payload.pop("report_json_path", None)
    payload.pop("output_mp3_path", None)
    payload.pop("output_m4b_path", None)
    payload.pop("input_snapshot_json", None)
    audio_summary = payload.get("audio_summary") if isinstance(payload.get("audio_summary"), dict) else {}
    payload["output_mp3_ready"] = bool(audio_summary.get("output_mp3_ready"))
    payload["output_m4b_ready"] = bool(audio_summary.get("output_m4b_ready"))
    if resolved_job_id:
        payload["output_mp3_download_url"] = _tts_download_url(resolved_job_id, "mp3")
        payload["output_m4b_download_url"] = _tts_download_url(resolved_job_id, "m4b")

    sanitized_chunks: list[dict[str, Any]] = []
    for chunk in payload.get("chunks", []) or []:
        chunk_payload = dict(chunk)
        chunk_payload.pop("wav_path", None)
        chunk_payload.pop("mp3_path", None)
        sanitized_chunks.append(chunk_payload)
    payload["chunks"] = sanitized_chunks
    return sanitize_public_payload(payload) if is_public_request(request) else payload


@router.post("/chapter", response_model=TTSJobResponse)
async def start_tts_chapter(
    payload: TTSChapterRequest,
    service: JobService = Depends(get_job_service),
):
    """Start TTS for one translated chapter using the existing job runner."""
    try:
        job_id = service.start_tts_job(
            book_id=payload.book_id,
            chapter_ids=[payload.chapter_id],
            limit=1,
            voice=payload.voice_config.get("voice") or payload.voice_config.get("voice_id"),
            rate=payload.voice_config.get("rate") or "-5%",
            volume=payload.voice_config.get("volume") or "+0%",
        )
    except TTSUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc
    return TTSJobResponse(job_id=job_id, status="pending", message="TTS job started")


@router.get("/jobs/{job_id}")
async def get_tts_job(
    job_id: str,
    request: Request,
    pipeline: TTSPipeline = Depends(get_tts_pipeline),
):
    job = pipeline.get_job_status(job_id)
    if job:
        return _api_tts_job_payload(job, request=request)
    mobile_job = get_shared_job_tracker().get_job(job_id)
    if mobile_job and mobile_job.job_type == "tts":
        payload = mobile_job.to_dict()
        payload["chunks"] = []
        payload["children"] = pipeline.get_child_jobs(job_id)
        return sanitize_public_payload(payload) if is_public_request(request) else payload
    raise HTTPException(status_code=404, detail="TTS job not found")


def _retry_job(job_id: str) -> None:
    pipeline = TTSPipeline(get_db_path(), get_data_dir())
    try:
        children = pipeline.get_child_jobs(job_id)
        targets = [child["id"] for child in children if child["status"] != "completed"] if children else [job_id]
        for target in targets:
            pipeline.retry_failed_chunks(target)
    finally:
        pipeline.close()


@router.post("/jobs/{job_id}/retry", response_model=TTSJobResponse)
async def retry_tts_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    pipeline: TTSPipeline = Depends(get_tts_pipeline),
):
    children = pipeline.get_child_jobs(job_id)
    if not pipeline.get_job_status(job_id) and not children:
        raise HTTPException(status_code=404, detail="TTS job not found")
    try:
        for target in ([child["id"] for child in children if child["status"] != "completed"] if children else [job_id]):
            pipeline.validate_retry(target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "tts_input_changed", "message": "Đầu vào TTS đã thay đổi. Hãy tạo tác vụ mới."}) from exc
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
