from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import init_db
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import auth as auth_router
from app.mobile_api.routers import jobs as jobs_router
from app.mobile_api import dependencies as mobile_dependencies
from app.mobile_api.routers import health as health_router
from app.mobile_api.services.job_service import JobTracker


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
