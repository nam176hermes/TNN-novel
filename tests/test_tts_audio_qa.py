from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from app.services.tts.audio_qa import analyze_audio


def _write_wav(path: Path, *, silent: bool = False, duration_seconds: float = 0.25) -> None:
    sample_rate = 24000
    frames = int(sample_rate * duration_seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = bytearray()
        for index in range(frames):
            value = 0 if silent else int(math.sin(index / 12) * 9000)
            payload.extend(struct.pack("<h", value))
        wav.writeframes(bytes(payload))


def test_audio_qa_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")

    result = analyze_audio(path, text="Xin chào")

    assert result.passed is False
    assert "empty" in result.error.lower()


def test_audio_qa_rejects_silent_wav(tmp_path: Path) -> None:
    path = tmp_path / "silent.wav"
    _write_wav(path, silent=True)

    result = analyze_audio(path, text="Xin chào")

    assert result.passed is False
    assert "silent" in result.error.lower()


def test_audio_qa_accepts_valid_wav(tmp_path: Path) -> None:
    path = tmp_path / "voice.wav"
    _write_wav(path)

    result = analyze_audio(path, text="Xin chào")

    assert result.passed is True
    assert result.duration_seconds > 0
    assert result.rms > 0
