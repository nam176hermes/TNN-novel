"""Safe, dependency-free observability primitives for import operations.

The module intentionally keeps metrics in process and exposes a small,
injectable API.  It never accepts raw source payloads as metric labels and
redacts values before they are emitted to Python logging.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
import math
import re
from threading import RLock
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit


_LOGGER = logging.getLogger(__name__)
_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "cookie",
    "secret",
    "token",
    "password",
    "passphrase",
    "api_key",
    "apikey",
    "private_key",
    "html",
    "chapter_text",
    "raw_text",
    "content",
)
_SENSITIVE_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "set-cookie:",
    "cookie:",
    "api_key",
    "apikey",
    "secret",
    "token=",
    "password=",
    "passphrase",
    "<html",
    "<!doctype",
    "chapter text:",
)
_ALLOWED_METRIC_LABELS = {
    "adapter_id",
    "adapter_version",
    "fetch_method",
    "error_code",
    "extractor",
    "operation",
    "status",
    "stage",
    "state",
}
_LABEL_VALUE = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
_RELEVANT_CIRCUIT_ERRORS = {
    "connect_timeout",
    "read_timeout",
    "rate_limited",
    "source_unavailable",
    "browser_crash",
}
_GLOSSARY_ACTIONS = {
    "add",
    "approve",
    "archive",
    "conflict",
    "import_add",
    "import_update",
    "lock",
    "merge",
    "merge_archive",
    "needs_review",
    "reject",
    "restore",
    "unlock",
    "update",
}
_GLOSSARY_STATES = {
    "APPROVED",
    "ARCHIVED",
    "CONFLICT",
    "LOCKED",
    "MISSING",
    "NEEDS_REVIEW",
    "REJECTED",
}
_GLOSSARY_EXTRACTORS = {"deterministic-v2", "hybrid-v1"}
_GLOSSARY_EXTRACTION_ERRORS = {
    "",
    "artifact_unavailable",
    "provider_malformed_response",
    "provider_not_configured",
    "provider_unavailable",
}
_GLOSSARY_PROVIDER_FAILURES = {
    "provider_malformed_response",
    "provider_not_configured",
    "provider_unavailable",
}


def sanitize_url(value: object) -> str:
    """Return an origin and path with credentials, query, and fragment removed."""

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "[redacted]"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "[redacted]"
    hostname = parsed.hostname.lower()
    try:
        port_number = parsed.port
    except ValueError:
        return "[redacted]"
    port = f":{port_number}" if port_number else ""
    return urlunsplit((parsed.scheme.lower(), f"{hostname}{port}", parsed.path or "/", "", ""))


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key or "").strip().lower()
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _is_sensitive_string(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS)


def sanitize_observability_data(value: Any, *, key: str = "") -> Any:
    """Redact recursively while retaining bounded operational metadata."""

    if _is_sensitive_key(key):
        return "[redacted]"
    if key.lower().endswith("url") or key.lower() in {"url", "requested_url", "final_url", "source_url"}:
        return sanitize_url(value)
    if isinstance(value, Mapping):
        return {
            str(child_key)[:64]: sanitize_observability_data(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_observability_data(item, key=key) for item in list(value)[:32]]
    if isinstance(value, str):
        compact = value.replace("\n", " ").replace("\r", " ").strip()
        return "[redacted]" if _is_sensitive_string(compact) else compact[:512]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_observability_data(str(value), key=key)


class StructuredEventLogger:
    """Emit redacted JSON records through the standard logging package."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or _LOGGER

    def emit(self, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
        payload = {"event": str(event)[:96], **sanitize_observability_data(fields)}
        self.logger.log(level, "novel_observability=%s", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


MetricLabels = tuple[tuple[str, str], ...]


class InMemoryMetrics:
    """Bounded-cardinality counters, gauges, and latency samples."""

    def __init__(self, *, max_series: int = 256, max_samples_per_series: int = 512) -> None:
        self.max_series = max(1, max_series)
        self.max_samples_per_series = max(1, max_samples_per_series)
        self._lock = RLock()
        self._counters: dict[tuple[str, MetricLabels], float] = defaultdict(float)
        self._gauges: dict[tuple[str, MetricLabels], float] = {}
        self._latencies: dict[tuple[str, MetricLabels], deque[float]] = {}

    def _labels(self, labels: Mapping[str, object] | None) -> MetricLabels:
        normalized: list[tuple[str, str]] = []
        for key, value in (labels or {}).items():
            name = str(key)
            if name not in _ALLOWED_METRIC_LABELS:
                raise ValueError(f"metric label {name!r} is not allowed")
            rendered = str(value or "unknown")[:64]
            normalized.append((name, rendered if _LABEL_VALUE.fullmatch(rendered) else "unknown"))
        return tuple(sorted(normalized))

    def _allow_series(self, key: tuple[str, MetricLabels]) -> bool:
        seen = set(self._counters) | set(self._gauges) | set(self._latencies)
        return key in seen or len(seen) < self.max_series

    def increment(self, name: str, value: float = 1.0, *, labels: Mapping[str, object] | None = None) -> None:
        key = (str(name), self._labels(labels))
        with self._lock:
            if self._allow_series(key):
                self._counters[key] += float(value)

    def set_gauge(self, name: str, value: float, *, labels: Mapping[str, object] | None = None) -> None:
        key = (str(name), self._labels(labels))
        with self._lock:
            if self._allow_series(key):
                self._gauges[key] = float(value)

    def observe_latency_ms(self, name: str, value: float, *, labels: Mapping[str, object] | None = None) -> None:
        key = (str(name), self._labels(labels))
        with self._lock:
            if not self._allow_series(key):
                return
            samples = self._latencies.setdefault(key, deque(maxlen=self.max_samples_per_series))
            samples.append(max(0.0, float(value)))

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        if percentile == 0.5 and len(ordered) % 2 == 0:
            upper = len(ordered) // 2
            return (ordered[upper - 1] + ordered[upper]) / 2
        index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
        return ordered[index]

    @staticmethod
    def _entry(name: str, labels: MetricLabels, value: float) -> dict[str, Any]:
        return {"name": name, "labels": dict(labels), "value": value}

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            counters = [self._entry(name, labels, value) for (name, labels), value in self._counters.items()]
            gauges = [self._entry(name, labels, value) for (name, labels), value in self._gauges.items()]
            latencies = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "count": len(samples),
                    "p50": self._percentile(list(samples), 0.5),
                    "p95": self._percentile(list(samples), 0.95),
                }
                for (name, labels), samples in self._latencies.items()
            ]
        return {
            "counters": sorted(counters, key=lambda item: (item["name"], tuple(item["labels"].items()))),
            "gauges": sorted(gauges, key=lambda item: (item["name"], tuple(item["labels"].items()))),
            "latencies": sorted(latencies, key=lambda item: (item["name"], tuple(item["labels"].items()))),
        }


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    window_seconds: float = 60.0
    cooldown_seconds: float = 30.0


