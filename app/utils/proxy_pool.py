"""Proxy pool for rotating IPs to avoid rate limits and bypass geo-restrictions."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProxyConfig:
    """Configuration for a single proxy."""
    url: str  # http://user:pass@host:port
    username: Optional[str] = None
    password: Optional[str] = None
    provider: str = "manual"  # manual, brightdata, oxylabs, webshare

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "provider": self.provider,
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

    @property
    def count(self) -> int:
        return len(self.proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for v in self.healthy.values() if v)


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

        # Parse URL for credentials
        url = item
        username = None
        password = None

        if "@" in url:
            auth, host = url.rsplit("@", 1)
            if ":" in auth:
                username, password = auth.split(":", 1)
            url = f"http://{host}"

        pool.add_proxy(ProxyConfig(
            url=url,
            username=username,
            password=password,
        ))

    return pool


# Global instance
proxy_pool = build_proxy_pool_from_env()
