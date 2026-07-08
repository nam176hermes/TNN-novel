"""Translation cache — MD5 hash + gzip + SQLite.

Adapted from LibreTranslate's cache.py pattern.
Caches translated chunks so repeated sentences skip Ollama calls.
"""

from __future__ import annotations

import gzip
import hashlib
import time
from pathlib import Path
from typing import Optional

from app.database.db import get_connection


def _make_cache_key(text: str, source_lang: str, target_lang: str, model: str) -> str:
    fingerprint = f"{text}:{source_lang}:{target_lang}:{model}"
    return "tcache_" + hashlib.md5(fingerprint.encode("utf-8")).hexdigest()


def get_cached_translation(
    db_path: Path, text: str, source_lang: str, target_lang: str, model: str
) -> Optional[str]:
    """Return cached translation or None."""
    key = _make_cache_key(text, source_lang, target_lang, model)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT content, expiry_ts FROM translation_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    content, expiry_ts = row
    if time.time() > float(expiry_ts):
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM translation_cache WHERE cache_key = ?", (key,))
            conn.commit()
        return None
    try:
        return gzip.decompress(content).decode("utf-8")
    except Exception:
        return None


def set_cached_translation(
    db_path: Path, text: str, source_lang: str, target_lang: str, model: str, content: str, ttl_days: int = 7
) -> None:
    """Store translation in cache."""
    key = _make_cache_key(text, source_lang, target_lang, model)
    compressed = gzip.compress(content.encode("utf-8"))
    expiry_ts = time.time() + ttl_days * 86400
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO translation_cache (cache_key, content, expiry_ts) VALUES (?, ?, ?)",
            (key, compressed, expiry_ts),
        )
        conn.commit()


def clear_translation_cache(db_path: Path) -> int:
    """Clear all cached translations. Returns count deleted."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM translation_cache")
        conn.commit()
        return cur.rowcount


def get_cache_stats(db_path: Path) -> dict:
    """Return cache statistics."""
    with get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM translation_cache").fetchone()[0]
        size_row = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM translation_cache"
        ).fetchone()[0]
    return dict(count=count, total_bytes=size_row)
