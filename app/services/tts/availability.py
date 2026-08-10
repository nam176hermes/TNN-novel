"""Local runtime availability checks for GPU-only F5 TTS."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import PROJECT_ROOT, settings


F5_PROVIDER_ALIASES = frozenset({"f5", "f5_tts", "f5_vietnamese", "vivioice", "vivoice"})
VIVIOICE_MODEL_ALIASES = frozenset({"vivioice", "vivoice", "f5_vietnamese", "f5-tts-vietnamese-vivoice"})


@dataclass(frozen=True)
class TTSCapability:
    available: bool
    status: str
    reason: str
    provider: str
    required: bool = False

    def safe_dict(self) -> dict[str, object]:
        return asdict(self)


class TTSUnavailableError(RuntimeError):
    """Raised when the configured local TTS runtime cannot accept work."""

    def __init__(self, message: str, *, code: str = "tts_unavailable") -> None:
        super().__init__(message)
        self.code = code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def is_f5_provider(provider: str | None) -> bool:
    return str(provider or "").strip().lower() in F5_PROVIDER_ALIASES


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False

    return bool(torch.cuda.is_available())


def _f5_runtime_installed() -> bool:
    return importlib.util.find_spec("f5_tts") is not None


def _configured_model_file_exists(value: str) -> bool:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.is_file()


def _f5_model_prerequisites_available(
    *,
    model: str,
    model_repo: str,
    ckpt_file: str,
    vocab_file: str,
) -> bool:
    if model.strip().lower() not in VIVIOICE_MODEL_ALIASES:
        return True

    checkpoint = ckpt_file.strip()
    vocabulary = vocab_file.strip()
    if checkpoint or vocabulary:
        return bool(
            checkpoint
            and vocabulary
            and _configured_model_file_exists(checkpoint)
            and _configured_model_file_exists(vocabulary)
        )
    return bool(model_repo.strip())


def require_tts_runtime_available(
    provider: str | None = None,
    device: str | None = None,
    *,
    model: str | None = None,
    model_repo: str | None = None,
    ckpt_file: str | None = None,
    vocab_file: str | None = None,
) -> None:
    """Raise a safe error before F5 work can create a job or synthesize audio."""
    resolved_provider = settings.tts_provider if provider is None else provider
    if not is_f5_provider(resolved_provider):
        return

    resolved_device = settings.tts_device if device is None else device
    if str(resolved_device).strip().lower() != "cuda" or not _cuda_available():
        raise TTSUnavailableError(
            "Local F5 TTS is unavailable: a CUDA GPU is required.",
            code="gpu_unavailable",
        )
    if not _f5_runtime_installed():
        raise TTSUnavailableError(
            "Local F5 TTS is unavailable: the F5 runtime is not installed.",
            code="runtime_missing",
        )

    if not _f5_model_prerequisites_available(
        model=settings.tts_model if model is None else model,
        model_repo=settings.tts_model_repo if model_repo is None else model_repo,
        ckpt_file=settings.tts_ckpt_file if ckpt_file is None else ckpt_file,
        vocab_file=settings.tts_vocab_file if vocab_file is None else vocab_file,
    ):
        raise TTSUnavailableError(
            "Local F5 TTS is unavailable: required model files or configuration are missing.",
            code="model_missing",
        )


def inspect_tts_capability(
    provider: str | None = None,
    device: str | None = None,
    *,
    model: str | None = None,
    model_repo: str | None = None,
    ckpt_file: str | None = None,
    vocab_file: str | None = None,
) -> TTSCapability:
    """Return a bounded capability state without loading a model or creating work."""

    resolved_provider = str(settings.tts_provider if provider is None else provider).strip().lower()
    if not is_f5_provider(resolved_provider):
        return TTSCapability(
            available=True,
            status="available",
            reason="external_provider_configured",
            provider=resolved_provider or "unknown",
        )
    resolved_device = str(settings.tts_device if device is None else device).strip().lower()
    if resolved_device != "cuda":
        return TTSCapability(False, "unavailable", "gpu_unavailable", resolved_provider)
    if not _cuda_available():
        return TTSCapability(False, "unavailable", "gpu_unavailable", resolved_provider)
    if not _f5_runtime_installed():
        return TTSCapability(False, "unavailable", "runtime_missing", resolved_provider)
    if not _f5_model_prerequisites_available(
        model=settings.tts_model if model is None else model,
        model_repo=settings.tts_model_repo if model_repo is None else model_repo,
        ckpt_file=settings.tts_ckpt_file if ckpt_file is None else ckpt_file,
        vocab_file=settings.tts_vocab_file if vocab_file is None else vocab_file,
    ):
        return TTSCapability(False, "unavailable", "model_missing", resolved_provider)
    return TTSCapability(True, "available", "ready", resolved_provider)
