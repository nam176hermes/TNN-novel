from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import Response
from pydantic import ValidationError

from app.database.db import init_db
from app.mobile_api.config import MobileAPISettings


def _request():
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/ready",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        }
    )


def _heartbeat(data_dir: Path, *, updated_at: int, release_id: str = "release-a") -> None:
    path = data_dir / "logs/runtime/import-worker.heartbeat"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": updated_at,
                "worker_id": "worker-a",
                "release_id": release_id,
                "git_sha": "abc1234",
                "component": "import-worker",
            }
        ),
        encoding="utf-8",
    )


async def _ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, now: int, heartbeat: bool = True, worker_release: str = "release-a"):
    from app.mobile_api.routers import health as health_router

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    if heartbeat:
        _heartbeat(data_dir, updated_at=now, release_id=worker_release)
    monkeypatch.setattr(health_router.mobile_settings, "import_job_run_in_api", False)
    monkeypatch.setattr(health_router.mobile_settings, "public_deploy", False)
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: db_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    monkeypatch.setattr("app.runtime_status.time.time", lambda: now)
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)
    response = Response()
    payload = await health_router.readiness_check(_request(), response)
    return response, payload.model_dump()


@pytest.mark.asyncio
async def test_fresh_matching_worker_is_ready_while_optional_tts_is_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response, payload = await _ready(tmp_path, monkeypatch, now=100)

    assert response.status_code == 200
    assert payload["status"] == "ready_with_degraded_capabilities"
    assert payload["job_processing"]["status"] == "ready"
    assert payload["job_processing"]["queue_claim_capable"] is True
    assert payload["capabilities"]["tts"]["reason"] == "gpu_unavailable"


@pytest.mark.asyncio
async def test_missing_worker_makes_external_job_processing_not_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response, payload = await _ready(tmp_path, monkeypatch, now=100, heartbeat=False)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["job_processing"]["status"] == "missing"


@pytest.mark.asyncio
async def test_stale_worker_makes_readiness_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mobile_api.routers import health as health_router

    monkeypatch.setattr(health_router.mobile_settings, "import_worker_heartbeat_max_age_seconds", 30)
    response, payload = await _ready(tmp_path, monkeypatch, now=100)
    path = tmp_path / "data/logs/runtime/import-worker.heartbeat"
    heartbeat = json.loads(path.read_text(encoding="utf-8"))
    heartbeat["updated_at"] = 60
    path.write_text(json.dumps(heartbeat), encoding="utf-8")
    response = Response()
    payload = (await health_router.readiness_check(_request(), response)).model_dump()

    assert response.status_code == 503
    assert payload["job_processing"]["status"] == "stale"


@pytest.mark.asyncio
async def test_worker_release_mismatch_is_not_claim_capable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response, payload = await _ready(tmp_path, monkeypatch, now=100, worker_release="release-b")

    assert response.status_code == 503
    assert payload["job_processing"]["status"] == "release_mismatch"
    assert payload["release"]["match"] == "false"


def test_preview_worker_runtime_dependency_requires_a_claim_capable_external_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.routers import import_routes

    data_dir = tmp_path / "preview-runtime"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    monkeypatch.setattr(import_routes, "get_data_dir", lambda: data_dir, raising=False)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: db_path)

    runtime = import_routes.get_import_worker_runtime()

    assert runtime.required is True
    assert runtime.status == "missing"
    assert runtime.queue_claim_capable is False
    assert runtime.safe_dict().keys() == {
        "status",
        "required",
        "heartbeat_age_seconds",
        "release_id",
        "release_match",
        "queue_claim_capable",
        "reason",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("import_preview_wait_timeout_seconds", 0),
        ("import_preview_wait_timeout_seconds", 301),
        ("import_job_sync_wait_timeout_seconds", 0),
        ("import_job_sync_wait_timeout_seconds", 7201),
        ("import_job_wait_poll_seconds", 0),
        ("import_job_wait_poll_seconds", 2.1),
    ],
)
def test_import_job_wait_settings_reject_unbounded_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        MobileAPISettings(**{field: value})
