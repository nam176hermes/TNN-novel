import json
import logging
from pathlib import Path
import sys
import types

import pytest

from app.config import PROJECT_ROOT
from app.services.tts.f5_vietnamese_engine import (
    F5VietnameseConfig,
    F5VietnameseEngine,
    TTSEngineError,
    VoiceConfig,
    _capture_upstream_output,
    stable_audio_cache_key,
)
from app.services.tts.availability import TTSUnavailableError


def test_stable_audio_cache_hash_changes_only_when_inputs_change(tmp_path: Path) -> None:
    model = F5VietnameseConfig(model="vivioice", device="cpu", cache_dir=tmp_path)
    voice = VoiceConfig(reference_audio_path="voice.wav", reference_text="Xin chào", voice_id="reader")

    first = stable_audio_cache_key("Một đoạn văn.", voice_config=voice, model_config=model)
    second = stable_audio_cache_key("Một đoạn văn.", voice_config=voice, model_config=model)
    changed = stable_audio_cache_key("Một đoạn văn khác.", voice_config=voice, model_config=model)

    assert first == second
    assert first != changed


def test_f5_engine_captures_upstream_console_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    api_module = types.ModuleType("f5_tts.api")

    class FakeF5TTS:
        def __init__(self, **_: object) -> None:
            print("noisy f5 load")

        def infer(self, *, file_wave: str, **_: object) -> None:
            print("noisy f5 infer")
            Path(file_wave).write_bytes(b"fake wav")

    api_module.F5TTS = FakeF5TTS
    monkeypatch.setitem(sys.modules, "f5_tts", types.ModuleType("f5_tts"))
    monkeypatch.setitem(sys.modules, "f5_tts.api", api_module)
    monkeypatch.setattr(
        "app.services.tts.f5_vietnamese_engine.require_tts_runtime_available",
        lambda **_: None,
    )

    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    output = tmp_path / "output.wav"
    engine = F5VietnameseEngine(
        F5VietnameseConfig(
            model="F5TTS_Base",
            ckpt_file=str(tmp_path / "model.pt"),
            vocab_file=str(tmp_path / "vocab.txt"),
            device="cuda",
            cache_enabled=False,
            cache_dir=tmp_path,
        )
    )

    engine.synthesize_chunk(
        "Một đoạn đọc.",
        output,
        voice_config=VoiceConfig(reference_audio_path=str(reference), reference_text="một đoạn đọc"),
    )

    captured = capsys.readouterr()
    assert "noisy f5" not in captured.out
    assert "noisy f5" not in captured.err
    assert output.read_bytes() == b"fake wav"


