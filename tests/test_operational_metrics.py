from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
import pytest

from app.database.db import init_db
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
    serialized = json.dumps(snapshot)
    for forbidden in (str(tmp_path), "pipeline.db", "worker-a", "authorization", "cookie", "token"):
        assert forbidden not in serialized.lower()


def test_alert_rules_cover_worker_release_disk_queue_backup_restore_and_artifacts() -> None:
    snapshot = {
        "worker": {"required": True, "queue_claim_capable": False},
        "release": {"worker_match": False},
        "storage": {"disk_free_bytes": 1},
        "queue": {"oldest_age_seconds": 4000},
        "jobs": {"failed_or_interrupted": 2},
        "backup": {"latest_age_seconds": None},
        "restore_drill": {"status": "failed", "age_seconds": None},
        "artifacts": {"error_count": 1},
    }

    alerts = evaluate_operational_alerts(snapshot)

    assert {alert["code"] for alert in alerts} == {
        "worker_not_ready",
        "release_mismatch",
        "disk_critical",
        "queue_stale",
        "jobs_failed",
        "backup_stale",
        "restore_drill_stale",
        "artifact_integrity",
    }


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
