"""Proxy pool for rotating IPs to avoid rate limits and bypass geo-restrictions.

Supports HTTP and SOCKS5 proxies. When ``PROXY_LIST`` is empty, the pool
is disabled and all proxy-related code paths are skipped.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration for a single proxy."""
    url: str  # http://user:pass@host:port or socks5://host:port
    username: Optional[str] = None
    password: Optional[str] = None
    provider: str = "manual"  # manual, brightdata, oxylabs, webshare
    proxy_type: str = "http"  # http or socks5

    @property
    def is_socks5(self) -> bool:
        return self.proxy_type == "socks5"

    def to_requests_proxies(self) -> dict[str, str]:
        """Return dict suitable for ``requests.Session.proxies``."""
        return {
            "http": self.url,
            "https": self.url,
        }

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "provider": self.provider,
            "type": self.proxy_type,
        }


@dataclass
class ProxyPool:
    """Round-robin proxy pool with health tracking."""
    proxies: list[ProxyConfig] = field(default_factory=list)
    current_index: int = 0
    healthy: dict[str, bool] = field(default_factory=dict)  # url -> is_healthy

    def add_proxy(self, proxy: ProxyConfig) -> None:
        self.proxies.append(proxy)
        self.healthy[proxy.url] = True

    def get_next(self) -> Optional[ProxyConfig]:
        """Get next proxy in round-robin fashion, skipping unhealthy ones."""
        if not self.proxies:
            return None

        # Try to find a healthy proxy
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            if self.healthy.get(proxy.url, True):
                return proxy

        # All unhealthy, return first anyway
        return self.proxies[0]

    def mark_healthy(self, proxy_url: str, is_healthy: bool) -> None:
        self.healthy[proxy_url] = is_healthy

    def reset_health(self) -> None:
        """Mark all proxies as healthy (use after cooldown period)."""
        for url in self.healthy:
            self.healthy[url] = True

    @property
    def count(self) -> int:
        return len(self.proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for v in self.healthy.values() if v)

    def should_retry_with_proxy(self, error: BaseException) -> bool:
        """Check if an error is worth retrying with a different proxy."""
        msg = str(error).casefold()
        retryable = (
            "timeout",
            "timed out",
            "connection error",
            "connection reset",
            "connection refused",
            "connection aborted",
            "proxyerror",
            "502",
            "503",
            "429",
            "rate limit",
            "max retries",
            "read timed out",
            "ssl: wrong version",
        )
        return any(marker in msg for marker in retryable)


def _parse_proxy_entry(item: str) -> ProxyConfig:
    """Parse a single proxy entry from PROXY_LIST."""
    item = item.strip()
    proxy_type = "http"
    url = item

    # Detect socks5
    if url.lower().startswith("socks5://"):
        proxy_type = "socks5"
    elif url.lower().startswith("socks5h://"):
        proxy_type = "socks5"

    # Extract credentials if present (user:pass@host:port)
    username = None
    password = None
    if "@" in url:
        # Split at last @ in case password contains @
        scheme_and_auth, host = url.rsplit("@", 1)
        if ":" in scheme_and_auth:
            # Handle scheme://user:pass
            if "://" in scheme_and_auth:
                scheme, auth = scheme_and_auth.split("://", 1)
            else:
                auth = scheme_and_auth
            if ":" in auth:
                username, password = auth.split(":", 1)
        # Reconstruct URL
        scheme = "socks5" if proxy_type == "socks5" else "http"
        url = f"{scheme}://{host}"

    return ProxyConfig(
        url=url,
        username=username,
        password=password,
        proxy_type=proxy_type,
    )


def build_proxy_pool_from_env() -> ProxyPool:
    """Build proxy pool from PROXY_LIST env var (comma-separated URLs)."""
    pool = ProxyPool()

    proxy_list = os.getenv("PROXY_LIST", "")
    if not proxy_list:
        return pool

    for item in proxy_list.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            proxy = _parse_proxy_entry(item)
            pool.add_proxy(proxy)
        except Exception:
            logger.warning("Failed to parse proxy entry (skipped)")

    if pool.count > 0:
        logger.info("Proxy pool initialized with %d proxies", pool.count)

    return pool


# Global instance
proxy_pool = build_proxy_pool_from_env()
