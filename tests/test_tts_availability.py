from __future__ import annotations

import pytest

from app.services.tts.availability import (
    TTSUnavailableError,
    is_f5_provider,
    require_tts_runtime_available,
)


def test_f5_provider_aliases_are_classified_case_insensitively() -> None:
    assert is_f5_provider("f5")
    assert is_f5_provider("F5_TTS")
    assert is_f5_provider("f5_vietnamese")
    assert is_f5_provider("vivioice")
    assert is_f5_provider("vivoice")
    assert not is_f5_provider("edge_tts")


def test_f5_without_cuda_raises_safe_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(provider="f5_vietnamese", device="cuda")

    assert exc_info.value.detail() == {
        "code": "tts_unavailable",
        "message": "Local F5 TTS is unavailable: a CUDA GPU is required.",
    }


def test_f5_without_runtime_raises_safe_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: True)
    monkeypatch.setattr("app.services.tts.availability._f5_runtime_installed", lambda: False)

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(provider="f5", device="cuda")

    assert exc_info.value.detail()["code"] == "tts_unavailable"
    assert "runtime is not installed" in exc_info.value.detail()["message"]


def test_explicit_non_f5_provider_is_not_blocked(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    require_tts_runtime_available(provider="edge_tts", device="cpu")
