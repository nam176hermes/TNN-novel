from __future__ import annotations

import threading
import time

from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.services.import_job_runtime import BoundedTaskRunner, RetryPolicy


def test_retry_policy_classifies_error_codes_and_uses_deterministic_backoff() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=30, jitter_ratio=0.25)

    retryable = SourceAdapterError("Timed out", code=FetchErrorCode.CONNECT_TIMEOUT, retryable=True)
    blocked = SourceAdapterError("Blocked", code=FetchErrorCode.USER_VERIFICATION_REQUIRED)

    assert policy.should_retry(retryable, attempt=1, elapsed_seconds=0)
    assert not policy.should_retry(blocked, attempt=1, elapsed_seconds=0)
    assert policy.delay_seconds(attempt=2, random_value=lambda: 0.5) == 4


def test_retry_policy_honors_attempt_and_total_time_budget() -> None:
    policy = RetryPolicy(max_attempts=2, total_time_budget_seconds=5)
    error = SourceAdapterError("Unavailable", code=FetchErrorCode.SOURCE_UNAVAILABLE, retryable=True)

    assert policy.should_retry(error, attempt=1, elapsed_seconds=4.9)
    assert not policy.should_retry(error, attempt=2, elapsed_seconds=0)
    assert not policy.should_retry(error, attempt=1, elapsed_seconds=5)


def test_retry_after_overrides_exponential_backoff() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=30)
    error = SourceAdapterError(
        "Retry later",
        code=FetchErrorCode.RATE_LIMITED,
        retryable=True,
        retry_after_seconds=10,
    )
    assert policy.delay_seconds(
        attempt=3,
        random_value=lambda: 0.0,
        retry_after_seconds=error.retry_after_seconds,
    ) == 10


def test_bounded_runner_enforces_global_and_per_host_limits() -> None:
    runner = BoundedTaskRunner(direct_global_limit=2, direct_per_host_limit=1, browser_global_limit=1)
    active = 0
    peak = 0
    lock = threading.Lock()

    def work() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1

    runner.run([
        ("direct_http", "one.example", work, lambda: None),
        ("direct_http", "one.example", work, lambda: None),
        ("direct_http", "two.example", work, lambda: None),
    ])

    assert peak == 2


def test_per_host_does_not_hold_during_import() -> None:
    runner = BoundedTaskRunner(direct_global_limit=2, direct_per_host_limit=1)
    second_fetch_started = threading.Event()
    first_import_observed_release: list[bool] = []

    runner.run([
        (
            "direct_http",
            "one.example",
            lambda: None,
            lambda: first_import_observed_release.append(second_fetch_started.wait(0.5)),
        ),
        (
            "direct_http",
            "one.example",
            second_fetch_started.set,
            lambda: None,
        ),
    ])

    assert first_import_observed_release == [True]
