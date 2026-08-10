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
    monkeypatch.setattr(
        "app.services.tts.availability._f5_runtime_installed",
        lambda: pytest.fail("runtime must not be checked before CUDA"),
    )
    monkeypatch.setattr(
        "app.services.tts.availability._f5_model_prerequisites_available",
        lambda **_kwargs: pytest.fail("model must not be checked before CUDA"),
        raising=False,
    )

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(provider="f5_vietnamese", device="cuda")

    assert exc_info.value.detail() == {
        "code": "gpu_unavailable",
        "message": "Local F5 TTS is unavailable: a CUDA GPU is required.",
    }


def test_f5_without_runtime_raises_safe_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: True)
    monkeypatch.setattr("app.services.tts.availability._f5_runtime_installed", lambda: False)
    monkeypatch.setattr(
        "app.services.tts.availability._f5_model_prerequisites_available",
        lambda **_kwargs: pytest.fail("model must not be checked before runtime"),
        raising=False,
    )

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(provider="f5", device="cuda")

    assert exc_info.value.detail()["code"] == "runtime_missing"
    assert "runtime is not installed" in exc_info.value.detail()["message"]


def test_f5_without_model_prerequisites_raises_model_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: True)
    monkeypatch.setattr("app.services.tts.availability._f5_runtime_installed", lambda: True)

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(
            provider="f5",
            device="cuda",
            model="vivioice",
            model_repo="",
            ckpt_file=str(tmp_path / "missing-model.pt"),
            vocab_file=str(tmp_path / "missing-vocab.json"),
        )

    assert exc_info.value.detail() == {
        "code": "model_missing",
        "message": "Local F5 TTS is unavailable: required model files or configuration are missing.",
    }


def test_f5_accepts_configured_model_repository(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: True)
    monkeypatch.setattr("app.services.tts.availability._f5_runtime_installed", lambda: True)

    require_tts_runtime_available(
        provider="f5",
        device="cuda",
        model="vivioice",
        model_repo="owner/model",
        ckpt_file="",
        vocab_file="",
    )


def test_explicit_non_f5_provider_is_not_blocked(monkeypatch) -> None:
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    require_tts_runtime_available(provider="edge_tts", device="cpu")
