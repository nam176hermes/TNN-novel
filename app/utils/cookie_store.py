"""Per-domain cookie persistence for session reuse.

Cookies saved after a successful stealth browser fetch are reloaded
on subsequent requests to the same domain — both requests.Session
and Playwright contexts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib.parse import urlparse

import requests

_COOKIE_DIR = Path(
    os.getenv("COOKIE_STORE_DIR", str(Path.home() / ".novel_pipeline" / "cookies"))
)


def _domain_key(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or parsed.netloc or "unknown"


# --------------------------------------------------------------------------- #
# Playwright-format cookies (list[dict]) — used by stealth_browser.py
# --------------------------------------------------------------------------- #

def save_cookies(url: str, cookies: list[dict[str, Any]]) -> None:
    """Persist cookies for *url*'s domain as JSON."""
    domain = _domain_key(url)
    _COOKIE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _COOKIE_DIR.chmod(0o700)
    except OSError:
        pass
    path = _COOKIE_DIR / f"{domain}.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{domain}.",
        suffix=".tmp",
        dir=_COOKIE_DIR,
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
            json.dump(cookies, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def load_cookies(url: str, *, now: float | None = None) -> list[dict[str, Any]]:
    """Return previously saved cookies (Playwright dict format)."""
    domain = _domain_key(url)
    path = _COOKIE_DIR / f"{domain}.json"
    if not path.exists():
        return []
    try:
        path.chmod(0o600)
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            _rotate_corrupt(path)
            return []
    except (json.JSONDecodeError, OSError):
        _rotate_corrupt(path)
        return []
    current_time = time.time() if now is None else now
    return [cookie for cookie in data if not _is_expired(cookie, current_time)]


def _is_expired(cookie: dict[str, Any], now: float) -> bool:
    expires = cookie.get("expires")
    if expires in (None, "", 0, -1):
        return False
    try:
        return float(expires) <= now
    except (TypeError, ValueError):
        return True


def _rotate_corrupt(path: Path) -> None:
    if not path.exists():
        return
    rotated = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
    try:
        os.replace(path, rotated)
        os.chmod(rotated, 0o600)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# requests.Session-format cookies — used by source_adapters.fetch_public_html
# --------------------------------------------------------------------------- #

def apply_cookies_to_session(url: str, session: requests.Session) -> None:
    """Load saved cookies into a *requests.Session* for the matching domain."""
    domain = _domain_key(url)
    cookies = load_cookies(url)

    for c in cookies:
        if not isinstance(c, dict):
            continue
        session.cookies.set(
            c.get("name", ""),
            c.get("value", ""),
            domain=c.get("domain", f".{domain}"),
            path=c.get("path", "/"),
        )


def clear_cookies(url: str) -> None:
    """Delete saved cookies for the domain."""
    domain = _domain_key(url)
    path = _COOKIE_DIR / f"{domain}.json"
    if path.exists():
        path.unlink()