@dataclass
class _CircuitRecord:
    state: CircuitState = CircuitState.CLOSED
    failure_times: deque[float] = field(default_factory=deque)
    opened_at: float = 0.0
    probe_in_flight: bool = False


class CircuitBreaker:
    """Per-adapter/fetch-method breaker with a single half-open probe."""

    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        metrics: InMemoryMetrics | None = None,
        events: StructuredEventLogger | None = None,
    ) -> None:
        self.config = config or CircuitBreakerConfig()
        self.clock = clock
        self.metrics = metrics or InMemoryMetrics()
        self.events = events or StructuredEventLogger()
        self._lock = RLock()
        self._records: dict[tuple[str, str], _CircuitRecord] = {}

    @staticmethod
    def _key(adapter_id: str, fetch_method: str) -> tuple[str, str]:
        return (str(adapter_id or "unknown")[:64], str(fetch_method or "unknown")[:64])

    def _record(self, adapter_id: str, fetch_method: str) -> _CircuitRecord:
        return self._records.setdefault(self._key(adapter_id, fetch_method), _CircuitRecord())

    def _transition(self, adapter_id: str, fetch_method: str, record: _CircuitRecord, state: CircuitState) -> None:
        if record.state is state:
            return
        previous = record.state
        record.state = state
        record.probe_in_flight = False
        labels = {"adapter_id": adapter_id, "fetch_method": fetch_method, "state": state.value}
        self.metrics.increment("circuit_breaker_transitions_total", labels=labels)
        self.events.emit(
            "circuit_breaker_transition",
            adapter_id=adapter_id,
            fetch_method=fetch_method,
            previous_state=previous.value,
            state=state.value,
        )

    def allow(self, adapter_id: str, fetch_method: str) -> bool:
        with self._lock:
            record = self._record(adapter_id, fetch_method)
            now = self.clock()
            if record.state is CircuitState.OPEN:
                if now - record.opened_at < self.config.cooldown_seconds:
                    self.metrics.increment(
                        "circuit_breaker_rejections_total",
                        labels={"adapter_id": adapter_id, "fetch_method": fetch_method, "state": record.state.value},
                    )
                    return False
                self._transition(adapter_id, fetch_method, record, CircuitState.HALF_OPEN)
                record.probe_in_flight = True
                return True
            if record.state is CircuitState.HALF_OPEN:
                if record.probe_in_flight:
                    self.metrics.increment(
                        "circuit_breaker_rejections_total",
                        labels={"adapter_id": adapter_id, "fetch_method": fetch_method, "state": record.state.value},
                    )
                    return False
                record.probe_in_flight = True
            return True

    def record_success(self, adapter_id: str, fetch_method: str) -> None:
        with self._lock:
            record = self._record(adapter_id, fetch_method)
            if record.state is not CircuitState.CLOSED:
                self._transition(adapter_id, fetch_method, record, CircuitState.CLOSED)
            record.failure_times.clear()
            record.probe_in_flight = False

    def record_failure(self, adapter_id: str, fetch_method: str, error_code: object) -> None:
        code = getattr(error_code, "value", str(error_code)).strip().lower()
        if code not in _RELEVANT_CIRCUIT_ERRORS:
            return
        with self._lock:
            record = self._record(adapter_id, fetch_method)
            now = self.clock()
            if record.state is CircuitState.HALF_OPEN:
                record.opened_at = now
                self._transition(adapter_id, fetch_method, record, CircuitState.OPEN)
                return
            record.failure_times.append(now)
            while record.failure_times and now - record.failure_times[0] > self.config.window_seconds:
                record.failure_times.popleft()
            if len(record.failure_times) >= max(1, self.config.failure_threshold):
                record.opened_at = now
                self._transition(adapter_id, fetch_method, record, CircuitState.OPEN)

    def state(self, adapter_id: str, fetch_method: str) -> CircuitState:
        with self._lock:
            return self._record(adapter_id, fetch_method).state

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "adapter_id": adapter_id,
                    "fetch_method": fetch_method,
                    "state": record.state.value,
                    "failure_count": len(record.failure_times),
                }
                for (adapter_id, fetch_method), record in sorted(self._records.items())
            ]


