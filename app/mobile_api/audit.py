from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from app.database.db import find_user_by_username, record_operational_event
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_db_path

logger = logging.getLogger(__name__)

_PUBLIC_PATH_KEYS = ("path", "dir", "directory", "file")


def _request_actor(request: Request | None) -> str:
    if request is None:
        return ""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return str(user.get("username") or "")
    return ""


def _request_actor_user_id(request: Request | None) -> str:
    if request is None:
        return ""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return str(user.get("user_id") or "")
    return ""


def _request_client_host(request: Request | None) -> str:
    if request is None or request.client is None:
        return ""
    return request.client.host or ""


def _request_id(request: Request | None) -> str:
    if request is None:
        return ""
    return request.headers.get("X-Request-ID", "") or request.headers.get("X-Correlation-ID", "")


def _public_safe_details(details: dict[str, Any]) -> dict[str, Any]:
    if not mobile_settings.public_deploy:
        return details
    safe: dict[str, Any] = {}
    for key, value in details.items():
        key_text = str(key)
        value_text = str(value)
        if any(marker in key_text.lower() for marker in _PUBLIC_PATH_KEYS) and ("/" in value_text or "\\" in value_text):
            safe[key_text] = "[redacted]"
        else:
            safe[key_text] = value
    return safe


def _resolve_actor_user_id(
    request: Request | None,
    details: dict[str, Any],
    explicit_actor_user_id: str = "",
) -> str:
    if explicit_actor_user_id:
        return explicit_actor_user_id
    request_actor_id = _request_actor_user_id(request)
    if request_actor_id:
        return request_actor_id
    username = str(details.get("username") or details.get("actor") or "").strip()
    if not username:
        return ""
    try:
        user = find_user_by_username(get_db_path(), username)
    except Exception:
        logger.debug("Could not resolve audit actor user id for %s", username, exc_info=True)
        return ""
    return str(user.get("id") or "") if user else ""


def record_audit_event(
    *,
    event_type: str,
    severity: str = "info",
    source: str,
    message: str,
    request: Request | None = None,
    job_id: str = "",
    details: dict[str, Any] | None = None,
    actor_user_id: str = "",
    owner_user_id: str = "",
) -> None:
    event_details = dict(details or {})
    actor = _request_actor(request)
    if actor:
        event_details.setdefault("actor", actor)
    request_id = _request_id(request)
    if request_id:
        event_details.setdefault("request_id", request_id)
    client_host = _request_client_host(request)
    if client_host:
        event_details.setdefault("client_host", client_host)
    resolved_actor_user_id = _resolve_actor_user_id(request, event_details, actor_user_id)
    resolved_owner_user_id = owner_user_id or resolved_actor_user_id

    try:
        record_operational_event(
            get_db_path(),
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            job_id=job_id,
            details=_public_safe_details(event_details),
            actor_user_id=resolved_actor_user_id,
            owner_user_id=resolved_owner_user_id,
        )
    except Exception:
        logger.warning("Failed to record operational event %s", event_type, exc_info=True)
