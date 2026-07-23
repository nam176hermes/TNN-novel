from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.runtime_identity import get_runtime_identity


def test_runtime_identity_exposes_only_allowlisted_build_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVEL_GIT_SHA", "abc1234")
    monkeypatch.setenv("NOVEL_BUILD_TIMESTAMP", "2026-07-23T12:00:00Z")
    monkeypatch.setenv("NOVEL_RELEASE_ID", "ws4-abc1234")
    monkeypatch.setenv("NOVEL_IMAGE_DIGEST", "sha256:012345")
    monkeypatch.setenv("NOVEL_COMPONENT", "api")

    identity = get_runtime_identity()

    assert identity.git_sha == "abc1234"
    assert identity.release_id == "ws4-abc1234"
    assert identity.image_digest == "sha256:012345"
    assert identity.component == "api"
    assert "secret" not in identity.safe_dict()


def test_runtime_identity_rejects_unsafe_environment_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVEL_RELEASE_ID", "unsafe\nAuthorization: bearer secret")

    assert get_runtime_identity().release_id == "development"


@pytest.mark.asyncio
async def test_version_endpoint_reports_traceable_release_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api.main import create_app

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", tmp_path / "data")
    monkeypatch.setenv("NOVEL_GIT_SHA", "abc1234")
    monkeypatch.setenv("NOVEL_RELEASE_ID", "ws4-abc1234")
    monkeypatch.setenv("NOVEL_COMPONENT", "api")
    app = create_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_sha"] == "abc1234"
    assert payload["release_id"] == "ws4-abc1234"
    assert payload["component"] == "api"
    assert payload["schema_revision"]


def test_worker_heartbeat_includes_shared_release_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.import_worker import WorkerHeartbeat

    monkeypatch.setenv("NOVEL_GIT_SHA", "abc1234")
    monkeypatch.setenv("NOVEL_RELEASE_ID", "ws4-abc1234")
    monkeypatch.setenv("NOVEL_COMPONENT", "import-worker")
    heartbeat_path = tmp_path / "worker.heartbeat"

    WorkerHeartbeat(heartbeat_path, clock=lambda: 100, worker_id="worker-a").touch()
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))

    assert payload == {
        "updated_at": 100,
        "worker_id": "worker-a",
        "release_id": "ws4-abc1234",
        "git_sha": "abc1234",
        "component": "import-worker",
    }
