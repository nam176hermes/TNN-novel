from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
import pytest

from app.database.db import init_db
from app.recovery_receipts import publish_recovery_receipt
from app.mobile_api.services.operational_metrics_service import (
    OperationalMetricsService,
    evaluate_operational_alerts,
)


def _heartbeat(data_dir: Path) -> None:
    path = data_dir / "logs/runtime/import-worker.heartbeat"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": 100,
                "worker_id": "worker-a",
                "release_id": "release-a",
                "git_sha": "abc1234",
                "component": "import-worker",
            }
        ),
        encoding="utf-8",
    )


def test_operational_snapshot_is_bounded_and_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    _heartbeat(data_dir)
    monkeypatch.setattr("app.mobile_api.services.operational_metrics_service.mobile_settings.import_job_run_in_api", False)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)
    receipt_counts = {
        "external-backup.receipt.json": {
            "archive_verified": 1,
            "metadata_verified": 1,
            "checksum_verified": 1,
            "remote_uploads_verified": 3,
            "remote_metadata_verified": 2,
        },
        "restore-drill.receipt.json": {
            "checksum_verified": 1,
            "sqlite_integrity_checks": 1,
            "foreign_key_violations": 0,
            "artifact_paths_scanned": 0,
            "api_readiness_checks": 1,
            "authenticated_reader_smokes": 1,
        },
    }
    for name, validation_counts in receipt_counts.items():
        publish_recovery_receipt(
            data_dir / "logs/runtime" / name,
            archive_hash_id="sha256:" + "a" * 64,
            validation_counts=validation_counts,
            producer_version="release-a",
            completed_at=datetime.fromtimestamp(90, tz=timezone.utc),
        )

    snapshot = OperationalMetricsService(db_path, data_dir).snapshot(
        now=datetime.fromtimestamp(100, tz=timezone.utc),
        use_cache=False,
    )

    assert snapshot["worker"]["status"] == "ready"
    assert snapshot["queue"] == {"depth": 0, "oldest_age_seconds": None}
    assert snapshot["artifacts"] == {
        "status": "ok",
        "scanned": 0,
        "error_count": 0,
        "errors_by_status": {},
    }
    assert snapshot["tts"]["reason"] == "gpu_unavailable"
    assert snapshot["backup"]["state"] == "fresh"
    assert snapshot["restore_drill"]["state"] == "fresh"
    serialized = json.dumps(snapshot)
    for forbidden in (str(tmp_path), "pipeline.db", "worker-a", "authorization", "cookie", "token"):
        assert forbidden not in serialized.lower()


def test_corrupt_receipt_payload_cannot_leak_source_data_through_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    monkeypatch.setattr("app.mobile_api.services.operational_metrics_service.mobile_settings.import_job_run_in_api", True)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)
    (runtime_dir / "restore-drill.receipt.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "completed_at": "2026-07-24T12:00:00+00:00",
                "archive_hash_id": "sha256:" + "a" * 64,
                "validation_counts": {"sqlite_integrity_checks": 1},
                "producer_version": "release-a",
                "archive_path": "/private/backups/novel-pipeline-backup-sensitive.tar.gz.enc",
                "credential": "LEAK-SENTINEL-CREDENTIAL",
                "connection_string": "postgresql://private-host/private-db",
                "bucket_key": "private-bucket/private-key",
            }
        ),
        encoding="utf-8",
    )

    snapshot = OperationalMetricsService(db_path, data_dir).snapshot(use_cache=False)
    serialized = json.dumps(snapshot)

    assert snapshot["restore_drill"]["state"] == "corrupt"
    for forbidden in (
        "LEAK-SENTINEL-CREDENTIAL",
        "/private/backups/",
        "novel-pipeline-backup-sensitive.tar.gz.enc",
        "postgresql://private-host/private-db",
        "private-bucket/private-key",
        "archive_path",
        "connection_string",
        "bucket_key",
    ):
        assert forbidden not in serialized


def test_alert_rules_cover_worker_release_disk_queue_backup_restore_and_artifacts() -> None:
    snapshot = {
        "worker": {"required": True, "queue_claim_capable": False},
        "release": {"worker_match": False},
        "storage": {"disk_free_bytes": 1},
        "queue": {"oldest_age_seconds": 4000},
        "jobs": {"failed_or_interrupted": 2},
        "backup": {"state": "missing"},
        "restore_drill": {"state": "future"},
        "artifacts": {"error_count": 1},
    }

    alerts = evaluate_operational_alerts(snapshot)

    assert {alert["code"] for alert in alerts} == {
        "worker_not_ready",
        "release_mismatch",
        "disk_critical",
        "queue_stale",
        "jobs_failed",
        "external_backup_missing",
        "backup_stale",
        "restore_drill_future",
        "restore_drill_stale",
        "artifact_integrity",
    }


@pytest.mark.parametrize(
    ("state", "suffix"),
    [
        ("corrupt", "invalid"),
        ("stale", "stale"),
        ("wrong_release", "wrong_release"),
        ("missing", "missing"),
        ("future", "future"),
    ],
)
def test_recovery_alert_mapping_covers_each_non_fresh_state(state: str, suffix: str) -> None:
    snapshot = {
        "worker": {"required": False, "queue_claim_capable": True},
        "release": {"worker_match": True},
        "storage": {"disk_free_bytes": 2 * 1024**3},
        "queue": {"oldest_age_seconds": None},
        "jobs": {"failed_or_interrupted": 0},
        "backup": {"state": state},
        "restore_drill": {"state": state},
        "artifacts": {"error_count": 0},
    }

    codes = {alert["code"] for alert in evaluate_operational_alerts(snapshot)}

    expected = {f"external_backup_{suffix}", f"restore_drill_{suffix}", "backup_stale"}
    expected.add("restore_drill_stale")
    assert codes == expected


@pytest.mark.asyncio
async def test_operational_metrics_endpoint_requires_authentication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api.config import mobile_settings
    from app.mobile_api.main import create_app

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(mobile_settings, "import_job_run_in_api", True)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/api/ops/metrics")
        login = await client.post(
            "/api/auth/login",
            json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
        )
        allowed = await client.get(
            "/api/ops/metrics",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert "alerts" in allowed.json()
