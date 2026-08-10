from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import stat
from typing import Any

import pytest
import requests

from app.services import operational_alert_delivery as delivery


OBSERVED_AT = "2026-08-09T12:00:00+00:00"
DELIVERED_AT = datetime(2026, 8, 9, 12, 0, 5, tzinfo=timezone.utc)
PRIVATE_SENTINELS = (
    "LEAK-SENTINEL-JOB",
    "LEAK-SENTINEL-USER",
    "private-book.epub",
    "private chapter content",
    "/private/operator/data",
)
EXPECTED_RECEIPT_NAMES = {
    "alert-backup_failure.receipt.json",
    "alert-wrong_release_receipt.receipt.json",
    "alert-worker_stale.receipt.json",
    "alert-stuck_jobs.receipt.json",
}


class FakeResponse:
    def __init__(self, status_code: int, response_body: str = "") -> None:
        self.status_code = status_code
        self._response_body = response_body

    @property
    def text(self) -> str:
        raise AssertionError(f"response body must not be inspected: {self._response_body}")


class FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.posts: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
        allow_redirects: bool | None = None,
    ) -> FakeResponse:
        self.posts.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if not self.outcomes:
            raise AssertionError("unexpected webhook delivery")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


def _snapshot(*alerts: dict[str, object], release_id: str = "release-a") -> dict[str, object]:
    return {
        "generated_at": OBSERVED_AT,
        "release": {"release_id": release_id},
        "alerts": list(alerts),
        "job_id": PRIVATE_SENTINELS[0],
        "user_id": PRIVATE_SENTINELS[1],
        "filename": PRIVATE_SENTINELS[2],
        "content": PRIVATE_SENTINELS[3],
        "absolute_path": PRIVATE_SENTINELS[4],
    }


def _alert(code: str, severity: str = "warning") -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "message": "private chapter content at /private/operator/data",
        "job_id": "LEAK-SENTINEL-JOB",
    }


def _dispatcher(
    tmp_path: Path,
    session: FakeSession,
    *,
    max_attempts: int = 3,
    timeout_seconds: float = 5.0,
    sleep: Any = lambda _delay: None,
) -> Any:
    config = delivery.AlertDeliveryConfig(
        webhook_url="https://alerts.example.test/private-hook",
        bearer_token="LEAK-SENTINEL-BEARER",
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
    return delivery.OperationalAlertDispatcher(
        config,
        receipt_dir=tmp_path,
        session=session,
        sleep=sleep,
        clock=lambda: DELIVERED_AT,
    )


@pytest.mark.parametrize(
    ("code", "expected_class", "severity"),
    [
        ("backup_failed", "backup_failure", "warning"),
        ("external_backup_wrong_release", "wrong_release_receipt", "warning"),
        ("restore_drill_wrong_release", "wrong_release_receipt", "warning"),
        ("worker_stale", "worker_stale", "critical"),
        ("queue_stale", "stuck_jobs", "warning"),
    ],
)
def test_supported_mapping_and_payload_are_strictly_allowlisted(
    tmp_path: Path,
    code: str,
    expected_class: str,
    severity: str,
) -> None:
    session = FakeSession([FakeResponse(202)])
    dispatcher = _dispatcher(tmp_path, session)
    snapshot = _snapshot(_alert(code, severity))

    incidents = delivery.incidents_from_snapshot(snapshot)
    receipts = dispatcher.dispatch(snapshot)

    assert len(incidents) == 1
    assert incidents[0].alert_class == expected_class
    assert incidents[0].code == code
    assert incidents[0].severity == severity
    assert len(session.posts) == 1
    payload = session.posts[0]["json"]
    assert set(payload) == {
        "schema_version",
        "alert_class",
        "code",
        "severity",
        "release_id",
        "observed_at",
        "fingerprint",
    }
    assert payload["alert_class"] == expected_class
    assert payload["code"] == code
    assert payload["schema_version"] == 1
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "https://alerts.example.test/private-hook",
        "LEAK-SENTINEL-BEARER",
        *PRIVATE_SENTINELS,
    ):
        assert forbidden not in serialized
    assert {receipt.alert_class for receipt in receipts} == {
        "backup_failure",
        "wrong_release_receipt",
        "worker_stale",
        "stuck_jobs",
    }


