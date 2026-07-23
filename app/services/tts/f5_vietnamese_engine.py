from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import io
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, settings
from app.services.tts.availability import require_tts_runtime_available

logger = logging.getLogger(__name__)


class TTSEngineError(RuntimeError):
    pass


class TTSDependencyError(TTSEngineError):
    pass


class TTSConfigurationError(TTSEngineError):
    pass


@dataclass(frozen=True)
class VoiceConfig:
    reference_audio_path: str = ""
    reference_text: str = ""
    voice_id: str = "default"
    rate: str = "-5%"
    volume: str = "+0%"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None) -> "VoiceConfig":
        payload = dict(data or {})
        return cls(
            reference_audio_path=str(payload.get("reference_audio_path") or settings.tts_reference_audio_path or ""),
            reference_text=str(payload.get("reference_text") or settings.tts_reference_text or ""),
            voice_id=str(payload.get("voice_id") or payload.get("voice") or "default"),
            rate=str(payload.get("rate") or "-5%"),
            volume=str(payload.get("volume") or "+0%"),
        )

    def safe_dict(self) -> dict[str, str]:
        return {
            "reference_audio_path": self.reference_audio_path,
            "reference_text": self.reference_text,
            "voice_id": self.voice_id,
            "rate": self.rate,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class F5VietnameseConfig:
    provider: str = "f5_vietnamese"
    model: str = "vivioice"
    model_repo: str = "hynt/F5-TTS-Vietnamese-ViVoice"
    ckpt_file: str = ""
    vocab_file: str = ""
    device: str = "cuda"
    sample_rate: int = 24000
    cache_enabled: bool = True
    cache_dir: Path = Path("data/audio/cache")
    timeout_seconds: int = 120
    retries: int = 2

    @classmethod
    def from_settings(cls, cache_dir: Path | None = None) -> "F5VietnameseConfig":
        return cls(
            provider=settings.tts_provider,
            model=settings.tts_model,
            model_repo=settings.tts_model_repo,
            ckpt_file=settings.tts_ckpt_file,
            vocab_file=settings.tts_vocab_file,
            device=settings.tts_device,
            sample_rate=settings.tts_audio_sample_rate,
            cache_enabled=settings.tts_cache,
            cache_dir=cache_dir or (settings.resolved_data_dir / "audio" / "cache"),
            timeout_seconds=settings.tts_chunk_timeout_seconds,
            retries=settings.tts_chunk_retries,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_repo": self.model_repo,
            "ckpt_file": self.ckpt_file,
            "vocab_file": self.vocab_file,
            "device": self.device,
            "sample_rate": self.sample_rate,
            "cache_enabled": self.cache_enabled,
        }


def stable_audio_cache_key(
    normalized_text: str,
    *,
    voice_config: VoiceConfig,
    model_config: F5VietnameseConfig,
) -> str:
    payload = {
        "text": normalized_text,
        "voice": voice_config.safe_dict(),
        "model": model_config.safe_dict(),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest


def _resolve_device(requested: str) -> str:
    requested = (requested or "").strip().lower()
    require_tts_runtime_available(provider="f5_vietnamese", device=requested)
    return "cuda"


def _resolve_project_path(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


@contextlib.contextmanager
def _capture_upstream_output(label: str):
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            yield
    finally:
        output = "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue()) if part.strip())
        if output:
            logger.debug("Captured F5-TTS %s output:\n%s", label, output[-4000:])


class F5VietnameseEngine:
    def __init__(self, config: F5VietnameseConfig | None = None):
        self.config = config or F5VietnameseConfig.from_settings()
        self._engine: Any | None = None

    def _load(self):
        if self._engine is not None:
            return self._engine
        device = _resolve_device(self.config.device)
        try:
            from f5_tts.api import F5TTS  # type: ignore
        except ImportError as exc:
            raise TTSDependencyError("F5-TTS is not installed. Install f5-tts and configure ViVoice before using local Vietnamese TTS.") from exc
        model_name, ckpt_file, vocab_file = self._resolve_model_files()
        try:
            with _capture_upstream_output("load"):
                self._engine = F5TTS(
                    model=model_name,
                    ckpt_file=ckpt_file,
                    vocab_file=vocab_file,
                    device=device,
                )
        except TypeError:
            with _capture_upstream_output("load"):
                self._engine = F5TTS(model=model_name, device=device)
        return self._engine

    def _resolve_model_files(self) -> tuple[str, str, str]:
        model = (self.config.model or "").strip()
        lowered = model.lower()
        if lowered in {"vivioice", "vivoice", "f5_vietnamese", "f5-tts-vietnamese-vivoice"}:
            model_name = "F5TTS_Base"
        else:
            model_name = model or "F5TTS_Base"

        ckpt_file = str(self.config.ckpt_file or "").strip()
        vocab_file = str(self.config.vocab_file or "").strip()
        if ckpt_file and vocab_file:
            return model_name, _resolve_project_path(ckpt_file), _resolve_project_path(vocab_file)
        if lowered not in {"vivioice", "vivoice", "f5_vietnamese", "f5-tts-vietnamese-vivoice"}:
            return model_name, ckpt_file, vocab_file

        try:
            from huggingface_hub import hf_hub_download  # type: ignore
        except ImportError as exc:
            raise TTSDependencyError("huggingface_hub is required to download the ViVoice F5-TTS checkpoint") from exc
        repo_id = (self.config.model_repo or "").strip()
        if not repo_id:
            raise TTSConfigurationError("TTS_MODEL_REPO is required when TTS_MODEL=vivioice and local checkpoint paths are not set")
        ckpt_file = ckpt_file or hf_hub_download(repo_id, "model_last.pt")
        vocab_file = vocab_file or hf_hub_download(repo_id, "config.json")
        return model_name, ckpt_file, vocab_file

    def _validate_voice(self, voice_config: VoiceConfig) -> tuple[str, str]:
        reference_audio = voice_config.reference_audio_path.strip()
        reference_text = voice_config.reference_text.strip()
        if not reference_audio:
            raise TTSConfigurationError("TTS_REFERENCE_AUDIO_PATH is required for F5-TTS/ViVoice voice cloning")
        path = Path(reference_audio).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise TTSConfigurationError("Configured TTS reference audio file does not exist")
        if not reference_text:
            raise TTSConfigurationError("TTS_REFERENCE_TEXT is required for F5-TTS/ViVoice")
        return str(path), reference_text

    def synthesize_chunk(
        self,
        normalized_text: str,
        output_wav_path: Path,
        *,
        voice_config: VoiceConfig,
    ) -> Path:
        if not normalized_text.strip():
            raise ValueError("Cannot synthesize empty TTS chunk")
        reference_audio, reference_text = self._validate_voice(voice_config)
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)
        cache_key = stable_audio_cache_key(
            normalized_text,
            voice_config=voice_config,
            model_config=self.config,
        )
        cache_path = self.config.cache_dir / f"{cache_key}.wav"
        if self.config.cache_enabled and cache_path.exists() and cache_path.stat().st_size > 0:
            shutil.copy2(cache_path, output_wav_path)
            return output_wav_path

        last_error: Exception | None = None
        for attempt in range(max(1, self.config.retries + 1)):
            try:
                self._infer_with_timeout(normalized_text, reference_audio, reference_text, output_wav_path)
                if self.config.cache_enabled:
                    self.config.cache_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(output_wav_path, cache_path)
                return output_wav_path
            except Exception as exc:
                last_error = exc
                logger.warning("F5 TTS chunk attempt %s failed: %s", attempt + 1, exc)
                output_wav_path.unlink(missing_ok=True)
        raise TTSEngineError(f"F5 TTS chunk failed after retries: {last_error}") from last_error

    def _infer_with_timeout(
        self,
        normalized_text: str,
        reference_audio: str,
        reference_text: str,
        output_wav_path: Path,
    ) -> None:
        engine = self._load()

        def run_infer() -> None:
            with _capture_upstream_output("infer"):
                engine.infer(
                    ref_file=reference_audio,
                    ref_text=reference_text,
                    gen_text=normalized_text,
                    file_wave=str(output_wav_path),
                    seed=None,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_infer)
            future.result(timeout=max(1, self.config.timeout_seconds))
