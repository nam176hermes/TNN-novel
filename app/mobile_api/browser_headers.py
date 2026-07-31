from __future__ import annotations

from collections.abc import MutableMapping
from urllib.parse import urlsplit

from app.mobile_api.config import MobileAPISettings, mobile_settings


def _connect_sources(settings: MobileAPISettings) -> str:
    sources = {"'self'"}
    for configured in settings.cors_origins:
        parsed = urlsplit(configured)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            sources.add(f"{parsed.scheme}://{parsed.netloc}")
    return " ".join(sorted(sources))


def content_security_policy(settings: MobileAPISettings = mobile_settings) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            "base-uri 'self'",
            f"connect-src {_connect_sources(settings)}",
            "font-src 'self' data:",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "img-src 'self' data: blob:",
            "manifest-src 'self'",
            "media-src 'self' blob:",
            "object-src 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "worker-src 'self' blob:",
        )
    )


def apply_browser_security_headers(
    headers: MutableMapping[str, str],
    *,
    public_https: bool,
    settings: MobileAPISettings = mobile_settings,
) -> None:
    headers["Content-Security-Policy"] = content_security_policy(settings)
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    if public_https:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
