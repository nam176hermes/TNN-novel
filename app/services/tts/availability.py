"""Local runtime availability checks for GPU-only F5 TTS."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass

from app.config import settings


F5_PROVIDER_ALIASES = frozenset({"f5", "f5_tts", "f5_vietnamese", "vivioice", "vivoice"})


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

    code = "tts_unavailable"

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


def require_tts_runtime_available(provider: str | None = None, device: str | None = None) -> None:
    """Raise a safe error before F5 work can create a job or synthesize audio."""
    resolved_provider = settings.tts_provider if provider is None else provider
    if not is_f5_provider(resolved_provider):
        return

    resolved_device = settings.tts_device if device is None else device
    if str(resolved_device).strip().lower() != "cuda" or not _cuda_available():
        raise TTSUnavailableError("Local F5 TTS is unavailable: a CUDA GPU is required.")
    if not _f5_runtime_installed():
        raise TTSUnavailableError("Local F5 TTS is unavailable: the F5 runtime is not installed.")


def inspect_tts_capability(provider: str | None = None, device: str | None = None) -> TTSCapability:
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
        return TTSCapability(False, "unavailable", "gpu_required", resolved_provider)
    if not _cuda_available():
        return TTSCapability(False, "unavailable", "gpu_unavailable", resolved_provider)
    if not _f5_runtime_installed():
        return TTSCapability(False, "unavailable", "runtime_missing", resolved_provider)
    return TTSCapability(True, "available", "ready", resolved_provider)
