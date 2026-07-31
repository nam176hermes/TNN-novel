from __future__ import annotations

import ipaddress
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

    client_host = request.client.host if request.client else ""
    try:
        client_is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        client_is_loopback = client_host.strip().lower() in _LOCAL_HOSTS
    if not client_is_loopback:
        return True

    host = request.url.hostname or request.headers.get("host", "").split(":", 1)[0]
    host = host.strip().lower().strip("[]")
    return host not in _LOCAL_HOSTS and not host.endswith(".localhost")


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
