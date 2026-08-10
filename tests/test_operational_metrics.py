from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

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
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO mobile_jobs (job_id, job_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("backup-failure", "BACKUP", "FAILED", "2026-08-09T00:00:00+00:00", "2026-08-09T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO mobile_jobs (job_id, job_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("non-backup-failure", "translate", "failed", "2026-08-09T00:00:00+00:00", "2026-08-09T00:00:00+00:00"),
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
    assert snapshot["jobs"]["backup_failed"] == 1
    serialized = json.dumps(snapshot)
    for forbidden in (str(tmp_path), "pipeline.db", "worker-a", "authorization", "cookie", "token"):
        assert forbidden not in serialized.lower()


def test_read_only_operational_snapshot_does_not_create_missing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "missing.db"
    monkeypatch.setattr(
        "app.mobile_api.services.operational_metrics_service.mobile_settings.import_job_run_in_api",
        True,
    )

    service = OperationalMetricsService(database_path, data_dir, read_only=True)

    with pytest.raises(sqlite3.OperationalError):
        service.snapshot(use_cache=False)
    assert not database_path.exists()


def test_guarded_snapshot_database_size_comes_from_query_inode_during_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "pipeline.db"
    replacement_path = data_dir / "replacement.db"
    saved_path = data_dir / "saved.db"
    init_db(database_path)
    init_db(replacement_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO mobile_jobs (job_id, job_type, status, created_at, updated_at)
            VALUES ('guarded-backup', 'backup', 'failed', '2026-08-10', '2026-08-10')
            """
        )
    with sqlite3.connect(replacement_path) as connection:
        connection.execute("CREATE TABLE size_padding (payload BLOB NOT NULL)")
        connection.execute("INSERT INTO size_padding VALUES (zeroblob(1048576))")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    guarded_size = database_path.stat().st_size
    assert replacement_path.stat().st_size > guarded_size
    monkeypatch.setattr(
        "app.mobile_api.services.operational_metrics_service.mobile_settings.import_job_run_in_api",
        True,
    )
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)
    reader = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    service = OperationalMetricsService(
        database_path,
        data_dir,
        read_only=True,
        database_connection=reader,
        database_size_bytes=guarded_size,
    )

    database_path.rename(saved_path)
    replacement_path.rename(database_path)
    try:
        snapshot = service.snapshot(use_cache=False)
    finally:
        database_path.rename(replacement_path)
        saved_path.rename(database_path)
        reader.close()

    assert snapshot["jobs"]["backup_failed"] == 1
    assert snapshot["storage"]["database_size_bytes"] == guarded_size


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


def test_alert_rules_emit_dispatchable_backup_failure_and_worker_stale_codes() -> None:
    snapshot = {
        "worker": {"required": True, "status": "stale", "queue_claim_capable": False},
        "release": {"worker_match": True},
        "storage": {"disk_free_bytes": 2 * 1024**3},
        "queue": {"oldest_age_seconds": None},
        "jobs": {"failed_or_interrupted": 0, "backup_failed": 1},
        "backup": {"state": "fresh"},
        "restore_drill": {"state": "fresh"},
        "artifacts": {"error_count": 0},
    }

    codes = {item["code"] for item in evaluate_operational_alerts(snapshot)}

    assert {"worker_not_ready", "worker_stale", "backup_failed"}.issubset(codes)


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
