from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class FFmpegUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioMetadata:
    title: str = ""
    author: str = ""
    chapter_number: int = 0
    source_book: str = ""


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FFmpegUnavailableError("ffmpeg is required for TTS audio merge/export but was not found in PATH")
    return ffmpeg


def _ffconcat_quote(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "'\\''") + "'"


def _write_concat_file(paths: list[Path], list_path: Path) -> None:
    lines = ["ffconcat version 1.0"]
    for path in paths:
        lines.append(f"file {_ffconcat_quote(path)}")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_silence(path: Path, *, sample_rate: int, silence_ms: int) -> None:
    ffmpeg = ensure_ffmpeg()
    duration = max(0.05, silence_ms / 1000)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{duration:.3f}",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to create TTS silence: {result.stderr.strip()}")


def merge_chapter_audio(
    chunk_paths: list[Path],
    output_path: Path,
    *,
    metadata: AudioMetadata,
    sample_rate: int = 24000,
    silence_ms: int = 350,
) -> Path:
    if not chunk_paths:
        raise ValueError("No TTS chunks to merge")
    ffmpeg = ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-merge-") as tmp:
        tmp_dir = Path(tmp)
        silence_path = tmp_dir / "silence.wav"
        _create_silence(silence_path, sample_rate=sample_rate, silence_ms=silence_ms)
        concat_paths: list[Path] = []
        for index, chunk_path in enumerate(chunk_paths):
            concat_paths.append(chunk_path)
            if index < len(chunk_paths) - 1:
                concat_paths.append(silence_path)
        list_path = tmp_dir / "chunks.ffconcat"
        _write_concat_file(concat_paths, list_path)
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-filter:a",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            str(sample_rate),
            "-codec:a",
            "libmp3lame",
            "-qscale:a",
            "2",
            "-metadata",
            f"title={metadata.title}",
            "-metadata",
            f"artist={metadata.author or 'novel_pipeline'}",
            "-metadata",
            f"album={metadata.source_book}",
        ]
        if metadata.chapter_number:
            cmd.extend(["-metadata", f"track={metadata.chapter_number}"])
        cmd.append(str(output_path))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed to merge TTS chunks: {result.stderr.strip()}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg merge produced an empty chapter MP3")
    return output_path


def merge_book_m4b(
    chapter_paths: list[Path],
    output_path: Path,
    *,
    metadata: AudioMetadata,
) -> Path:
    if not chapter_paths:
        raise ValueError("No chapter audio files to merge into M4B")
    ffmpeg = ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-m4b-") as tmp:
        list_path = Path(tmp) / "chapters.ffconcat"
        _write_concat_file(chapter_paths, list_path)
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vn",
            "-codec:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-metadata",
            f"title={metadata.title}",
            "-metadata",
            f"artist={metadata.author or 'novel_pipeline'}",
            "-metadata",
            f"album={metadata.source_book or metadata.title}",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed to create M4B audiobook: {result.stderr.strip()}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg created an empty M4B audiobook")
    return output_path
