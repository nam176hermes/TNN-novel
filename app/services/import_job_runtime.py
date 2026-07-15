"""Retry and bounded-runtime primitives for durable import tasks.

The primitives are deliberately dependency-free: callers inject time, sleep,
and randomness so retry behaviour is deterministic in tests and no source
payload ever needs to be persisted or logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from threading import BoundedSemaphore
from typing import Callable, Iterable

from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError


_NON_RETRYABLE = {
    FetchErrorCode.INVALID_URL,
    FetchErrorCode.SOURCE_NOT_ALLOWED,
    FetchErrorCode.PRIVATE_NETWORK_BLOCKED,
    FetchErrorCode.USER_VERIFICATION_REQUIRED,
    FetchErrorCode.PARSE_FAILED,
    FetchErrorCode.DUPLICATE,
    FetchErrorCode.CANCELLED,
}
_DEFAULT_RETRYABLE = {
    FetchErrorCode.CONNECT_TIMEOUT,
    FetchErrorCode.READ_TIMEOUT,
    FetchErrorCode.RATE_LIMITED,
}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_ratio: float = 0.2
    total_time_budget_seconds: float = 120.0

    def should_retry(self, error: SourceAdapterError, *, attempt: int, elapsed_seconds: float) -> bool:
        if error.code in _NON_RETRYABLE:
            return False
        if attempt >= self.max_attempts or elapsed_seconds >= self.total_time_budget_seconds:
            return False
        return bool(
            error.retryable
            or error.code in _DEFAULT_RETRYABLE
            or error.code is FetchErrorCode.SOURCE_UNAVAILABLE
        )

    def delay_seconds(
        self,
        *,
        attempt: int,
        random_value: Callable[[], float],
        retry_after_seconds: float | None = None,
    ) -> float:
        if retry_after_seconds is not None:
            return max(0.0, min(float(retry_after_seconds), self.max_delay_seconds))
        base = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))
        jitter = (max(0.0, min(1.0, random_value())) - 0.5) * 2 * base * self.jitter_ratio
        return max(0.0, min(self.max_delay_seconds, base + jitter))


class BoundedTaskRunner:
    """Runs independent fetch/parse units with bounded global and host slots."""

    def __init__(
        self,
        *,
        direct_global_limit: int = 4,
        direct_per_host_limit: int = 1,
        browser_global_limit: int = 1,
        max_queue_size: int = 64,
    ) -> None:
        self.direct_global_limit = max(1, direct_global_limit)
        self.direct_per_host_limit = max(1, direct_per_host_limit)
        self.browser_global_limit = max(1, browser_global_limit)
        self.max_queue_size = max(1, max_queue_size)

    def run(
        self,
        work_items: Iterable[
            tuple[str, str, Callable[[], None], Callable[[], None]]
        ],
    ) -> None:
        items = list(work_items)
        if len(items) > self.max_queue_size:
            raise ValueError("bounded task queue is full")
        direct = BoundedSemaphore(self.direct_global_limit)
        browser = BoundedSemaphore(self.browser_global_limit)
        per_host: dict[str, BoundedSemaphore] = defaultdict(
            lambda: BoundedSemaphore(self.direct_per_host_limit)
        )

        def invoke(
            method: str,
            host: str,
            fetch_callback: Callable[[], None],
            import_callback: Callable[[], None],
        ) -> None:
            global_slot = browser if method in {"browser_session", "stealth_browser_headed"} else direct
            host_slot = None if global_slot is browser else per_host[host]
            with global_slot:
                if host_slot is None:
                    fetch_callback()
                else:
                    with host_slot:
                        fetch_callback()
            import_callback()

        workers = min(len(items), self.direct_global_limit + self.browser_global_limit)
        if not workers:
            return
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="import-task") as pool:
            futures = [
                pool.submit(invoke, method, host, fetch_callback, import_callback)
                for method, host, fetch_callback, import_callback in items
            ]
            for future in futures:
                future.result()
