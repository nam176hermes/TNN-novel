from __future__ import annotations

import hashlib
import unicodedata


def normalize_import_text(text: str) -> str:
    """Return the canonical text representation used for stored chapters."""

    normalized = unicodedata.normalize("NFC", str(text or ""))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").lstrip("\ufeff")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def source_hash(text: str) -> str:
    """Hash the same normalized representation that is persisted by imports."""

    return hashlib.sha256(normalize_import_text(text).encode("utf-8")).hexdigest()
