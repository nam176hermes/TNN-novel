"""Shared decoding for optional SQLite JSON payload columns."""
import json
from typing import Any


def decode_json_field(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback



