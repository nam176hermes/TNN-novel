from __future__ import annotations

from pathlib import Path
import threading
import time

import httpx
import pytest

from app.database.db import init_db
from app.database import db, operations_repository
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import auth as auth_router
from app.mobile_api.routers import jobs as jobs_router
from app.mobile_api import dependencies as mobile_dependencies
from app.mobile_api.routers import health as health_router
from app.mobile_api.services.job_service import JobTracker


def test_db_operational_event_exports_are_repository_function_objects() -> None:
    assert db.record_operational_event is operations_repository.record_operational_event
    assert db.list_operational_events is operations_repository.list_operational_events


def test_data_size_snapshot_does_not_block_on_slow_filesystem_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_started = threading.Event()
    release_scan = threading.Event()

    def slow_scan(_: Path) -> int:
        scan_started.set()
        release_scan.wait(timeout=5)
        return 987_654

    monkeypatch.setattr(health_router, "_directory_size_bytes", slow_scan)
    started_at = time.perf_counter()
    snapshot = health_router._cached_directory_size_bytes(tmp_path, minimum_bytes=123_456)
    elapsed = time.perf_counter() - started_at

    assert snapshot == 123_456
    assert elapsed < 0.1
    assert scan_started.wait(timeout=1)

    release_scan.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if health_router._cached_directory_size_bytes(tmp_path, minimum_bytes=123_456) == 987_654:
            break
        time.sleep(0.01)
    else:
        pytest.fail("background data-size scan did not publish its snapshot")


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_system_status_requires_authentication() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/system/status")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_system_status_reports_runtime_without_secrets(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import claim_mobile_job

    init_db(temp_db_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    tracker = JobTracker(db_path=temp_db_path)
    running = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    assert claim_mobile_job(
        temp_db_path,
        job_id=running.job_id,
        worker_id="status-test",
        lease_token="status-test-token",
        lease_seconds=120,
    )
    tracker.jobs.pop(running.job_id, None)
    loaded_running = tracker.get_job(running.job_id)
    assert loaded_running is not None
    loaded_running.message = "Translating"
    failed = tracker.create_job("translate", [11], 1, {"provider_id": "deepseek"})
    tracker.update_job(failed.job_id, status="failed", message="Provider failed", error="quota exhausted")

    monkeypatch.setattr(mobile_dependencies, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(mobile_dependencies, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(auth_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.session_auth.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.audit.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_shared_job_tracker", lambda: tracker)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/system/status", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["public_deploy"] is mobile_settings.public_deploy
    assert payload["api_ready"] is True
    assert payload["active_provider"] == "gemini"
    assert payload["upload_max_bytes"] == mobile_settings.upload_max_bytes
    assert payload["asset_protection_enabled"] is True
    assert payload["active_jobs"] == 1
    assert payload["running_jobs"] == 1
    assert payload["last_failed_job"]["job_id"] == failed.job_id
    assert payload["last_failed_job"]["message"] == "Provider failed"
    assert payload["database_available"] is True
    assert payload["data_directory_available"] is True
    assert payload["data_size_bytes"] >= payload["db_size_bytes"]
    assert payload["storage_health"] == "healthy"
    assert payload["storage_label"] == "Configured data storage"
    assert "database_path" not in payload
    assert "data_dir" not in payload
    assert str(temp_db_path) not in response.text
    assert str(data_dir) not in response.text
    assert "secret" not in response.text.lower()
    assert "api_key" not in response.text.lower()


@pytest.mark.asyncio
async def test_system_status_reports_sanitized_operational_events(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import record_operational_event

    init_db(temp_db_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    tracker = JobTracker(db_path=temp_db_path)
    interrupted = tracker.create_job("translate", [12], 1, {"provider_id": "gemini"})
    tracker.update_job(
        interrupted.job_id,
        status="interrupted",
        message="Job interrupted before completion. Please retry the job.",
        error="Job interrupted before completion",
    )
    record_operational_event(
        temp_db_path,
        event_type="provider_failure",
        severity="error",
        source="job",
        message="provider failed with provider-secret at /tmp/provider-secret/cache.json",
        job_id=interrupted.job_id,
        details={"api_key": "sk-test-secret", "provider_id": "gemini"},
    )
    record_operational_event(
        temp_db_path,
        event_type="backup_success",
        severity="info",
        source="backup-local",
        message="Backup completed",
        details={"backup_name": "novel-pipeline-backup-test.tar.gz"},
    )

    monkeypatch.setattr(mobile_dependencies, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(mobile_dependencies, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(auth_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.session_auth.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.audit.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_shared_job_tracker", lambda: tracker)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/system/status", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["interrupted_jobs"] == 1
    assert payload["recent_operational_errors"]
    assert payload["recent_operational_errors"][0]["event_type"] == "provider_failure"
    assert payload["recent_operational_errors"][0]["message"] == "Operational event recorded. Check server logs."
    assert payload["recent_operational_errors"][0]["details"]["api_key"] == "[redacted]"
    assert payload["recent_backup_events"][0]["event_type"] == "backup_success"
    assert payload["recent_backup_events"][0]["message"] == "Backup completed"
    assert "provider-secret" not in response.text
    assert "sk-test-secret" not in response.text
    assert "/tmp/" not in response.text


@pytest.mark.asyncio
async def test_system_status_exposes_only_safe_retention_counts_and_summary(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.retention_service import RetentionService, RetentionSummary

    init_db(temp_db_path)
    data_dir = tmp_path / "retention-status-data"
    data_dir.mkdir(parents=True)
    tracker = JobTracker(db_path=temp_db_path)
    service = RetentionService(temp_db_path, settings=mobile_settings)
    service._last_summary = RetentionSummary(
        last_run_at="2026-07-13T12:00:00+00:00",
        deleted_counts={
            "auth_sessions": 3,
            "auth_login_failures": 4,
            "operational_events": 5,
        },
        result="completed",
    )

    monkeypatch.setattr(mobile_dependencies, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(mobile_dependencies, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(auth_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.session_auth.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.audit.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(jobs_router, "get_shared_job_tracker", lambda: tracker)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(app.state, "retention_service", service)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/system/status", headers=headers)

    assert response.status_code == 200
    retention = response.json()["retention"]
    assert set(retention) == {"table_counts", "auth_session_counts", "last_run"}
    assert set(retention["table_counts"]) == {
        "auth_sessions",
        "auth_login_failures",
        "operational_events",
    }
    assert all(isinstance(count, int) for count in retention["table_counts"].values())
    assert retention["table_counts"]["auth_sessions"] == 1
    assert retention["auth_session_counts"] == {
        "total": 1,
        "active": 1,
        "expired": 0,
        "revoked": 0,
        "age_eligible": 0,
        "row_cap_eligible": 0,
        "would_remove": 0,
    }
    assert retention["last_run"] == {
        "last_run_at": "2026-07-13T12:00:00+00:00",
        "deleted_counts": {
            "auth_sessions": 3,
            "auth_login_failures": 4,
            "operational_events": 5,
        },
        "result": "completed",
    }
    retention_text = str(retention).lower()
    assert str(temp_db_path) not in str(retention)
    assert str(data_dir) not in str(retention)
    assert not any(marker in retention_text for marker in ("select ", "exception", "row_values"))
