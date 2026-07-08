"""Per-domain cookie persistence for session reuse.

Cookies saved after a successful stealth browser fetch are reloaded
on subsequent requests to the same domain — both requests.Session
and Playwright contexts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
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
    _COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    path = _COOKIE_DIR / f"{domain}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cookies, fh, ensure_ascii=False, indent=2)


def load_cookies(url: str) -> list[dict[str, Any]]:
    """Return previously saved cookies (Playwright dict format)."""
    domain = _domain_key(url)
    path = _COOKIE_DIR / f"{domain}.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# --------------------------------------------------------------------------- #
# requests.Session-format cookies — used by source_adapters.fetch_public_html
# --------------------------------------------------------------------------- #

def apply_cookies_to_session(url: str, session: requests.Session) -> None:
    """Load saved cookies into a *requests.Session* for the matching domain."""
    domain = _domain_key(url)
    path = _COOKIE_DIR / f"{domain}.json"
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cookies = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return

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
