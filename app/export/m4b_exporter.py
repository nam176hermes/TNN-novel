from __future__ import annotations

import subprocess
import tempfile
from shutil import which
from pathlib import Path


def export_m4b(
    book_title: str,
    author: str,
    chapters: list[dict],
    output_path: Path,
) -> Path:
    """
    Merge chapter MP3s into one M4B audiobook using FFmpeg.

    Args:
        book_title: Title of the book.
        author: Author name.
        chapters: List of chapter dicts with audio_path.
        output_path: Output .m4b file.

    Returns:
        Path to created M4B file.
    """
    audio_paths: list[Path] = []
    for ch in sorted(chapters, key=lambda c: c.get("chapter_number", 0)):
        audio_path = ch.get("audio_path")
        if audio_path and Path(audio_path).exists():
            audio_paths.append(Path(audio_path))

    if not audio_paths:
        raise ValueError("No chapter audio files found. Run TTS first.")
    if which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is not installed. Install ffmpeg to export M4B audiobooks.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="m4b-export-", dir=output_path.parent) as tmp:
        concat_file = Path(tmp) / "chapters.ffconcat"
        with concat_file.open("w", encoding="utf-8") as f:
            for p in audio_paths:
                f.write(f"file '{p.as_posix()}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-vn",
            "-metadata",
            f"title={book_title}",
            "-metadata",
            f"artist={author or 'Unknown'}",
            "-metadata",
            f"album={book_title}",
            "-metadata",
            "genre=Audiobook",
            str(output_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FFmpeg M4B export timed out") from exc
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg M4B export failed: {result.stderr}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("FFmpeg M4B export produced an empty file")

        return output_path


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
