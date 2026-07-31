from __future__ import annotations

import logging

import pytest

from app.observability import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    InMemoryMetrics,
    StructuredEventLogger,
    sanitize_url,
)


def test_structured_logger_redacts_sensitive_fields_and_url_query(caplog: pytest.LogCaptureFixture) -> None:
    logger = StructuredEventLogger(logging.getLogger("tests.observability"))

    with caplog.at_level(logging.INFO, logger="tests.observability"):
        logger.emit(
            "fetch_failed",
            job_id="job-1",
            source_url="https://alice:password@example.test/chapter/1?token=secret-token",
            cookies={"session": "private-cookie"},
            error="Authorization: Bearer private-token; chapter text: private chapter body",
        )

    rendered = caplog.text
    assert '"job_id":"job-1"' in rendered
    assert "https://example.test/chapter/1" in rendered
    assert "password" not in rendered
    assert "secret-token" not in rendered
    assert "private-cookie" not in rendered
    assert "private chapter body" not in rendered


def test_metrics_reject_unbounded_correlation_labels() -> None:
    metrics = InMemoryMetrics()

    with pytest.raises(ValueError, match="not allowed"):
        metrics.increment("import_tasks_total", labels={"job_id": "job-1"})


def test_metrics_calculate_latency_percentiles_with_bounded_labels() -> None:
    metrics = InMemoryMetrics(max_samples_per_series=8)
    for value in (10, 20, 30, 40):
        metrics.observe_latency_ms(
            "fetch_latency_ms",
            value,
            labels={"adapter_id": "69shuba", "fetch_method": "direct_http"},
        )

    snapshot = metrics.snapshot()
    latency = snapshot["latencies"][0]
    assert latency["count"] == 4
    assert latency["p50"] == 25.0
    assert latency["p95"] == 40.0
    assert latency["labels"] == {"adapter_id": "69shuba", "fetch_method": "direct_http"}


def test_circuit_breaker_opens_half_opens_and_recovers() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=2, window_seconds=10, cooldown_seconds=5),
        clock=lambda: now[0],
    )

    assert breaker.allow("69shuba", "direct_http")
    breaker.record_failure("69shuba", "direct_http", "connect_timeout")
    assert breaker.state("69shuba", "direct_http") is CircuitState.CLOSED
    breaker.record_failure("69shuba", "direct_http", "read_timeout")
    assert breaker.state("69shuba", "direct_http") is CircuitState.OPEN
    assert not breaker.allow("69shuba", "direct_http")

    now[0] = 5.0
    assert breaker.allow("69shuba", "direct_http")
    assert breaker.state("69shuba", "direct_http") is CircuitState.HALF_OPEN
    assert not breaker.allow("69shuba", "direct_http")

    breaker.record_success("69shuba", "direct_http")
    assert breaker.state("69shuba", "direct_http") is CircuitState.CLOSED
    assert breaker.allow("69shuba", "direct_http")


def test_circuit_breaker_ignores_content_and_validation_failures() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))

    breaker.record_failure("69shuba", "direct_http", "content_invalid")

    assert breaker.state("69shuba", "direct_http") is CircuitState.CLOSED


def test_sanitize_url_redacts_malformed_port_without_raising() -> None:
    assert sanitize_url("https://example.test:not-a-port/chapter?token=private") == "[redacted]"