def test_fingerprint_is_canonical_and_excludes_mutable_alert_text() -> None:
    first = _snapshot(_alert("backup_failed"))
    second = _snapshot(
        {
            "message": "different private message",
            "severity": "warning",
            "code": "backup_failed",
        }
    )
    second["generated_at"] = "2026-08-10T12:00:00+00:00"

    first_incident = delivery.incidents_from_snapshot(first)[0]
    second_incident = delivery.incidents_from_snapshot(second)[0]

    assert first_incident.fingerprint == (
        "sha256:6d09e305e310512f2503ef66013b3dcf69e2627cd89a5680397724a3610945ad"
    )
    assert second_incident.fingerprint == first_incident.fingerprint


def test_wrong_release_code_selection_is_deterministic() -> None:
    snapshot = _snapshot(
        _alert("restore_drill_wrong_release"),
        _alert("external_backup_wrong_release"),
    )

    incident = delivery.incidents_from_snapshot(snapshot)[0]

    assert incident.alert_class == "wrong_release_receipt"
    assert incident.code == "external_backup_wrong_release"


@pytest.mark.parametrize(
    "release_id",
    [
        "release/2026-08-10",
        "r" * 192,
    ],
)
def test_dispatcher_accepts_the_runtime_identity_release_id_contract(
    release_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.runtime_identity import get_runtime_identity

    monkeypatch.setenv("NOVEL_RELEASE_ID", release_id)
    runtime_release_id = get_runtime_identity().release_id

    incident = delivery.incidents_from_snapshot(
        _snapshot(_alert("backup_failed"), release_id=runtime_release_id)
    )[0]

    assert runtime_release_id == release_id
    assert incident.release_id == release_id
    assert len(incident.fingerprint) == len("sha256:") + 64


def test_unsupported_alerts_are_not_dispatched(tmp_path: Path) -> None:
    session = FakeSession([])
    dispatcher = _dispatcher(tmp_path, session)

    incidents = delivery.incidents_from_snapshot(_snapshot(_alert("../../private")))
    receipts = dispatcher.dispatch(_snapshot(_alert("../../private")))

    assert incidents == ()
    assert session.posts == []
    assert all(receipt.status == "resolved" for receipt in receipts)
    assert {path.name for path in tmp_path.glob("alert-*.receipt.json")} == EXPECTED_RECEIPT_NAMES


def test_receipt_directory_rejects_parent_traversal_before_post(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200)])
    config = delivery.AlertDeliveryConfig(webhook_url="https://alerts.example.test/hook")

    with pytest.raises(ValueError, match="receipt directory"):
        delivery.OperationalAlertDispatcher(
            config,
            receipt_dir=tmp_path / "nested" / ".." / "escaped",
            session=session,
        )

    assert session.posts == []


def test_production_webhook_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        delivery.AlertDeliveryConfig(webhook_url="http://example.test/hook")


def test_loopback_http_requires_explicit_synthetic_mode() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        delivery.AlertDeliveryConfig(webhook_url="http://127.0.0.1:18765/hook")

    config = delivery.AlertDeliveryConfig(
        webhook_url="http://127.0.0.1:18765/hook",
        allow_loopback_http=True,
    )

    assert config.webhook_url == "http://127.0.0.1:18765/hook"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/hook",
        "http://localhost:18765/hook",
        "http://192.0.2.1:18765/hook",
        "ftp://127.0.0.1:18765/hook",
    ],
)
def test_synthetic_mode_rejects_non_literal_loopback_http(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS|loopback"):
        delivery.AlertDeliveryConfig(webhook_url=url, allow_loopback_http=True)


def test_retryable_failures_then_success_use_bounded_attempts_and_backoff(tmp_path: Path) -> None:
    sleeps: list[float] = []
    session = FakeSession(
        [
            requests.ConnectionError("LEAK-SENTINEL-NETWORK"),
            FakeResponse(503, "LEAK-SENTINEL-RESPONSE"),
            FakeResponse(202),
        ]
    )
    dispatcher = _dispatcher(tmp_path, session, sleep=sleeps.append)

    receipts = dispatcher.dispatch(_snapshot(_alert("backup_failed")))

    receipt = next(item for item in receipts if item.alert_class == "backup_failure")
    assert receipt.status == "delivered"
    assert receipt.attempt_count == 3
    assert receipt.http_status == 202
    assert len(session.posts) == 3
    assert sleeps == [1.0, 2.0]
    assert all(math.isfinite(delay) and 0 < delay <= 5.0 for delay in sleeps)


def test_redirect_responses_are_not_followed_or_delivered(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(307), FakeResponse(307), FakeResponse(307)])
    dispatcher = _dispatcher(tmp_path, session)

    receipts = dispatcher.dispatch(_snapshot(_alert("backup_failed")))

    receipt = next(item for item in receipts if item.alert_class == "backup_failure")
    assert receipt.status == "failed"
    assert receipt.attempt_count == 3
    assert receipt.http_status == 307
    assert len(session.posts) == 3
    assert all(post["allow_redirects"] is False for post in session.posts)


