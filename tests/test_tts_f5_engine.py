from pathlib import Path
import sys
import types

from app.config import PROJECT_ROOT
from app.services.tts.f5_vietnamese_engine import (
    F5VietnameseConfig,
    F5VietnameseEngine,
    VoiceConfig,
    stable_audio_cache_key,
)


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

    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    output = tmp_path / "output.wav"
    engine = F5VietnameseEngine(
        F5VietnameseConfig(
            model="F5TTS_Base",
            ckpt_file=str(tmp_path / "model.pt"),
            vocab_file=str(tmp_path / "vocab.txt"),
            device="cpu",
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
