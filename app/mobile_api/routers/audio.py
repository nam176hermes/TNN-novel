from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.mobile_api.schemas import PlaylistResponse
from app.mobile_api.services.audio_service import AudioService
from app.mobile_api.services.pipeline_service import PipelineService

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
    result = audio.stream_audio(chapter_id)
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
    result = audio.download_audio(chapter_id)
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
