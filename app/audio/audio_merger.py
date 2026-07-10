from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

def merge_audio_segments(segment_paths: List[Path], output_path: Path) -> Path:
    """Merge multiple MP3 files into one using FFmpeg concat demuxer."""
    if not segment_paths:
        raise ValueError("No segments to merge")

    # Create a temporary file list for FFmpeg
    list_file = segment_paths[0].parent / "ffmpeg_list.txt"
    try:
        with list_file.open("w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{p.as_posix()}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg merge failed: {result.stderr}")
        return output_path
    finally:
        if list_file.exists():
            list_file.unlink()
