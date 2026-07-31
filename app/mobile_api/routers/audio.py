from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.mobile_api.schemas import PlaylistResponse
from app.mobile_api.services.audio_service import AudioService
from app.mobile_api.services.pipeline_service import PipelineService
from app.storage.artifact_paths import ArtifactPathError, ResolutionStatus

router = APIRouter(prefix="/api", tags=["audio"])


def get_audio_service():
    return AudioService(PipelineService())


def _ensure_chapter_in_book(audio: AudioService, book_id: int, chapter_id: int) -> None:
    chapter = audio.pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")


@router.get("/books/{book_id}/chapters/{chapter_id}/audio")
async def stream_audio(
    book_id: int,
    chapter_id: int,
    audio: AudioService = Depends(get_audio_service),
):
    """Stream MP3 audio for chapter."""
    _ensure_chapter_in_book(audio, book_id, chapter_id)
    try:
        result = audio.stream_audio(chapter_id)
    except ArtifactPathError as exc:
        status_code = 403 if exc.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    return result


@router.get("/books/{book_id}/chapters/{chapter_id}/audio/download")
async def download_audio(
    book_id: int,
    chapter_id: int,
    audio: AudioService = Depends(get_audio_service),
):
    """Download MP3 audio for chapter."""
    _ensure_chapter_in_book(audio, book_id, chapter_id)
    try:
        result = audio.download_audio(chapter_id)
    except ArtifactPathError as exc:
        status_code = 403 if exc.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    return result


@router.get("/books/{book_id}/audio/playlist", response_model=PlaylistResponse)
async def get_playlist(
    book_id: int,
    audio: AudioService = Depends(get_audio_service),
):
    """Get playlist JSON for book."""
    chapters = audio.get_playlist(book_id)
    return {"book_id": book_id, "chapters": chapters}
