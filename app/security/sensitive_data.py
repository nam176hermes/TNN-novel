"""Shared predicates for fields that must not cross durable boundaries."""

from __future__ import annotations

from urllib.parse import unquote_plus


_CREDENTIAL_KEY_MARKERS = (
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
_SENSITIVE_PAYLOAD_KEY_MARKERS = (
    *_CREDENTIAL_KEY_MARKERS,
    "content",
    "html",
)


def _normalized_key_name(value: object) -> str:
    decoded = str(value)
    for _ in range(3):
        unquoted = unquote_plus(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    return "".join(character for character in decoded.casefold() if character.isalnum())


def is_credential_key_name(value: object) -> bool:
    """Match credential field names independent of case and separators."""
    normalized = _normalized_key_name(value)
    return any(marker in normalized for marker in _CREDENTIAL_KEY_MARKERS)


def is_sensitive_payload_key_name(value: object) -> bool:
    """Match content or credential field names forbidden in durable metadata."""
    normalized = _normalized_key_name(value)
    return any(marker in normalized for marker in _SENSITIVE_PAYLOAD_KEY_MARKERS)
