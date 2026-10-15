from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AudioQAResult:
    passed: bool
    duration_seconds: float = 0
    rms: float = 0
    peak: float = 0
    clipped_ratio: float = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
            "rms": self.rms,
            "peak": self.peak,
            "clipped_ratio": self.clipped_ratio,
            "warnings": list(self.warnings),
            "error": self.error,
        }


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return 0
    try:
        payload = json.loads(result.stdout or "{}")
        return float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _read_wav_metrics(path: Path) -> tuple[float, float, float, float]:
    square_sum, peak_abs, clipped, count = 0, 0, 0, 0
    with wave.open(str(path), "rb") as wav:
        width = wav.getsampwidth()
        duration = wav.getnframes() / wav.getframerate()
        if width not in {1, 2, 3, 4}:
            raise wave.Error("Unsupported PCM sample width")
        max_abs = 1 << (width * 8 - 1)
        while raw := wav.readframes(8192):
            if width == 1:
                samples = [value - 128 for value in raw]
            elif width == 3:
                samples = [int.from_bytes(raw[i:i + 3], "little", signed=True) for i in range(0, len(raw), 3)]
            else:
                samples = struct.unpack(f"<{len(raw) // width}{'h' if width == 2 else 'i'}", raw)
            count += len(samples)
            square_sum += sum(value * value for value in samples)
            peak_abs = max(peak_abs, max((abs(value) for value in samples), default=0))
            clipped += sum(abs(value) >= max_abs * .98 for value in samples)
    return (duration, math.sqrt(square_sum / count) / max_abs if count else 0,
            peak_abs / max_abs, clipped / count if count else 0)


def _decode_metrics(path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise OSError("FFmpeg unavailable for decoded audio QA")
    with tempfile.TemporaryDirectory(prefix="audio-qa-") as tmp:
        pcm = Path(tmp) / "decoded.wav"
        result = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-ac", "1",
            "-ar", "24000", "-c:a", "pcm_s16le", str(pcm)], capture_output=True, timeout=300)
        if result.returncode:
            raise OSError("Audio decode failed")
        return _read_wav_metrics(pcm)


def analyze_audio(
    path: Path,
    *,
    text: str = "",
    min_duration_seconds: float = 0.05,
) -> AudioQAResult:
    if not path.exists():
        return AudioQAResult(False, error="Audio file does not exist")
    if path.stat().st_size <= 0:
        return AudioQAResult(False, error="Audio file is empty")

    warnings: list[str] = []
    try:
        if path.suffix.lower() == ".wav":
            duration, rms, peak, clipped_ratio = _read_wav_metrics(path)
        else:
            duration, rms, peak, clipped_ratio = _decode_metrics(path)
    except (OSError, wave.Error, struct.error, subprocess.TimeoutExpired):
        return AudioQAResult(False, error="Audio QA failed: audio could not be decoded")

    if duration <= min_duration_seconds:
        return AudioQAResult(False, duration_seconds=duration, rms=rms, peak=peak, clipped_ratio=clipped_ratio, error="Audio duration is too short")
    if rms < 0.0005:
        return AudioQAResult(False, duration_seconds=duration, rms=rms, peak=peak, clipped_ratio=clipped_ratio, error="Audio appears silent")
    if clipped_ratio > 0.05:
        warnings.append("Audio has heavy clipping")

    text_len = len((text or "").strip())
    if text_len:
        expected_min = max(0.2, text_len / 25)
        expected_max = max(4.0, text_len / 2)
        if duration < expected_min:
            warnings.append("Audio duration is short for text length")
        if duration > expected_max:
            warnings.append("Audio duration is long for text length")

    return AudioQAResult(
        passed=not any(warning == "Audio has heavy clipping" for warning in warnings),
        duration_seconds=round(duration, 3),
        rms=round(rms, 6),
        peak=round(peak, 6),
        clipped_ratio=round(clipped_ratio, 6),
        warnings=tuple(warnings),
    )
