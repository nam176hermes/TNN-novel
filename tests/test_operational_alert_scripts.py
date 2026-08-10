from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
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
        def __init__(
            self,
            db_path: Path,
            data_dir: Path,
            *,
            read_only: bool = False,
            database_connection: sqlite3.Connection | None = None,
        ) -> None:
            observed["metrics_paths"] = (db_path, data_dir)
            observed["read_only"] = read_only
            observed["database_connection"] = database_connection

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
    data_dir.mkdir()
    (data_dir / "pipeline.db").touch()
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
    assert observed["read_only"] is True
    assert isinstance(observed["database_connection"], sqlite3.Connection)
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
        def __init__(
            self,
            db_path: Path,
            data_dir: Path,
            *,
            read_only: bool = False,
            database_connection: sqlite3.Connection | None = None,
        ) -> None:
            pass

        def snapshot(self, *, use_cache: bool = True) -> dict[str, object]:
            return {"alerts": []}

    class FailingDispatcher:
        def __init__(self, config: object, *, receipt_dir: Path) -> None:
            pass

        def dispatch(self, snapshot: object) -> tuple[object, ...]:
            raise OSError(f"cannot persist {private_path}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pipeline.db").touch()
    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", data_dir)
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
        def __init__(
            self,
            db_path: Path,
            data_dir: Path,
            *,
            read_only: bool = False,
            database_connection: sqlite3.Connection | None = None,
        ) -> None:
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

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pipeline.db").touch()
    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setattr(dispatch_operational_alerts, "OperationalMetricsService", FakeMetricsService)
    monkeypatch.setattr(dispatch_operational_alerts, "OperationalAlertDispatcher", FakeDispatcher)
    monkeypatch.setattr(dispatch_operational_alerts.os, "getenv", tracked_getenv)

    assert dispatch_operational_alerts.main() == 0
    assert observed_names == list(values)
    assert capsys.readouterr().err == ""


def test_dispatch_cli_missing_database_stays_absent_and_error_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "private-production-data"
    data_dir.mkdir()
    database_path = data_dir / "pipeline.db"
    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setenv("NOVEL_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/hook")

    result = dispatch_operational_alerts.main()

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "status=error\n"
    assert not database_path.exists()
    assert os.fspath(database_path) not in captured.err


def test_dispatch_cli_rejects_fifo_database_without_blocking_or_disclosure(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "private-fifo-data"
    data_dir.mkdir()
    database_path = data_dir / "pipeline.db"
    os.mkfifo(database_path, mode=0o600)
    environment = os.environ.copy()
    environment.update(
        {
            "DATA_DIR": os.fspath(data_dir),
            "NOVEL_ALERT_WEBHOOK_URL": "https://alerts.example.invalid/hook",
            "NOVEL_PIPELINE_IGNORE_DOTENV": "1",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "scripts.dispatch_operational_alerts"],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=2.0,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "status=error\n"
    assert os.fspath(database_path) not in result.stderr


def test_dispatch_cli_snapshot_uses_guarded_inode_across_path_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "aba-data"
    data_dir.mkdir()
    database_path = data_dir / "pipeline.db"
    replacement_path = data_dir / "replacement.db"
    saved_path = data_dir / "saved.db"
    for path, marker in ((database_path, "A"), (replacement_path, "B")):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
            connection.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
    observed: dict[str, object] = {}

    class SwappingMetricsService:
        def __init__(
            self,
            db_path: Path,
            data_dir: Path,
            *,
            read_only: bool = False,
            database_connection: sqlite3.Connection | None = None,
        ) -> None:
            self.db_path = db_path
            self.database_connection = database_connection

        def snapshot(self, *, use_cache: bool = True) -> dict[str, object]:
            database_path.rename(saved_path)
            replacement_path.rename(database_path)
            try:
                if self.database_connection is None:
                    with sqlite3.connect(self.db_path) as connection:
                        marker = connection.execute("SELECT value FROM marker").fetchone()[0]
                else:
                    marker = self.database_connection.execute(
                        "SELECT value FROM marker"
                    ).fetchone()[0]
            finally:
                database_path.rename(replacement_path)
                saved_path.rename(database_path)
            return {"guarded_marker": marker}

    class FakeDispatcher:
        def __init__(self, config: object, *, receipt_dir: Path) -> None:
            pass

        def dispatch(self, snapshot: dict[str, object]) -> tuple[SimpleNamespace, ...]:
            observed["snapshot"] = snapshot
            return tuple(
                SimpleNamespace(alert_class=alert_class, status="resolved")
                for alert_class in SUPPORTED_ALERT_CLASSES
            )

    monkeypatch.setattr(dispatch_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setattr(
        dispatch_operational_alerts,
        "OperationalMetricsService",
        SwappingMetricsService,
    )
    monkeypatch.setattr(dispatch_operational_alerts, "OperationalAlertDispatcher", FakeDispatcher)
    monkeypatch.setenv("NOVEL_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/hook")

    assert dispatch_operational_alerts.main() == 0
    assert observed["snapshot"] == {"guarded_marker": "A"}
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


@pytest.mark.parametrize("relative_candidate", ["", "logs/runtime", "nested/deeper"])
def test_synthetic_smoke_rejects_data_subtree_before_server_or_artifacts(
    relative_candidate: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "operator-data"
    candidate = data_dir / relative_candidate
    candidate.mkdir(parents=True, mode=0o700)
    server_calls: list[object] = []

    def forbidden_server(*args: object, **kwargs: object) -> object:
        server_calls.append((args, kwargs))
        raise AssertionError("server must not start for an unsafe receipt directory")

    monkeypatch.setattr(smoke_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setattr(smoke_operational_alerts, "ThreadingHTTPServer", forbidden_server)

    with pytest.raises(ValueError, match="unsafe"):
        smoke_operational_alerts.run_smoke(candidate)

    assert server_calls == []
    assert not any(path.name in RECEIPT_FILENAMES for path in candidate.iterdir())


def test_synthetic_smoke_rejects_symlink_equivalent_data_path_before_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "operator-data"
    candidate = data_dir / "logs" / "runtime"
    candidate.mkdir(parents=True, mode=0o700)
    alias = tmp_path / "receipt-alias"
    alias.symlink_to(candidate, target_is_directory=True)
    server_calls: list[object] = []

    def forbidden_server(*args: object, **kwargs: object) -> object:
        server_calls.append((args, kwargs))
        raise AssertionError("server must not start for an unsafe receipt directory")

    monkeypatch.setattr(smoke_operational_alerts.settings, "data_dir", data_dir)
    monkeypatch.setattr(smoke_operational_alerts, "ThreadingHTTPServer", forbidden_server)

    with pytest.raises(ValueError, match="unsafe"):
        smoke_operational_alerts.run_smoke(alias)

    assert server_calls == []
    assert tuple(candidate.iterdir()) == ()


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