class Observability:
    """Facade used by workers, adapters, and browser lifecycle code."""

    def __init__(
        self,
        *,
        metrics: InMemoryMetrics | None = None,
        events: StructuredEventLogger | None = None,
        circuit_config: CircuitBreakerConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.metrics = metrics or InMemoryMetrics()
        self.events = events or StructuredEventLogger()
        self.circuit_breaker = CircuitBreaker(circuit_config, clock=clock, metrics=self.metrics, events=self.events)

    def configure_circuit_breaker(self, config: CircuitBreakerConfig) -> None:
        """Apply process configuration without replacing the shared telemetry stores.

        The default instance is shared by adapters, browser sessions, and job
        workers, so changing its breaker preserves a single per-process source
        view while keeping metrics and redacted event logging intact.
        """

        if self.circuit_breaker.config == config:
            return
        self.circuit_breaker = CircuitBreaker(config, metrics=self.metrics, events=self.events)

    def record_fetch(
        self,
        *,
        adapter_id: str,
        adapter_version: str = "",
        fetch_method: str = "",
        error_code: str = "",
        elapsed_ms: int | float = 0,
        response_bytes: int = 0,
        parsed_text_length: int = 0,
        operation: str = "fetch",
        job_id: str = "",
        task_id: int | str = "",
    ) -> None:
        labels = {
            "adapter_id": adapter_id or "unknown",
            "adapter_version": adapter_version or "unknown",
            "fetch_method": fetch_method or "unknown",
            "operation": operation,
        }
        self.metrics.increment("fetch_requests_total", labels={**labels, "status": "failure" if error_code else "success"})
        self.metrics.observe_latency_ms("fetch_latency_ms", elapsed_ms, labels=labels)
        self.metrics.observe_latency_ms("response_bytes", response_bytes, labels=labels)
        self.metrics.observe_latency_ms("parsed_text_length", parsed_text_length, labels=labels)
        if error_code:
            self.metrics.increment("fetch_failures_total", labels={**labels, "error_code": error_code})
        self.events.emit(
            "fetch_result",
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            fetch_method=fetch_method,
            error_code=error_code,
            elapsed_ms=int(elapsed_ms),
            response_bytes=int(response_bytes),
            parsed_text_length=int(parsed_text_length),
            operation=operation,
            job_id=job_id,
            task_id=task_id,
        )

    def record_parse(
        self,
        *,
        adapter_id: str,
        adapter_version: str,
        operation: str,
        parsed_text_length: int = 0,
        error_code: str = "",
    ) -> None:
        labels = {
            "adapter_id": adapter_id or "unknown",
            "adapter_version": adapter_version or "unknown",
            "operation": operation,
            "status": "failure" if error_code else "success",
        }
        self.metrics.increment("parse_attempts_total", labels=labels)
        self.metrics.observe_latency_ms("parsed_text_length", parsed_text_length, labels=labels)
        if error_code:
            self.metrics.increment("parse_failures_total", labels={**labels, "error_code": error_code})
        self.events.emit(
            "parse_result",
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            operation=operation,
            parsed_text_length=int(parsed_text_length),
            error_code=error_code,
        )

    def record_job(self, *, status: str, operation: str, job_id: str = "") -> None:
        self.metrics.increment(
            "import_jobs_total",
            labels={"status": status, "operation": operation},
        )
        self.events.emit("import_job", job_id=job_id, status=status, operation=operation)

    def record_task(
        self,
        *,
        status: str,
        stage: str,
        operation: str,
        job_id: str = "",
        task_id: int | str = "",
        adapter_id: str = "",
        adapter_version: str = "",
        fetch_method: str = "",
        error_code: str = "",
        attempts: int = 0,
        elapsed_ms: int | float = 0,
        response_bytes: int = 0,
        parsed_text_length: int = 0,
        worker_id: str = "",
    ) -> None:
        labels = {
            "status": status,
            "stage": stage,
            "operation": operation,
            "adapter_id": adapter_id or "unknown",
            "adapter_version": adapter_version or "unknown",
            "fetch_method": fetch_method or "unknown",
        }
        self.metrics.increment("import_tasks_total", labels=labels)
        if status == "cancelled":
            self.metrics.increment("import_task_cancellations_total", labels=labels)
        if error_code:
            self.metrics.increment("import_task_failures_total", labels={**labels, "error_code": error_code})
        if attempts > 1:
            self.metrics.increment("import_task_retries_total", attempts - 1, labels=labels)
        self.events.emit(
            "import_task",
            job_id=job_id,
            task_id=task_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            fetch_method=fetch_method,
            error_code=error_code,
            attempts=attempts,
            elapsed_ms=int(elapsed_ms),
            response_bytes=int(response_bytes),
            parsed_text_length=int(parsed_text_length),
            operation=operation,
            worker_id=worker_id,
            status=status,
            stage=stage,
        )

    def record_browser_lifecycle(self, operation: str) -> None:
        metric = "browser_restarts_total" if operation == "restart" else "browser_launches_total"
        self.metrics.increment(metric, labels={"operation": operation})
        self.events.emit("browser_lifecycle", operation=operation)

    def set_workload(self, *, active_jobs: int, queue_depth: int) -> None:
        self.metrics.set_gauge("active_jobs", active_jobs)
        self.metrics.set_gauge("queue_depth", queue_depth)

    def record_glossary_query(
        self,
        *,
        elapsed_ms: int | float,
        result_count: int,
        conflict_count: int,
    ) -> None:
        labels = {"operation": "queue"}
        self.metrics.increment("glossary_queries_total", labels=labels)
        self.metrics.observe_latency_ms("glossary_query_latency_ms", elapsed_ms, labels=labels)
        self.metrics.set_gauge("glossary_conflicts", max(0, int(conflict_count)))
        self.events.emit(
            "glossary_query",
            operation="queue",
            elapsed_ms=max(0, int(elapsed_ms)),
            result_count=max(0, int(result_count)),
            conflict_count=max(0, int(conflict_count)),
        )

    def record_glossary_transition(
        self,
        *,
        action: str,
        before_state: str,
        after_state: str,
        term_id: int,
        book_id: int,
        version: int,
    ) -> None:
        safe_action = action if action in _GLOSSARY_ACTIONS else "unknown"
        safe_before = before_state if before_state in _GLOSSARY_STATES else "MISSING"
        safe_after = after_state if after_state in _GLOSSARY_STATES else "CONFLICT"
        labels = {"operation": safe_action, "state": safe_after}
        self.metrics.increment("glossary_state_transitions_total", labels=labels)
        self.events.emit(
            "glossary_state_transition",
            operation=safe_action,
            before_state=safe_before,
            state=safe_after,
            term_id=max(0, int(term_id)),
            book_id=max(0, int(book_id)),
            version=max(0, int(version)),
            conflict_count=int(safe_after == "CONFLICT"),
        )

    def record_glossary_extraction(
        self,
        *,
        extractor: str,
        status: str,
        created: int,
        updated: int,
        skipped: int,
        candidate_count: int,
        warning_count: int,
        error_code: str,
        book_id: int,
        chapter_id: int,
    ) -> None:
        safe_extractor = extractor if extractor in _GLOSSARY_EXTRACTORS else "deterministic-v2"
        safe_status = status if status in {"success", "warning", "skipped"} else "warning"
        safe_error = error_code if error_code in _GLOSSARY_EXTRACTION_ERRORS else ""
        labels = {"extractor": safe_extractor, "status": safe_status}
        self.metrics.increment("glossary_extractions_total", labels=labels)
        if safe_error in _GLOSSARY_PROVIDER_FAILURES:
            self.metrics.increment(
                "glossary_provider_failures_total",
                labels={"extractor": safe_extractor, "error_code": safe_error},
            )
        self.events.emit(
            "glossary_extraction",
            extractor=safe_extractor,
            status=safe_status,
            error_code=safe_error,
            created=max(0, int(created)),
            updated=max(0, int(updated)),
            skipped=max(0, int(skipped)),
            candidate_count=max(0, int(candidate_count)),
            warning_count=max(0, int(warning_count)),
            book_id=max(0, int(book_id)),
            chapter_id=max(0, int(chapter_id)),
        )

    def record_glossary_resolution(
        self,
        *,
        book_id: int,
        effective_term_count: int,
        fingerprint_id: str,
    ) -> None:
        fingerprint = str(fingerprint_id or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            fingerprint = "invalid"
        self.metrics.increment("glossary_resolutions_total", labels={"operation": "resolve"})
        self.metrics.set_gauge("glossary_effective_terms", max(0, int(effective_term_count)))
        self.events.emit(
            "glossary_resolution",
            book_id=max(0, int(book_id)),
            effective_term_count=max(0, int(effective_term_count)),
            fingerprint_id=fingerprint,
        )

    def record_glossary_qa(
        self,
        *,
        book_id: int,
        chapter_id: int,
        violation_count: int,
        status: str,
    ) -> None:
        safe_status = status if status in {"pass", "warning", "fail"} else "warning"
        count = max(0, int(violation_count))
        self.metrics.increment("glossary_qa_runs_total", labels={"status": safe_status})
        self.metrics.increment("glossary_qa_violations_total", count, labels={"status": safe_status})
        self.events.emit(
            "glossary_qa",
            book_id=max(0, int(book_id)),
            chapter_id=max(0, int(chapter_id)),
            violation_count=count,
            status=safe_status,
        )

    def snapshot(self) -> dict[str, Any]:
        return {"metrics": self.metrics.snapshot(), "circuits": self.circuit_breaker.snapshot()}


default_observability = Observability()
