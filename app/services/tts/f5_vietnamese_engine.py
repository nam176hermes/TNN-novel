from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import shutil
import multiprocessing
import time
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, settings
from app.observability import StructuredEventLogger
from app.services.tts.availability import require_tts_runtime_available
from app.database.chapter_repository import file_digest

logger = logging.getLogger(__name__)
_events = StructuredEventLogger(logger)

_UPSTREAM_CAPTURE_MAX_CHARS = 8192
_UPSTREAM_CAPTURE_HEAD_CHARS = _UPSTREAM_CAPTURE_MAX_CHARS // 2
_UPSTREAM_STAGES = frozenset({"load", "infer"})
_UPSTREAM_STREAMS = frozenset({"stdout", "stderr"})
_UPSTREAM_DIAGNOSTIC_RULES = (
    (
        "gpu_out_of_memory",
        "CUDA GPU ran out of memory.",
        ("cuda out of memory", "outofmemoryerror", "cublas_status_alloc_failed"),
    ),
    (
        "gpu_unavailable",
        "CUDA GPU runtime or driver is unavailable.",
        (
            "cuda is not available",
            "no cuda gpu",
            "no nvidia driver",
            "cuda driver",
            "driver version is insufficient",
            "invalid device ordinal",
            "torch not compiled with cuda",
            "cuda initialization",
        ),
    ),
    (
        "model_file_missing",
        "Model checkpoint or vocabulary file is unavailable.",
        ("checkpoint not found", "model not found", "vocab not found", "filenotfounderror", "no such file or directory"),
    ),
    (
        "model_load_failed",
        "Model weights could not be loaded.",
        (
            "loading state_dict",
            "failed to load model",
            "failed to load checkpoint",
            "missing key(s) in state_dict",
            "unexpected key(s) in state_dict",
            "safetensors",
        ),
    ),
    (
        "model_download_failed",
        "Model artifact download failed.",
        ("huggingface", "hf_hub_download", "repository not found", "401 client error", "403 client error"),
    ),
    (
        "dependency_missing",
        "A required TTS runtime dependency is unavailable.",
        ("modulenotfounderror", "no module named"),
    ),
    (
        "timeout",
        "The upstream TTS operation timed out.",
        ("timed out", "timeout"),
    ),
)


class _BoundedOutputCapture(io.TextIOBase):
    """Keep a bounded head and tail while upstream libraries write console output."""

    def __init__(self, max_chars: int = _UPSTREAM_CAPTURE_MAX_CHARS) -> None:
        super().__init__()
        self.max_chars = max(2, int(max_chars))
        self.head_chars = min(_UPSTREAM_CAPTURE_HEAD_CHARS, self.max_chars // 2)
        self.tail_chars = self.max_chars - self.head_chars
        self._head = ""
        self._tail = ""
        self.total_chars = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        text = str(value)
        self.total_chars += len(text)
        head_remaining = self.head_chars - len(self._head)
        if head_remaining > 0:
            self._head += text[:head_remaining]
            text = text[head_remaining:]
        if text:
            self._tail = (self._tail + text)[-self.tail_chars :]
        return len(value)

    def getvalue(self) -> str:
        return self._head + self._tail

    @property
    def truncated(self) -> bool:
        return self.total_chars > len(self._head) + len(self._tail)


def _classify_upstream_diagnostic(value: object) -> tuple[str, str]:
    text = str(value or "")
    if len(text) > _UPSTREAM_CAPTURE_MAX_CHARS:
        half = _UPSTREAM_CAPTURE_MAX_CHARS // 2
        text = text[:half] + text[-half:]
    normalized = text.casefold()
    for category, diagnostic, markers in _UPSTREAM_DIAGNOSTIC_RULES:
        if any(marker in normalized for marker in markers):
            return category, diagnostic
    return "suppressed", "Upstream output was suppressed."


def _emit_upstream_diagnostic(*, stage: str, stream: str, capture: _BoundedOutputCapture) -> None:
    output = capture.getvalue()
    if not output.strip():
        return
    category, diagnostic = _classify_upstream_diagnostic(output)
    _events.emit(
        "tts_upstream_diagnostic",
        level=logging.DEBUG,
        stage=stage if stage in _UPSTREAM_STAGES else "unknown",
        stream=stream if stream in _UPSTREAM_STREAMS else "unknown",
        category=category,
        diagnostic=diagnostic,
        truncated=capture.truncated,
    )


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
        "version": 2,
        "text": normalized_text,
        "voice": voice_config.safe_dict(),
        "reference_digest": file_digest(Path(_resolve_project_path(voice_config.reference_audio_path))) if voice_config.reference_audio_path else None,
        "model": model_config.safe_dict(),
    }
    for name in ("ckpt_file", "vocab_file"):
        value = getattr(model_config, name)
        if value:
            try:
                stat = Path(_resolve_project_path(value)).stat()
                payload[name + "_identity"] = [stat.st_size, stat.st_mtime_ns]
            except OSError:
                payload[name + "_identity"] = None
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
    stdout = _BoundedOutputCapture()
    stderr = _BoundedOutputCapture()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            yield
    finally:
        _emit_upstream_diagnostic(stage=label, stream="stdout", capture=stdout)
        _emit_upstream_diagnostic(stage=label, stream="stderr", capture=stderr)


