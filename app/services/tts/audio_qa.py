from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
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
    with wave.open(str(path), "rb") as wav:
        channels = max(1, wav.getnchannels())
        sample_width = wav.getsampwidth()
        frames = wav.getnframes()
        frame_rate = wav.getframerate()
        raw = wav.readframes(frames)
    duration = frames / frame_rate if frame_rate else 0
    if not raw or sample_width not in {1, 2, 3, 4}:
        return duration, 0, 0, 0

    if sample_width == 1:
        samples = [sample - 128 for sample in raw]
        max_abs = 128
    elif sample_width == 2:
        count = len(raw) // 2
        samples = list(struct.unpack(f"<{count}h", raw[: count * 2]))
        max_abs = 32768
    elif sample_width == 3:
        samples = []
        for index in range(0, len(raw) - 2, 3):
            value = int.from_bytes(raw[index:index + 3], "little", signed=True)
            samples.append(value)
        max_abs = 8388608
    else:
        count = len(raw) // 4
        samples = list(struct.unpack(f"<{count}i", raw[: count * 4]))
        max_abs = 2147483648

    if channels > 1 and samples:
        # Keep QA cheap; aggregate over interleaved samples rather than channel splitting.
        pass
    if not samples:
        return duration, 0, 0, 0
    square_sum = sum(float(sample) * float(sample) for sample in samples)
    rms = math.sqrt(square_sum / len(samples)) / max_abs
    peak_abs = max(abs(sample) for sample in samples)
    peak = peak_abs / max_abs
    clipped = sum(1 for sample in samples if abs(sample) >= max_abs * 0.98)
    clipped_ratio = clipped / len(samples)
    return duration, rms, peak, clipped_ratio


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
            duration = _probe_duration(path)
            rms = 0
            peak = 0
            clipped_ratio = 0
    except (OSError, wave.Error, struct.error) as exc:
        return AudioQAResult(False, error=f"Audio QA failed: {exc}")

    if duration <= min_duration_seconds:
        return AudioQAResult(False, duration_seconds=duration, rms=rms, peak=peak, clipped_ratio=clipped_ratio, error="Audio duration is too short")
    if path.suffix.lower() == ".wav":
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
