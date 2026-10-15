from __future__ import annotations

import json
from pathlib import Path

from app.services.tts.audio_merger import AudioMetadata, merge_book_m4b


class IncompleteAudiobookError(ValueError):
    def __init__(self, chapter_ids):
        self.chapter_ids = chapter_ids
        super().__init__("Audiobook is incomplete; missing or stale chapter audio")


def select_audiobook_chapters(chapters, *, allow_partial=False):
    included, missing = [], []
    for chapter in sorted(chapters, key=lambda row: row.get("chapter_number", 0)):
        value = chapter.get("audio_path")
        path = Path(value) if value else None
        if chapter.get("audio_status") == "stale" or path is None or not path.is_file() or path.stat().st_size <= 0:
            missing.append(chapter.get("id", chapter.get("chapter_number", 0)))
        else:
            included.append(chapter)
    if missing and not allow_partial:
        raise IncompleteAudiobookError(missing)
    if not included:
        raise ValueError("No chapter audio files found. Run TTS first.")
    return included, missing


def validate_audiobook_snapshot(before, after):
    keys = ("id", "content_revision", "audio_path", "audio_status", "audio_translation_hash")
    def identity(rows):
        return sorted((tuple(row.get(key) for key in keys) for row in rows), key=lambda row: row[0])
    if identity(before) != identity(after):
        raise ValueError("Audiobook inputs changed during export; please retry")


def export_m4b(book_title: str, author: str, chapters: list[dict], output_path: Path, *, allow_partial=False) -> Path:
    included, missing = select_audiobook_chapters(chapters, allow_partial=allow_partial)
    result = merge_book_m4b([Path(chapter["audio_path"]) for chapter in included], output_path,
        metadata=AudioMetadata(title=book_title, author=author, source_book=book_title),
        chapter_titles=[chapter.get("translated_title") or chapter.get("title") or f"Chương {chapter.get('chapter_number', 0)}" for chapter in included])
    output_path.with_suffix(".manifest.json").write_text(json.dumps({
        "version": 1, "partial": bool(missing), "missing_chapter_ids": missing,
        "chapters": [{name: chapter.get(name) for name in ("id", "chapter_number", "content_revision", "audio_status", "audio_translation_hash")}
                     for chapter in included],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def export_mp3_playlist(
    book_title: str,
    chapters: list[dict],
    output_path: Path,
) -> Path:
    """Create an M3U playlist for chapter MP3 files."""
    lines = ["#EXTM3U"]
    for ch in sorted(chapters, key=lambda c: c.get("chapter_number", 0)):
        audio_path = ch.get("audio_path")
        if not audio_path or not Path(audio_path).exists():
            continue
        title = ch.get("title") or f"Chapter {ch.get('chapter_number', 0)}"
        lines.append(f"#EXTINF:-1,{title}")
        lines.append(str(Path(audio_path).resolve()))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
