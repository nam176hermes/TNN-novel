"""Shared predicates for fields that must not cross durable boundaries."""

from __future__ import annotations

import re
from urllib.parse import unquote_plus


_LEGACY_SENSITIVE_PAYLOAD_MARKERS = (
    "html",
    "content",
    "cookie",
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
)
_TOKEN_CREDENTIAL_QUALIFIERS = frozenset(
    {
        "access",
        "api",
        "auth",
        "bearer",
        "csrf",
        "id",
        "openai",
        "provider",
        "refresh",
        "remote",
        "session",
    }
)
_COOKIE_CREDENTIAL_QUALIFIERS = frozenset({"auth", "session"})
_JOINED_API_KEY_QUALIFIERS = frozenset(
    {"deepseek", "gemini", "openai", "openrouter", "provider", "remote"}
)


def _decoded_key_name(value: object) -> str:
    decoded = str(value)
    seen: set[str] = set()
    while decoded not in seen:
        seen.add(decoded)
        unquoted = unquote_plus(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    return decoded


def _key_words(value: object) -> tuple[str, ...]:
    decoded = _decoded_key_name(value)
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", decoded)
    acronym_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
    return tuple(word.casefold() for word in re.findall(r"[A-Za-z0-9]+", acronym_split))


def _contains_adjacent(words: tuple[str, ...], first: str, second: str) -> bool:
    return any(left == first and right == second for left, right in zip(words, words[1:]))


def is_api_key_name(value: object) -> bool:
    """Recognize API-key field names without treating ``apiKeyboard`` as one."""
    words = _key_words(value)
    return (
        "apikey" in words
        or _contains_adjacent(words, "api", "key")
        or any(
            word.endswith("apikey")
            and word.removesuffix("apikey") in _JOINED_API_KEY_QUALIFIERS
            for word in words
        )
    )


def is_credential_query_key_name(value: object) -> bool:
    """Recognize credential query fields while preserving ordinary lookalikes."""
    words = _key_words(value)
    if not words:
        return False
    if is_api_key_name(value):
        return True
    if any(word in {"authorization", "credential", "password", "secret"} for word in words):
        return True
    if words == ("token",) or any(
        word == "token" and index > 0 and words[index - 1] in _TOKEN_CREDENTIAL_QUALIFIERS
        for index, word in enumerate(words)
    ):
        return True
    return words == ("cookie",) or any(
        word == "cookie" and index > 0 and words[index - 1] in _COOKIE_CREDENTIAL_QUALIFIERS
        for index, word in enumerate(words)
    )


def is_sensitive_payload_key_name(value: object) -> bool:
    """Match content or credential field names forbidden in durable metadata."""
    lowered = str(value).casefold()
    return is_api_key_name(value) or any(
        marker in lowered for marker in _LEGACY_SENSITIVE_PAYLOAD_MARKERS
    )