class F5VietnameseEngine:
    def __init__(self, config: F5VietnameseConfig | None = None):
        self.config = config or F5VietnameseConfig.from_settings()
        self._engine: Any | None = None
        self._process = None
        self._connection = None

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
        cancel_check=None,
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
        marker = cache_path.with_suffix(".qa.json")
        if self.config.cache_enabled and cache_path.exists() and marker.exists():
            try:
                receipt = json.loads(marker.read_text(encoding="utf-8"))
                if receipt.get("passed") is True and receipt.get("audio_hash") == file_digest(cache_path):
                    shutil.copy2(cache_path, output_wav_path)
                    return output_wav_path
            except (OSError, ValueError):
                pass

        last_diagnostic = "Upstream output was suppressed."
        # The pipeline owns the retry budget, including audio QA failures.
        for attempt in range(1):
            try:
                self._infer_with_timeout(normalized_text, reference_audio, reference_text, output_wav_path, cancel_check=cancel_check)
                return output_wav_path
            except Exception as exc:
                category, last_diagnostic = _classify_upstream_diagnostic(exc)
                _events.emit(
                    "tts_chunk_attempt_failed",
                    level=logging.WARNING,
                    attempt=attempt + 1,
                    category=category,
                    diagnostic=last_diagnostic,
                )
                output_wav_path.unlink(missing_ok=True)
        raise TTSEngineError(f"F5 TTS chunk failed after retries: {last_diagnostic}")

    def _infer_with_timeout(
        self,
        normalized_text: str,
        reference_audio: str,
        reference_text: str,
        output_wav_path: Path,
        *, cancel_check=None,
    ) -> None:
        deadline = time.monotonic() + max(.05, self.config.timeout_seconds)
        try:
            if self._process is None or not self._process.is_alive():
                self.close()
                context = multiprocessing.get_context("spawn")
                self._connection, child = context.Pipe()
                self._process = context.Process(target=_f5_worker, args=(child, self.config, self._engine), daemon=True)
                self._process.start()
                child.close()
            self._connection.send((normalized_text, reference_audio, reference_text, str(output_wav_path)))
            while time.monotonic() < deadline:
                if cancel_check and cancel_check():
                    raise TTSEngineError("TTS cancelled")
                if self._connection.poll(min(.1, max(0, deadline - time.monotonic()))):
                    error = self._connection.recv()
                    if error:
                        raise TTSEngineError(error)
                    return
                if not self._process.is_alive():
                    raise TTSEngineError("F5 worker exited")
            raise TTSEngineError("F5 inference deadline exceeded")
        except BaseException:
            self.close()
            output_wav_path.unlink(missing_ok=True)
            raise

    def confirm_audio_qa(self, text, voice, path):
        if not self.config.cache_enabled:
            return
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        key = stable_audio_cache_key(text, voice_config=voice, model_config=self.config)
        cache = self.config.cache_dir / f"{key}.wav"
        temporary = cache.with_name(f"{key}.{os.getpid()}.tmp")
        shutil.copy2(path, temporary)
        os.replace(temporary, cache)
        marker = cache.with_suffix(".qa.json")
        temporary = marker.with_name(f"{key}.{os.getpid()}.json.tmp")
        temporary.write_text(json.dumps({"passed": True, "audio_hash": file_digest(cache)}), encoding="utf-8")
        os.replace(temporary, marker)

    def invalidate_audio_cache(self, text, voice):
        key = stable_audio_cache_key(text, voice_config=voice, model_config=self.config)
        cache = self.config.cache_dir / f"{key}.wav"
        cache.with_suffix(".qa.json").unlink(missing_ok=True)
        cache.unlink(missing_ok=True)

    def close(self):
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=1)
        if self._connection is not None:
            self._connection.close()
        self._process = self._connection = None


def _f5_worker(connection, config, injected_engine=None):
    # One CUDA worker owns the GPU across its warm batch; close it at batch end.
    import fcntl
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    with (config.cache_dir.parent / ".f5-cuda.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        engine = F5VietnameseEngine(config)
        engine._engine = injected_engine
        while True:
            try:
                text, reference_audio, reference_text, output = connection.recv()
            except EOFError:
                return
            try:
                runtime = engine._load()
                with _capture_upstream_output("infer"):
                    runtime.infer(ref_file=reference_audio, ref_text=reference_text, gen_text=text, file_wave=output, seed=None)
                connection.send("")
            except Exception as exc:
                _, diagnostic = _classify_upstream_diagnostic(exc)
                connection.send(diagnostic)
