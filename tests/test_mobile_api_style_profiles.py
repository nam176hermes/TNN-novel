from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import init_db, list_style_profiles
from app.mobile_api import dependencies
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app


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
def style_profile_db(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_db(temp_db_path)
    monkeypatch.setattr(dependencies, "get_db_path", lambda: temp_db_path)
    return temp_db_path


@pytest.mark.asyncio
async def test_style_profiles_api_lists_seeded_profiles_and_default(style_profile_db: Path) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/style-profiles", headers=headers)

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert [profile["id"] for profile in profiles] == [
        "tien_hiep",
        "huyen_huyen",
        "kiem_hiep",
        "he_thong",
    ]
    assert next(profile for profile in profiles if profile["is_default"] == 1)["id"] == "tien_hiep"
    assert "sư huynh" in profiles[0]["pronoun_rules"]
    assert "level up" in profiles[0]["banned_modern_terms"]


@pytest.mark.asyncio
async def test_style_profiles_api_sets_single_default(style_profile_db: Path) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            "/api/style-profiles/default",
            json={"style_profile_id": "kiem_hiep"},
            headers=headers,
        )
        default_response = await client.get("/api/style-profiles/default", headers=headers)

    assert response.status_code == 200
    assert response.json()["default"]["id"] == "kiem_hiep"
    assert default_response.status_code == 200
    assert default_response.json()["profile"]["id"] == "kiem_hiep"
    assert sum(profile["is_default"] for profile in list_style_profiles(style_profile_db)) == 1


@pytest.mark.asyncio
async def test_style_profiles_api_rejects_missing_default(style_profile_db: Path) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            "/api/style-profiles/default",
            json={"style_profile_id": "missing"},
            headers=headers,
        )

    assert response.status_code == 404
