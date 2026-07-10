from __future__ import annotations

import os
from pathlib import Path

import requests

from app.config import PROJECT_ROOT
from app.database.db import get_provider_defaults, get_usage_summary, list_model_providers
from app.mobile_api.dependencies import get_db_path


def _coerce_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ProviderService:
    def __init__(self) -> None:
        self.db_path = get_db_path()
        self.env_path = PROJECT_ROOT / ".env"

    def _normalize_provider(self, provider: dict) -> dict:
        normalized = dict(provider)
        api_key_env = str(normalized.get("api_key_env") or "").strip()
        normalized["api_key_env"] = api_key_env
        normalized["api_key_set"] = bool(api_key_env and os.environ.get(api_key_env, "").strip())
        normalized["temperature"] = _coerce_float(normalized.get("temperature"), 0.3)
        normalized["timeout_seconds"] = _coerce_int(normalized.get("timeout_seconds"), 180)
        normalized["supports_streaming"] = _coerce_int(normalized.get("supports_streaming"), 0)
        normalized["supports_batch"] = _coerce_int(normalized.get("supports_batch"), 0)
        normalized["cost_input_per_1m"] = _coerce_float(normalized.get("cost_input_per_1m"), 0)
        normalized["cost_output_per_1m"] = _coerce_float(normalized.get("cost_output_per_1m"), 0)
        normalized["enabled"] = _coerce_int(normalized.get("enabled"), 1)
        return normalized

    def list_providers(self) -> list[dict]:
        return [self._normalize_provider(provider) for provider in list_model_providers(self.db_path)]

    def get_provider(self, provider_id: str) -> dict | None:
        for provider in self.list_providers():
            if provider["id"] == provider_id:
                return provider
        return None

    def get_defaults(self) -> dict[str, str]:
        return get_provider_defaults(self.db_path)

    def _write_env_value(self, key: str, value: str) -> None:
        env_path = Path(getattr(self, "env_path", PROJECT_ROOT / ".env"))
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        updated_lines: list[str] = []
        replaced = False
        prefix = f"{key}="

        for line in lines:
            if line.startswith(prefix):
                if not replaced:
                    updated_lines.append(f"{key}={value}")
                    replaced = True
                continue
            updated_lines.append(line)

        if not replaced:
            if updated_lines and updated_lines[-1] != "":
                updated_lines.append("")
            updated_lines.append(f"{key}={value}")

        env_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = env_path.with_name(f"{env_path.name}.tmp")
        tmp_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        tmp_path.replace(env_path)

    def update_provider_key(self, provider_id: str, api_key: str) -> dict:
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        api_key_env = str(provider.get("api_key_env") or "").strip()
        if not api_key_env:
            raise ValueError(f"Provider {provider_id} has no API key env var")

        value = api_key.strip()
        if not value:
            raise ValueError(f"{api_key_env} value is empty")
        if "\n" in value or "\r" in value:
            raise ValueError(f"{api_key_env} value must be a single line")

        self._write_env_value(api_key_env, value)
        os.environ[api_key_env] = value
        return self.get_provider(provider_id) or provider

    def estimate_cost(
        self,
        *,
        provider_id: str,
        source_chars: int,
        chapter_count: int = 1,
        prompt_overhead_tokens: int = 1500,
        max_cost_usd: float | None = None,
    ) -> dict:
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        source_tokens = max(1, int(source_chars / 1.5))
        estimated_input_tokens = source_tokens + prompt_overhead_tokens * chapter_count
        estimated_output_tokens = max(1, int(source_tokens * 1.25))
        cost = (
            estimated_input_tokens * float(provider["cost_input_per_1m"])
            + estimated_output_tokens * float(provider["cost_output_per_1m"])
        ) / 1_000_000
        rounded_cost = round(cost, 6)

        return {
            "provider_id": provider["id"],
            "model": provider["model"],
            "chapter_count": chapter_count,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_cost_usd": rounded_cost,
            "within_budget": True if max_cost_usd is None else rounded_cost <= max_cost_usd,
        }

    def test_provider(self, provider_id: str, prompt: str) -> dict:
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        api_key_env = provider.get("api_key_env") or ""
        api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
        if api_key_env and not api_key:
            raise ValueError(f"Provider {provider_id} requires {api_key_env}")

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = requests.post(
            f"{provider['base_url'].rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": provider["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": provider.get("temperature", 0.3),
                "stream": False,
            },
            timeout=int(provider.get("timeout_seconds") or 180),
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        return {
            "provider_id": provider_id,
            "model": provider["model"],
            "ok": bool(text.strip()),
            "sample": text.strip()[:500],
        }

    def usage_summary(self) -> dict:
        return get_usage_summary(self.db_path)
