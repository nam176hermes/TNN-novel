from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import PROJECT_ROOT, settings as app_settings
from app.services.operational_alert_delivery import SUPPORTED_ALERT_CLASSES
from scripts import dispatch_operational_alerts, smoke_operational_alerts


PAYLOAD_KEYS = {
    "schema_version",
    "alert_class",
    "code",
    "severity",
    "release_id",
    "observed_at",
    "fingerprint",
}
RECEIPT_FILENAMES = {
    "alert-backup_failure.receipt.json",
    "alert-wrong_release_receipt.receipt.json",
    "alert-worker_stale.receipt.json",
    "alert-stuck_jobs.receipt.json",
}


def test_dispatch_cli_missing_webhook_exits_two_without_value_leak(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "private-unrelated-environment-value"
    monkeypatch.delenv("NOVEL_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("PRIVATE_UNRELATED_SETTING", sentinel)

    result = dispatch_operational_alerts.main()

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "status=configuration_error\n"
    assert sentinel not in captured.err


def test_dispatch_cli_uses_fresh_snapshot_and_prints_only_class_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    webhook = "https://alerts.example.invalid/private-hook"
    token = "private-bearer-token"
    private_body = "private-response-body"
    snapshot = {"private": private_body}
    observed: dict[str, object] = {}

    class FakeMetricsService:
        def __init__(self, db_path: Path, data_dir: Path) -> None:
            observed["metrics_paths"] = (db_path, data_dir)

        def snapshot(self, *, use_cache: bool = True) -> dict[str, str]:
            observed["use_cache"] = use_cache
            return snapshot

    class FakeDispatcher:
        def __init__(self, config: object, *, receipt_dir: Path) -> None:
            observed["config"] = config
            observed["receipt_dir"] = receipt_dir

        def dispatch(self, received: object) -> tuple[SimpleNamespace, ...]:
            observed["snapshot"] = received
            return tuple(
                SimpleNamespace(alert_class=alert_class, status="delivered")
                for alert_class in SUPPORTED_ALERT_CLASSES
            )

    data_dir = tmp_path / "data"
    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setattr(
        dispatch_operational_alerts,
        "OperationalMetricsService",
        FakeMetricsService,
    )
    monkeypatch.setattr(
        dispatch_operational_alerts,
        "OperationalAlertDispatcher",
        FakeDispatcher,
    )
    monkeypatch.setenv("NOVEL_ALERT_WEBHOOK_URL", webhook)
    monkeypatch.setenv("NOVEL_ALERT_WEBHOOK_BEARER_TOKEN", token)
    monkeypatch.setenv("NOVEL_ALERT_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("NOVEL_ALERT_MAX_ATTEMPTS", "2")

    result = dispatch_operational_alerts.main()

    captured = capsys.readouterr()
    assert result == 0
    assert observed["metrics_paths"] == (data_dir / "pipeline.db", data_dir)
    assert observed["use_cache"] is False
    assert observed["snapshot"] is snapshot
    assert observed["receipt_dir"] == data_dir / "logs" / "runtime"
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"class={alert_class} status=delivered"
        for alert_class in SUPPORTED_ALERT_CLASSES
    ]
    for private_value in (webhook, token, private_body, str(data_dir.resolve())):
        assert private_value not in captured.out


def test_dispatch_cli_redacts_receipt_persistence_errors_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = tmp_path / "private-runtime" / "receipt.json"

    class FakeMetricsService:
        def __init__(self, db_path: Path, data_dir: Path) -> None:
            pass

        def snapshot(self, *, use_cache: bool = True) -> dict[str, object]:
            return {"alerts": []}

    class FailingDispatcher:
        def __init__(self, config: object, *, receipt_dir: Path) -> None:
            pass

        def dispatch(self, snapshot: object) -> tuple[object, ...]:
            raise OSError(f"cannot persist {private_path}")

    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(
        dispatch_operational_alerts,
        "OperationalMetricsService",
        FakeMetricsService,
    )
    monkeypatch.setattr(
        dispatch_operational_alerts,
        "OperationalAlertDispatcher",
        FailingDispatcher,
    )
    monkeypatch.setenv("NOVEL_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/hook")

    result = dispatch_operational_alerts.main()

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "status=error\n"
    assert str(private_path) not in captured.err


def test_dispatch_cli_reads_only_allowlisted_alert_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed_names: list[str] = []
    values = {
        "NOVEL_ALERT_WEBHOOK_URL": "https://alerts.example.invalid/hook",
        "NOVEL_ALERT_WEBHOOK_BEARER_TOKEN": "",
        "NOVEL_ALERT_TIMEOUT_SECONDS": "5",
        "NOVEL_ALERT_MAX_ATTEMPTS": "3",
    }

    class FakeMetricsService:
        def __init__(self, db_path: Path, data_dir: Path) -> None:
            pass

        def snapshot(self, *, use_cache: bool = True) -> dict[str, object]:
            return {"alerts": []}

    class FakeDispatcher:
        def __init__(self, config: object, *, receipt_dir: Path) -> None:
            pass

        def dispatch(self, snapshot: object) -> tuple[SimpleNamespace, ...]:
            return tuple(
                SimpleNamespace(alert_class=alert_class, status="resolved")
                for alert_class in SUPPORTED_ALERT_CLASSES
            )

    def tracked_getenv(name: str, default: str = "") -> str:
        observed_names.append(name)
        return values.get(name, default)

    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(dispatch_operational_alerts, "OperationalMetricsService", FakeMetricsService)
    monkeypatch.setattr(dispatch_operational_alerts, "OperationalAlertDispatcher", FakeDispatcher)
    monkeypatch.setattr(dispatch_operational_alerts.os, "getenv", tracked_getenv)

    assert dispatch_operational_alerts.main() == 0
    assert observed_names == list(values)
    assert capsys.readouterr().err == ""


def test_synthetic_smoke_delivers_exactly_four_allowlisted_loopback_requests(
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "isolated-smoke-receipts"
    receipt_dir.mkdir(mode=0o700)

    receipts, captured_requests = smoke_operational_alerts.run_smoke(receipt_dir)

    assert [(receipt.alert_class, receipt.status) for receipt in receipts] == [
        (alert_class, "delivered") for alert_class in SUPPORTED_ALERT_CLASSES
    ]
    assert {path.name for path in receipt_dir.iterdir()} == RECEIPT_FILENAMES
    assert len(captured_requests) == 4
    assert [payload["alert_class"] for payload in captured_requests] == list(
        SUPPORTED_ALERT_CLASSES
    )
    assert all(set(payload) == PAYLOAD_KEYS for payload in captured_requests)
    for path in receipt_dir.iterdir():
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "delivered"


def test_synthetic_smoke_command_output_is_bounded_and_redacted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_dir = tmp_path / "synthetic-private-receipts"
    receipt_dir.mkdir(mode=0o700)

    result = smoke_operational_alerts.main(["--receipt-dir", os.fspath(receipt_dir)])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"class={alert_class} status=delivered"
        for alert_class in SUPPORTED_ALERT_CLASSES
    ]
    for private_value in (
        "http://127.0.0.1",
        "synthetic-response-body",
        os.fspath(receipt_dir.resolve()),
    ):
        assert private_value not in captured.out


@pytest.mark.parametrize(
    "unsafe_path",
    [Path("/"), PROJECT_ROOT, app_settings.resolved_data_dir],
)
def test_synthetic_smoke_rejects_unsafe_receipt_directory_without_disclosure(
    unsafe_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = smoke_operational_alerts.main(["--receipt-dir", os.fspath(unsafe_path)])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "status=configuration_error\n"
    assert os.fspath(unsafe_path) not in captured.err