def test_f5_upstream_diagnostics_are_structured_bounded_and_private(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_secret = "tts-" + "token-must-not-leak"
    private_provider = "private-provider-account"
    private_path = "/home/operator/private/models/checkpoint.pt"
    chapter_text = "Đây là toàn bộ nội dung chương riêng tư không được ghi log."

    with caplog.at_level(logging.DEBUG, logger="app.services.tts.f5_vietnamese_engine"):
        with _capture_upstream_output("load"):
            print(
                f"Error(s) in loading state_dict provider={private_provider} "
                f"checkpoint={private_path} secret={fake_secret}"
            )
            print(
                f"{chapter_text} CUDA out of memory Authorization: Bearer {fake_secret} "
                + ("x" * 20_000),
                file=sys.stderr,
            )

    rendered = caplog.text
    for forbidden in (fake_secret, private_provider, private_path, chapter_text, "x" * 256):
        assert forbidden not in rendered

    payloads = [
        json.loads(record.getMessage().split("=", 1)[1])
        for record in caplog.records
        if record.getMessage().startswith("novel_observability=")
    ]
    assert payloads == [
        {
            "category": "model_load_failed",
            "diagnostic": "Model weights could not be loaded.",
            "event": "tts_upstream_diagnostic",
            "stage": "load",
            "stream": "stdout",
            "truncated": False,
        },
        {
            "category": "gpu_out_of_memory",
            "diagnostic": "CUDA GPU ran out of memory.",
            "event": "tts_upstream_diagnostic",
            "stage": "load",
            "stream": "stderr",
            "truncated": True,
        },
    ]
    assert all(len(record.getMessage()) <= 320 for record in caplog.records)


def test_f5_upstream_diagnostic_rejects_untrusted_stage_and_raw_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.services.tts.f5_vietnamese_engine"):
        with _capture_upstream_output("load secret=/private/provider/path"):
            print("unclassified provider output with private chapter prose")

    assert "secret=/private/provider/path" not in caplog.text
    assert "private chapter prose" not in caplog.text
    payload = json.loads(caplog.records[-1].getMessage().split("=", 1)[1])
    assert payload == {
        "category": "suppressed",
        "diagnostic": "Upstream output was suppressed.",
        "event": "tts_upstream_diagnostic",
        "stage": "unknown",
        "stream": "stdout",
        "truncated": False,
    }


def test_f5_retry_failure_does_not_log_or_raise_raw_provider_details(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_secret = "runtime-" + "secret-must-not-leak"
    private_provider = "provider-account-private"
    private_path = "/srv/private/models/voice.ckpt"
    chapter_text = "Nội dung chương tuyệt mật chỉ dành cho kiểm thử."

    class FailingEngine:
        def infer(self, **_: object) -> None:
            raise RuntimeError(
                f"provider={private_provider} path={private_path} "
                f"token={fake_secret} chapter text: {chapter_text}"
            )

    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    engine = F5VietnameseEngine(
        F5VietnameseConfig(
            model="F5TTS_Base",
            device="cuda",
            cache_enabled=False,
            cache_dir=tmp_path,
            retries=0,
        )
    )
    engine._engine = FailingEngine()

    with caplog.at_level(logging.WARNING, logger="app.services.tts.f5_vietnamese_engine"):
        with pytest.raises(TTSEngineError) as exc_info:
            engine.synthesize_chunk(
                "Một đoạn đọc.",
                tmp_path / "output.wav",
                voice_config=VoiceConfig(
                    reference_audio_path=str(reference),
                    reference_text="một đoạn đọc",
                ),
            )

    rendered = caplog.text + str(exc_info.value)
    for forbidden in (fake_secret, private_provider, private_path, chapter_text):
        assert forbidden not in rendered
    payload = json.loads(caplog.records[-1].getMessage().split("=", 1)[1])
    assert payload == {
        "attempt": 1,
        "category": "suppressed",
        "diagnostic": "Upstream output was suppressed.",
        "event": "tts_chunk_attempt_failed",
    }


def test_f5_engine_rejects_cpu_without_loading_runtime(tmp_path: Path, monkeypatch) -> None:
    engine = F5VietnameseEngine(
        F5VietnameseConfig(
            model="vivioice",
            device="cpu",
            cache_enabled=False,
            cache_dir=tmp_path,
        )
    )
    model_resolution_called = False

    def unexpected_model_resolution():
        nonlocal model_resolution_called
        model_resolution_called = True
        raise AssertionError("model files must not be resolved without a supported GPU")

    monkeypatch.setattr(engine, "_resolve_model_files", unexpected_model_resolution)

    with pytest.raises(TTSUnavailableError) as exc_info:
        engine._load()

    assert exc_info.value.detail()["code"] == "tts_unavailable"
    assert "CUDA GPU is required" in str(exc_info.value)
    assert model_resolution_called is False


def test_f5_engine_resolves_relative_checkpoint_paths_from_project_root(tmp_path: Path) -> None:
    engine = F5VietnameseEngine(
        F5VietnameseConfig(
            model="vivioice",
            ckpt_file="data/models/tts/vivoice/model_last.pt",
            vocab_file="data/models/tts/vivoice/vocab.txt",
            device="cpu",
            cache_dir=tmp_path,
        )
    )

    model_name, ckpt_file, vocab_file = engine._resolve_model_files()

    assert model_name == "F5TTS_Base"
    assert ckpt_file == str(PROJECT_ROOT / "data/models/tts/vivoice/model_last.pt")
    assert vocab_file == str(PROJECT_ROOT / "data/models/tts/vivoice/vocab.txt")
