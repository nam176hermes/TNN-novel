from __future__ import annotations

import shutil
import subprocess
import tempfile
import re
import wave
import os
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
        raise RuntimeError("FFmpeg failed to create TTS silence")


def _decode_pcm(paths, directory, sample_rate=24000):
    decoded = []
    for index, source in enumerate(paths):
        try:
            with wave.open(str(source), "rb") as wav:
                if (wav.getcomptype() == "NONE" and wav.getnchannels() == 1
                        and wav.getsampwidth() == 2 and wav.getframerate() == sample_rate
                        and wav.getnframes() > 0):
                    # Check the last frame too: a truncated data chunk is not reusable PCM.
                    wav.setpos(wav.getnframes() - 1)
                    if len(wav.readframes(1)) == 2:
                        decoded.append(source)
                        continue
        except (OSError, EOFError, wave.Error):
            pass  # Non-WAV and malformed input still use the existing FFmpeg decoder.
        target = directory / f"pcm_{index:06d}.wav"
        result = subprocess.run([ensure_ffmpeg(), "-v", "error", "-i", str(source), "-ac", "1",
            "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(target)], capture_output=True, timeout=300)
        if result.returncode:
            raise RuntimeError("FFmpeg could not decode chapter audio")
        decoded.append(target)
    return decoded


def _voice_filters(rate, volume):
    if not re.fullmatch(r"[+-]?\d+%", rate) or not re.fullmatch(r"[+-]?\d+%", volume):
        raise ValueError("Rate and volume must be percentages")
    tempo, gain = 1 + int(rate[:-1]) / 100, 1 + int(volume[:-1]) / 100
    if not .05 <= tempo <= 4 or not 0 <= gain <= 4:
        raise ValueError("Rate or volume is outside the supported range")
    filters = ["loudnorm=I=-16:TP=-1.5:LRA=11"]
    while tempo < .5:
        filters.append("atempo=0.5")
        tempo *= 2
    while tempo > 2:
        filters.append("atempo=2")
        tempo /= 2
    filters.extend([f"atempo={tempo}", f"volume={gain}"])
    return ",".join(filters)


def merge_chapter_audio(chunk_paths: list[Path], output_path: Path, *, metadata: AudioMetadata,
                        sample_rate: int = 24000, silence_ms: int = 350,
                        rate: str = "+0%", volume: str = "+0%") -> Path:
    if not chunk_paths:
        raise ValueError("No TTS chunks to merge")
    ffmpeg = ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-merge-", dir=output_path.parent) as tmp:
        directory = Path(tmp)
        decoded = _decode_pcm(chunk_paths, directory, sample_rate)
        silence = directory / "silence.wav"
        if silence_ms > 0:
            _create_silence(silence, sample_rate=sample_rate, silence_ms=silence_ms)
        paths = []
        for index, path in enumerate(decoded):
            paths.append(path)
            if silence_ms > 0 and index < len(decoded) - 1:
                paths.append(silence)
        concat = directory / "chunks.ffconcat"
        _write_concat_file(paths, concat)
        staged = directory / "chapter.mp3"
        command = [ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-filter:a", _voice_filters(rate, volume), "-ar", str(sample_rate), "-codec:a", "libmp3lame", "-qscale:a", "2",
            "-metadata", f"title={metadata.title}", "-metadata", f"artist={metadata.author or 'novel_pipeline'}",
            "-metadata", f"album={metadata.source_book}"]
        if metadata.chapter_number:
            command.extend(["-metadata", f"track={metadata.chapter_number}"])
        result = subprocess.run([*command, str(staged)], capture_output=True, timeout=300)
        if result.returncode or not staged.exists() or staged.stat().st_size <= 0:
            raise RuntimeError("FFmpeg failed to merge chapter audio")
        os.replace(staged, output_path)
    return output_path


def _metadata_text(value):
    return str(value).replace("\\", "\\\\").replace("\n", " ").replace("\r", " ").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")


def merge_book_m4b(chapter_paths: list[Path], output_path: Path, *, metadata: AudioMetadata,
                   chapter_titles: list[str] | None = None) -> Path:
    if not chapter_paths:
        raise ValueError("No chapter audio files to merge into M4B")
    ffmpeg = ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-m4b-", dir=output_path.parent) as tmp:
        directory = Path(tmp)
        decoded = _decode_pcm(chapter_paths, directory)
        concat = directory / "chapters.ffconcat"
        _write_concat_file(decoded, concat)
        lines, elapsed_frames = [";FFMETADATA1"], 0
        for index, path in enumerate(decoded):
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                sample_rate = wav.getframerate()
            start, end = round(elapsed_frames * 1000 / sample_rate), round((elapsed_frames + frames) * 1000 / sample_rate)
            title = chapter_titles[index] if chapter_titles else f"Chương {index + 1}"
            lines.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_metadata_text(title)}"])
            elapsed_frames += frames
        chapter_metadata = directory / "chapters.ffmetadata"
        chapter_metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")
        staged = directory / "book.m4b"
        command = [ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-i", str(chapter_metadata), "-map_metadata", "1", "-map_chapters", "1", "-vn", "-c:a", "aac",
            "-b:a", "96k", "-movflags", "+faststart", "-metadata", f"title={metadata.title}",
            "-metadata", f"artist={metadata.author or 'novel_pipeline'}", "-metadata", f"album={metadata.source_book or metadata.title}",
            "-metadata", "genre=Audiobook", str(staged)]
        result = subprocess.run(command, capture_output=True, timeout=600)
        if result.returncode or not staged.exists() or staged.stat().st_size <= 0:
            raise RuntimeError("FFmpeg failed to create M4B audiobook")
        os.replace(staged, output_path)
    return output_path
