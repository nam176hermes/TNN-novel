from __future__ import annotations

import math
from pathlib import Path

from mutagen import File as MutagenFile

from app.mobile_api.services.pipeline_service import PipelineService
from app.storage.artifact_paths import ArtifactClass, ArtifactPathError


def audio_duration_seconds(audio_path: Path) -> float:
    try:
        metadata = MutagenFile(str(audio_path))
        length = getattr(getattr(metadata, "info", None), "length", 0)
        duration = float(length or 0)
    except (OSError, ValueError, TypeError):
        return 0
    return round(duration, 2) if math.isfinite(duration) and duration > 0 else 0


class AudioService:
    def __init__(self, pipeline_service: PipelineService):
        self.pipeline = pipeline_service

    def get_audio_path(self, chapter_id: int) -> Path | None:
        """Get the audio file path for a chapter."""
        chapter = self.pipeline.get_chapter(chapter_id)
        if not chapter or not chapter.get("audio_path"):
            return None
        return self.pipeline.resolve_artifact_file(chapter["audio_path"], ArtifactClass.AUDIO)

    def stream_audio(self, chapter_id: int):
        """Yield audio file in chunks for streaming."""
        from fastapi.responses import FileResponse

        audio_path = self.get_audio_path(chapter_id)
        if not audio_path:
            return None
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=audio_path.name,
        )

    def download_audio(self, chapter_id: int):
        """Return audio file for download."""
        from fastapi.responses import FileResponse

        audio_path = self.get_audio_path(chapter_id)
        if not audio_path:
            return None
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=audio_path.name,
        )

    def get_playlist(self, book_id: int) -> list[dict]:
        """Get audio playlist for a book."""
        chapters = self.pipeline.list_chapters(book_id)
        playlist = []
        order = 0
        for chapter in chapters:
            if chapter.get("audio_path"):
                try:
                    audio_path = self.pipeline.resolve_artifact_file(chapter["audio_path"], ArtifactClass.AUDIO)
                except ArtifactPathError:
                    continue
                if audio_path.is_file():
                    chapter_id = chapter["id"]
                    playlist.append({
                        "chapter_id": chapter_id,
                        "chapter_number": chapter["chapter_number"],
                        "title": chapter["title"],
                        "duration_seconds": audio_duration_seconds(audio_path),
                        "download_url": f"/api/books/{book_id}/chapters/{chapter_id}/audio/download",
                        "filename": audio_path.name,
                        "order": order,
                        "size_bytes": audio_path.stat().st_size,
                        "stream_url": f"/api/books/{book_id}/chapters/{chapter_id}/audio",
                    })
                    order += 1
        return playlist