def test_exhausted_delivery_writes_redacted_failed_receipt(tmp_path: Path) -> None:
    session = FakeSession(
        [
            requests.Timeout("LEAK-SENTINEL-URL https://private.invalid"),
            FakeResponse(502, "LEAK-SENTINEL-RESPONSE-BODY"),
            FakeResponse(503, "LEAK-SENTINEL-RESPONSE-BODY"),
        ]
    )
    dispatcher = _dispatcher(tmp_path, session)

    receipts = dispatcher.dispatch(_snapshot(_alert("backup_failed")))

    receipt = next(item for item in receipts if item.alert_class == "backup_failure")
    assert receipt.status == "failed"
    assert receipt.attempt_count == 3
    assert receipt.http_status == 503
    receipt_path = tmp_path / "alert-backup_failure.receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "status",
        "alert_class",
        "code",
        "attempt_count",
        "observed_at",
        "delivered_at",
        "release_id",
        "fingerprint",
        "http_status",
    }
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "https://alerts.example.test/private-hook",
        "https://private.invalid",
        "LEAK-SENTINEL-BEARER",
        "LEAK-SENTINEL-URL",
        "LEAK-SENTINEL-RESPONSE-BODY",
        *PRIVATE_SENTINELS,
    ):
        assert forbidden not in serialized


def test_delivered_fingerprint_suppresses_duplicate_post(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(204)])
    dispatcher = _dispatcher(tmp_path, session)
    snapshot = _snapshot(_alert("backup_failed"))

    first = dispatcher.dispatch(snapshot)
    second = dispatcher.dispatch(snapshot)

    first_receipt = next(item for item in first if item.alert_class == "backup_failure")
    second_receipt = next(item for item in second if item.alert_class == "backup_failure")
    assert first_receipt.status == second_receipt.status == "delivered"
    assert first_receipt.fingerprint == second_receipt.fingerprint
    assert first_receipt.delivered_at == second_receipt.delivered_at
    assert len(session.posts) == 1


@pytest.mark.parametrize(
    ("snapshot_code", "receipt_code", "receipt_release", "receipt_name"),
    [
        (
            "backup_failed",
            "backup_failed",
            "release-b",
            "alert-backup_failure.receipt.json",
        ),
        (
            "restore_drill_wrong_release",
            "external_backup_wrong_release",
            "release-a",
            "alert-wrong_release_receipt.receipt.json",
        ),
    ],
)
def test_semantically_mismatched_receipt_cannot_suppress_delivery(
    tmp_path: Path,
    snapshot_code: str,
    receipt_code: str,
    receipt_release: str,
    receipt_name: str,
) -> None:
    snapshot = _snapshot(_alert(snapshot_code))
    incident = delivery.incidents_from_snapshot(snapshot)[0]
    forged = {
        "schema_version": 1,
        "status": "delivered",
        "alert_class": incident.alert_class,
        "code": receipt_code,
        "attempt_count": 1,
        "observed_at": OBSERVED_AT,
        "delivered_at": DELIVERED_AT.isoformat(),
        "release_id": receipt_release,
        "fingerprint": incident.fingerprint,
        "http_status": 200,
    }
    (tmp_path / receipt_name).write_text(json.dumps(forged), encoding="utf-8")
    session = FakeSession([FakeResponse(202)])
    dispatcher = _dispatcher(tmp_path, session)

    receipts = dispatcher.dispatch(snapshot)

    receipt = next(item for item in receipts if item.alert_class == incident.alert_class)
    assert len(session.posts) == 1
    assert receipt.status == "delivered"
    assert receipt.code == incident.code
    assert receipt.release_id == incident.release_id
    assert receipt.fingerprint == incident.fingerprint


