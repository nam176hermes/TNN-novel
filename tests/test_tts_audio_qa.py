from __future__ import annotations

import math
import struct
import wave
import shutil
import subprocess
import pytest
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


def test_audio_qa_rejects_missing_file(tmp_path: Path) -> None:
    result = analyze_audio(tmp_path / "missing.wav", text="Xin chào")

    assert result.passed is False
    assert "does not exist" in result.error.lower()


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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required for compressed audio regression")
def test_audio_qa_decodes_mp3_and_rejects_silence(tmp_path: Path) -> None:
    wav_path, mp3_path = tmp_path / "silent.wav", tmp_path / "silent.mp3"
    _write_wav(wav_path, silent=True, duration_seconds=1)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav_path), str(mp3_path)], check=True)
    result = analyze_audio(mp3_path)
    assert not result.passed and "silent" in result.error.lower()


def test_audio_qa_rejects_mp3_when_decoder_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "voice.mp3"
    path.write_bytes(b"mp3 bytes")
    monkeypatch.setattr("app.services.tts.audio_qa.shutil.which", lambda _: None)

    result = analyze_audio(path, text="Một đoạn tiếng Việt ngắn")

    assert result.passed is False
    assert "could not be decoded" in result.error
