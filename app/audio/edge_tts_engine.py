from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

try:
    import edge_tts
except ModuleNotFoundError:  # pragma: no cover - runtime dependency branch
    edge_tts = SimpleNamespace(Communicate=None)

from app.config import settings
from app.audio.audio_splitter import split_text_for_tts
from app.audio.audio_merger import merge_audio_segments
from app.audio.ffmpeg_utils import embed_metadata, normalize_audio
from app.utils.asyncio_bridge import run_coro_sync


async def _synthesize_chunk(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = "+0%",
    volume: str = "+0%",
) -> None:
    """Synthesize a single chunk of text to MP3 using edge-tts."""
    communicate_cls = getattr(edge_tts, "Communicate", None)
    if communicate_cls is None:
        raise RuntimeError("edge-tts is not installed. Install edge-tts or configure local F5 TTS.")
    voice = voice or settings.edge_tts_voice
    communicate = communicate_cls(text, voice, rate=rate, volume=volume)
    await communicate.save(str(output_path))


def text_to_speech_file(
    text: str,
    output_path: Path,
    book_title: str = "",
    chapter_number: int = 0,
    chapter_title: str = "",
    voice: Optional[str] = None,
    rate: str = "-5%",
    volume: str = "+0%",
) -> None:
    """Convert Vietnamese text to speech, split into chunks, merge, and embed metadata."""
    # Split text into TTS-friendly chunks
    chunks = split_text_for_tts(text)
    if not chunks:
        raise ValueError("No text to synthesize")

    # Create temporary directory for chunks
    tmp_dir = output_path.parent / f"tts_tmp_{output_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Synthesize chunks in one event loop (avoid asyncio.run() per chunk)
    async def _synthesize_all() -> list[Path]:
        chunk_paths: list[Path] = []
        for i, chunk in enumerate(chunks, 1):
            chunk_path = tmp_dir / f"chunk_{i:03d}.mp3"
            try:
                await _synthesize_chunk(chunk, chunk_path, voice=voice, rate=rate, volume=volume)
                chunk_paths.append(chunk_path)
            except Exception as e:
                for p in chunk_paths:
                    p.unlink(missing_ok=True)
                tmp_dir.rmdir()
                raise RuntimeError(f"TTS failed on chunk {i}: {e}") from e
        return chunk_paths

    chunk_paths = run_coro_sync(_synthesize_all())

    # Merge chunks
    merge_audio_segments(chunk_paths, output_path)

    # Clean up chunk files
    for p in chunk_paths:
        p.unlink(missing_ok=True)
    tmp_dir.rmdir()

    # Normalize loudness
    normalize_audio(output_path)

    # Embed metadata
    title = f"{book_title} - Chương {chapter_number}"
    if chapter_title:
        title += f": {chapter_title}"
    embed_metadata(
        output_path,
        title=title,
        artist="novel_pipeline",
        album=book_title,
        track=chapter_number,
        genre="Audiobook",
    )
