#!/usr/bin/env python3
"""
Test script for mobile API health and auth endpoints.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import httpx
import pytest
from app.config import settings
from app.database.db import init_db
from app.mobile_api.config import mobile_settings

pytestmark = pytest.mark.asyncio


def make_client() -> httpx.AsyncClient:
    from app.mobile_api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    for subdir in ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    init_db(tmp_path / "pipeline.db")


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_health_endpoints():
    """Test health endpoints."""
    async with make_client() as client:
        # Test /health
        resp = await client.get("/api/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data["status"] == "ok", f"Expected status 'ok', got {data['status']}"
        assert data["version"] == mobile_settings.version
        print("✓ /health endpoint works")

        # Test /version
        resp = await client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == mobile_settings.version
        print("✓ /version endpoint works")

        login = await client.post(
            "/api/auth/login",
            json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
        )
        token = login.json()["access_token"]

        # Test /system/status (protected)
        resp = await client.get(
            "/api/system/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "db_size_bytes" in data
        assert "ollama_host" in data
        print("✓ /system/status endpoint works")


async def test_auth_endpoints():
    """Test auth endpoints."""
    async with make_client() as client:
        # Test login with default credentials
        resp = await client.post(
            "/api/auth/login",
            json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        print("✓ /auth/login works")

        # Test /me with token
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == mobile_settings.admin_username
        print("✓ /auth/me works")

        # Test /auth/refresh
        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        print("✓ /auth/refresh works")

        # Test logout (should succeed)
        resp = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 200
        print("✓ /auth/logout works")

        # Test invalid login
        resp = await client.post(
            "/api/auth/login",
            json={"username": "wrong", "password": "wrong"},
        )
        assert resp.status_code == 401
        print("✓ Invalid login correctly rejected")


async def test_cors_preflight_for_protected_routes_does_not_require_bearer_token():
    """Browser preflight requests must pass before the bearer-protected request."""
    async with make_client() as client:
        resp = await client.options(
            "/api/books",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
        assert "authorization" in resp.headers["access-control-allow-headers"].lower()


async def test_reader_sync_reports_client_won_when_progress_diverged_since_last_sync():
    async with make_client() as client:
        headers = await auth_headers(client)
        imported = await client.post(
            "/api/import/paste",
            headers=headers,
            json={
                "title": "Sync Conflict Book",
                "chapter_number": 1,
                "chapter_title": "Nhập môn",
                "text": "少年站在山门前。",
            },
        )
        assert imported.status_code == 200, imported.text
        book_id = imported.json()["book_id"]
        chapter_id = imported.json()["chapter_id"]
        anchor = {
            "version": 1,
            "text": "Thiếu niên đứng trước sơn môn.",
            "offset": 12,
            "prefix": "Nhập môn",
            "suffix": "Gió núi",
        }

        server_progress = await client.patch(
            f"/api/books/{book_id}/reader/progress",
            headers=headers,
            json={
                "chapter_id": chapter_id,
                "mode": "scroll",
                "percent": 20,
                "paragraph_index": 1,
                "char_offset": 3,
                "absolute_char_offset": 30,
                "page_index": 0,
            },
        )
        assert server_progress.status_code == 200, server_progress.text

        sync = await client.post(
            f"/api/books/{book_id}/reader/sync",
            headers=headers,
            json={
                "device_id": "phone",
                "last_sync_at": "1970-01-01T00:00:00+00:00",
                "progress": {
                    "chapter_id": chapter_id,
                    "mode": "scroll",
                    "percent": 80,
                    "paragraph_index": 7,
                    "char_offset": 9,
                    "absolute_char_offset": 190,
                    "page_index": 0,
                    "anchor": anchor,
                    "updated_at": "2999-01-01T00:00:00+00:00",
                },
                "annotations": [],
            },
        )

        assert sync.status_code == 200, sync.text
        data = sync.json()
        assert data["progress"]["percent"] == 80
        assert data["progress"]["anchor"] == anchor
        assert data["conflicts"] == [
            {
                "entity": "progress",
                "id": None,
                "client_id": "phone",
                "resolution": "client_won",
                "reason": "diverged_since_last_sync",
            }
        ]


async def test_reader_sync_reports_client_won_when_annotation_diverged_since_last_sync():
    async with make_client() as client:
        headers = await auth_headers(client)
        imported = await client.post(
            "/api/import/paste",
            headers=headers,
            json={
                "title": "Annotation Sync Conflict Book",
                "chapter_number": 1,
                "chapter_title": "Nhập môn",
                "text": "少年站在山门前。",
            },
        )
        assert imported.status_code == 200, imported.text
        book_id = imported.json()["book_id"]
        chapter_id = imported.json()["chapter_id"]

        created = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/annotations",
            headers=headers,
            json={
                "kind": "note",
                "paragraph_index": 0,
                "char_start": 0,
                "char_end": 6,
                "selected_text": "Thiếu niên",
                "note": "Server note",
                "color": "yellow",
            },
        )
        assert created.status_code == 201, created.text
        annotation_id = created.json()["annotation"]["id"]

        sync = await client.post(
            f"/api/books/{book_id}/reader/sync",
            headers=headers,
            json={
                "device_id": "tablet",
                "last_sync_at": "1970-01-01T00:00:00+00:00",
                "progress": None,
                "annotations": [
                    {
                        "id": annotation_id,
                        "client_id": "offline-note-1",
                        "chapter_id": chapter_id,
                        "kind": "note",
                        "paragraph_index": 0,
                        "char_start": 0,
                        "char_end": 6,
                        "selected_text": "Thiếu niên",
                        "note": "Client note",
                        "color": "green",
                        "updated_at": "2999-01-01T00:00:00+00:00",
                    }
                ],
            },
        )

        assert sync.status_code == 200, sync.text
        data = sync.json()
        synced_annotation = next(annotation for annotation in data["annotations"] if annotation["id"] == annotation_id)
        assert synced_annotation["note"] == "Client note"
        assert synced_annotation["color"] == "green"
        assert len(data["conflicts"]) == 1
        conflict = data["conflicts"][0]
        assert {
            "entity": conflict["entity"],
            "id": conflict["id"],
            "client_id": conflict["client_id"],
            "resolution": conflict["resolution"],
            "reason": conflict["reason"],
        } == {
            "entity": "annotation",
            "id": annotation_id,
            "client_id": "offline-note-1",
            "resolution": "client_won",
            "reason": "diverged_since_last_sync",
        }
        assert conflict["server_annotation"]["note"] == "Server note"
        assert conflict["server_annotation"]["color"] == "yellow"
        assert conflict["client_annotation"]["note"] == "Client note"
        assert conflict["client_annotation"]["color"] == "green"


async def main():
    """Run all tests."""
    print("Testing mobile API endpoints...")
    await test_health_endpoints()
    await test_auth_endpoints()
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
