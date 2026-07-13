from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path

import httpx
import pytest

from app.database.db import init_db
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import backups as backups_router
from app.mobile_api.services.backup_service import BackupService
from scripts import ops


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


@pytest.fixture
def backup_service_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BackupService:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env.example").write_text("EXAMPLE=1\n", encoding="utf-8")
    (project_root / ".env").write_text("GEMINI_API_KEY=top-secret\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_db(data_dir / "pipeline.db")
    (data_dir / "translated").mkdir()
    (data_dir / "translated" / "chapter.txt").write_text("bản dịch", encoding="utf-8")
    (data_dir / "audio").mkdir()
    (data_dir / "audio" / "chapter.mp3").write_bytes(b"audio")
    (data_dir / "exports").mkdir()
    (data_dir / "exports" / "book.txt").write_text("export", encoding="utf-8")
    (data_dir / "logs").mkdir()
    (data_dir / "logs" / "runtime.log").write_text("log", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(ops, "ROOT", project_root)

    service = BackupService(backup_dir=backup_dir, data_dir=data_dir)
    app.dependency_overrides[backups_router.get_backup_service] = lambda: service
    yield service
    app.dependency_overrides.pop(backups_router.get_backup_service, None)


@pytest.mark.asyncio
async def test_system_backup_routes_require_authentication(backup_service_fixture: BackupService) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/system/backups")
        create_response = await client.post("/api/system/backups", json={})

    assert list_response.status_code == 401
    assert create_response.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_backup_create_and_download_with_manifest(
    backup_service_fixture: BackupService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        create_response = await client.post(
            "/api/system/backups",
            json={"include_audio": True, "include_exports": False, "include_job_logs": False},
            headers=headers,
        )
        assert create_response.status_code == 200
        payload = create_response.json()
        assert payload["encrypted"] is False
        assert payload["secrets_included"] is False
        assert "database" in payload["included_modules"]
        assert "exports" in payload["excluded_modules"]
        assert payload["download_url"].endswith("/download")

        list_response = await client.get("/api/system/backups", headers=headers)
        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["filename"] == payload["filename"]

        download_response = await client.get(payload["download_url"], headers=headers)
        assert download_response.status_code == 200
        assert "attachment" in download_response.headers["content-disposition"]

    archive_path = backup_service_fixture.backup_dir / payload["filename"]
    manifest_sidecar = archive_path.with_suffix(archive_path.suffix + ops.BACKUP_MANIFEST_SUFFIX)
    assert archive_path.exists()
    assert manifest_sidecar.exists()

    manifest = json.loads(manifest_sidecar.read_text(encoding="utf-8"))
    assert manifest["encrypted"] is False
    assert manifest["secrets_included"] is False
    assert "exports" in manifest["excluded_modules"]
    assert "audio" in manifest["included_modules"]

    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
        assert "manifest.json" in names
        assert ".env" not in names
        assert "data/translated/chapter.txt" in names
        assert "data/audio/chapter.mp3" in names
        assert "data/exports/book.txt" not in names


@pytest.mark.asyncio
async def test_encrypted_secrets_backup_requires_passphrase(backup_service_fixture: BackupService) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/system/backups",
            json={"include_secrets": True},
            headers=headers,
        )

    assert response.status_code == 400
    assert "passphrase" in response.json()["detail"].lower()


def test_backup_service_blocks_path_traversal(backup_service_fixture: BackupService) -> None:
    with pytest.raises(ValueError, match="Invalid backup filename"):
        backup_service_fixture.resolve_download_path("../etc/passwd")


@pytest.mark.asyncio
async def test_backup_list_is_sidecar_only_and_gates_download_urls(
    backup_service_fixture: BackupService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = backup_service_fixture.backup_dir
    ready = backup_dir / "novel-pipeline-backup-20260712-100000.tar.gz"
    ready.write_bytes(b"artifact")
    ops.backup_sidecar_path(ready).write_text(
        json.dumps(
            {
                "backup_format_version": 2,
                "created_at": "2026-07-12T10:00:00",
                "encrypted": False,
                "secrets_included": False,
                "included_modules": ["database"],
                "excluded_modules": ["secrets"],
                "file_count": 1,
                "total_size_bytes": 8,
                "checksums": [{"path": "data/private.txt", "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    missing = backup_dir / "novel-pipeline-backup-20260712-090000.tar.gz"
    missing.write_bytes(b"archive-content-must-not-be-opened")
    malformed = backup_dir / "novel-pipeline-backup-20260712-080000.tar.gz"
    malformed.write_bytes(b"artifact")
    ops.backup_sidecar_path(malformed).write_text("{", encoding="utf-8")
    monkeypatch.setattr(ops.tarfile, "open", lambda *args, **kwargs: pytest.fail("API list opened archive"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/system/backups", headers=headers)

    assert response.status_code == 200
    payload = {item["filename"]: item for item in response.json()["items"]}
    assert payload[ready.name]["metadata_status"] == "READY"
    assert payload[ready.name]["download_url"].endswith("/download")
    assert payload[missing.name]["metadata_status"] == "METADATA_MISSING"
    assert payload[missing.name]["download_url"] == ""
    assert payload[malformed.name]["metadata_status"] == "METADATA_INVALID"
    assert payload[malformed.name]["download_url"] == ""
    assert "checksums" not in response.text
    assert "private.txt" not in response.text
    assert not re.search(r"/home/|/mnt/|[A-Za-z]:\\\\", response.text)


@pytest.mark.asyncio
async def test_backup_download_route_rejects_path_traversal(
    backup_service_fixture: BackupService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/system/backups/..%2Fetc%2Fpasswd/download", headers=headers)

    assert response.status_code in {400, 404}
