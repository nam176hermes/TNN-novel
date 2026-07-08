from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

def embed_metadata(
    audio_path: Path,
    title: str,
    artist: str = "novel_pipeline",
    album: str = "",
    track: Optional[int] = None,
    genre: str = "Audiobook",
) -> None:
    """Embed ID3 metadata into an MP3 file using FFmpeg."""
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Build FFmpeg metadata arguments
    args = ["-metadata", f"title={title}", "-metadata", f"artist={artist}"]
    if album:
        args.extend(["-metadata", f"album={album}"])
    if track is not None:
        args.extend(["-metadata", f"track={track}"])
    if genre:
        args.extend(["-metadata", f"genre={genre}"])

    # Output to a temp file then replace
    temp_path = audio_path.with_suffix(".tmp.mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
    ] + args + [
        "-codec",
        "copy",
        str(temp_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg metadata failed: {result.stderr}")

    # Replace original
    temp_path.replace(audio_path)


def normalize_audio(
    input_path: Path,
    output_path: Optional[Path] = None,
    target_loudness: float = -16.0,
) -> Path:
    """Normalize audio loudness using FFmpeg's loudnorm filter."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    out = output_path or input_path.with_suffix(".norm.mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        f"loudnorm=I={target_loudness}:TP=-1.5:LRA=11",
        "-codec:a",
        "libmp3lame",
        "-qscale:a",
        "2",
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg normalization failed: {result.stderr}")

    if output_path is None:
        out.replace(input_path)
        return input_path
    return out
