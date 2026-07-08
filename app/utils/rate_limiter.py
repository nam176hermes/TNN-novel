"""Simple rate limiting / flood control (adapted from LibreTranslate flood.py).

Tracks requests per IP with in-memory storage.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict


@dataclass
class RateLimiter:
    """Simple in-memory rate limiter."""

    window_minutes: int = 5
    max_requests: int = 60
    _requests: Dict[str, list] = field(default_factory=lambda: defaultdict(list))

    def is_allowed(self, client_ip: str) -> bool:
        """Return True if request is allowed, False if rate limited."""
        now = datetime.now()
        window_start = now - timedelta(minutes=self.window_minutes)

        # Clean old entries
        self._requests[client_ip] = [t for t in self._requests[client_ip] if t > window_start]

        if len(self._requests[client_ip]) >= self.max_requests:
            return False

        self._requests[client_ip].append(now)
        return True

    def remaining(self, client_ip: str) -> int:
        """Return remaining requests in current window."""
        now = datetime.now()
        window_start = now - timedelta(minutes=self.window_minutes)
        count = len([t for t in self._requests[client_ip] if t > window_start])
        return max(0, self.max_requests - count)


# Global instance
limiter = RateLimiter()