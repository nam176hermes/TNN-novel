from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from app.mobile_api.config import mobile_settings

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "test"}
_SENSITIVE_KEY_MARKERS = ("path", "dir", "directory", "file", "database")


def is_public_request(request: Request | None) -> bool:
    if mobile_settings.public_deploy:
        return True
    if request is None:
        return False

    host = request.url.hostname or request.headers.get("host", "").split(":", 1)[0]
    host = host.strip().lower().strip("[]")
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return False
    return True


def public_safe_value(key: str, value: Any) -> Any:
    key_text = str(key).lower()
    if isinstance(value, str) and any(marker in key_text for marker in _SENSITIVE_KEY_MARKERS):
        if "/" in value or "\\" in value:
            return ""
    return value


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_public_payload(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_public_payload(public_safe_value(str(key), item))
            for key, item in value.items()
        }
    return value