def test_valid_existing_receipt_is_normalized_to_mode_0600_before_dedupe(
    tmp_path: Path,
) -> None:
    session = FakeSession([FakeResponse(204)])
    dispatcher = _dispatcher(tmp_path, session)
    snapshot = _snapshot(_alert("backup_failed"))
    receipt_path = tmp_path / "alert-backup_failure.receipt.json"
    dispatcher.dispatch(snapshot)
    receipt_path.chmod(0o644)

    dispatcher.dispatch(snapshot)

    assert len(session.posts) == 1
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def test_resolved_state_allows_same_fingerprint_to_recur(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(202), FakeResponse(202)])
    dispatcher = _dispatcher(tmp_path, session)
    active = _snapshot(_alert("backup_failed"))

    first = dispatcher.dispatch(active)
    resolved = dispatcher.dispatch(_snapshot())
    recurrence = dispatcher.dispatch(active)

    first_receipt = next(item for item in first if item.alert_class == "backup_failure")
    resolved_receipt = next(item for item in resolved if item.alert_class == "backup_failure")
    recurrence_receipt = next(item for item in recurrence if item.alert_class == "backup_failure")
    assert first_receipt.status == "delivered"
    assert resolved_receipt.status == "resolved"
    assert resolved_receipt.attempt_count == 0
    assert resolved_receipt.code == ""
    assert resolved_receipt.fingerprint == ""
    assert recurrence_receipt.status == "delivered"
    assert recurrence_receipt.fingerprint == first_receipt.fingerprint
    assert len(session.posts) == 2


def test_receipts_are_regular_mode_0600_files(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200)])
    dispatcher = _dispatcher(tmp_path, session)

    dispatcher.dispatch(_snapshot(_alert("worker_stale", "critical")))

    paths = list(tmp_path.glob("alert-*.receipt.json"))
    assert {path.name for path in paths} == EXPECTED_RECEIPT_NAMES
    for path in paths:
        metadata = path.stat()
        assert stat.S_ISREG(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == 0o600


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(-100, 1), (0, 1), (1, 1), (2, 2), (3, 3), (999, 3)],
)
def test_attempt_count_is_clamped_to_one_through_three(configured: int, expected: int) -> None:
    config = delivery.AlertDeliveryConfig(
        webhook_url="https://alerts.example.test/hook",
        max_attempts=configured,
    )

    assert config.max_attempts == expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(-1.0, 5.0), (0.0, 5.0), (float("nan"), 5.0), (float("inf"), 5.0), (0.25, 0.25), (9999.0, 60.0)],
)
def test_timeout_is_finite_positive_and_bounded(configured: float, expected: float) -> None:
    config = delivery.AlertDeliveryConfig(
        webhook_url="https://alerts.example.test/hook",
        timeout_seconds=configured,
    )

    assert config.timeout_seconds == expected
    assert math.isfinite(config.timeout_seconds)
    assert 0 < config.timeout_seconds <= 60.0


def test_incident_config_and_receipt_records_are_frozen(tmp_path: Path) -> None:
    config = delivery.AlertDeliveryConfig(webhook_url="https://alerts.example.test/hook")
    incident = delivery.incidents_from_snapshot(_snapshot(_alert("backup_failed")))[0]
    session = FakeSession([FakeResponse(200)])
    receipt = next(
        item
        for item in _dispatcher(tmp_path, session).dispatch(_snapshot(_alert("backup_failed")))
        if item.alert_class == "backup_failure"
    )

    with pytest.raises(FrozenInstanceError):
        config.max_attempts = 2
    with pytest.raises(FrozenInstanceError):
        incident.code = "queue_stale"
    with pytest.raises(FrozenInstanceError):
        receipt.status = "failed"


def test_atomic_replace_failure_cleans_uncommitted_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([FakeResponse(200)])
    dispatcher = _dispatcher(tmp_path, session)

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(delivery.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        dispatcher.dispatch(_snapshot(_alert("backup_failed")))

    assert not list(tmp_path.glob(".alert-*.tmp"))
    assert not (tmp_path / "alert-backup_failure.receipt.json").exists()
