from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest


def test_auth_router_uses_db_auth_repository_exports() -> None:
    from app.database import auth_repository
    from app.mobile_api.routers import auth

    assert auth.create_auth_session is auth_repository.create_auth_session
    assert auth.rotate_auth_session_refresh is auth_repository.rotate_auth_session_refresh
    assert auth.record_auth_login_failure is auth_repository.record_auth_login_failure


def _fetch_users(db_path: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM users ORDER BY created_at, id").fetchall()


def test_init_db_creates_minimal_users_table(temp_db_path: Path) -> None:
    from app.database.db import init_db

    init_db(temp_db_path)

    with sqlite3.connect(temp_db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"]: row
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }

    assert set(columns) == {
        "id",
        "username",
        "display_name",
        "source",
        "created_at",
        "updated_at",
        "disabled_at",
    }
    assert columns["id"]["type"].upper() == "TEXT"
    assert columns["username"]["notnull"] == 1
    assert columns["source"]["notnull"] == 1
    assert not any("password" in column_name for column_name in columns)


def test_env_operator_is_seeded_without_storing_password(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import init_db

    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "private_operator")
    monkeypatch.setenv("MOBILE_API_ADMIN_PASSWORD", "not-written-to-users-table")

    init_db(temp_db_path)

    users = _fetch_users(temp_db_path)
    assert len(users) == 1
    assert users[0]["id"]
    assert users[0]["username"] == "private_operator"
    assert users[0]["display_name"] == ""
    assert users[0]["source"] == "env"
    assert users[0]["created_at"]
    assert users[0]["updated_at"]
    assert users[0]["disabled_at"] == ""
    assert "not-written-to-users-table" not in str(dict(users[0]))


def test_operator_seed_is_idempotent_and_stable_across_reinitialization(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import get_or_seed_operator_user, init_db

    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "stable_operator")

    init_db(temp_db_path)
    first = get_or_seed_operator_user(temp_db_path, "stable_operator")
    init_db(temp_db_path)
    second = get_or_seed_operator_user(temp_db_path, "stable_operator")

    users = _fetch_users(temp_db_path)
    assert len(users) == 1
    assert first["id"] == second["id"] == users[0]["id"]
    assert users[0]["username"] == "stable_operator"


def test_operator_seed_preserves_id_when_env_username_changes(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import get_or_seed_operator_user, init_db

    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "old_operator")
    init_db(temp_db_path)
    original = get_or_seed_operator_user(temp_db_path, "old_operator")

    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "new_operator")
    init_db(temp_db_path)
    renamed = get_or_seed_operator_user(temp_db_path, "new_operator")

    users = _fetch_users(temp_db_path)
    assert len(users) == 1
    assert renamed["id"] == original["id"]
    assert users[0]["id"] == original["id"]
    assert users[0]["username"] == "new_operator"


@pytest.mark.asyncio
async def test_startup_seeds_operator_and_current_auth_flow_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api import main as main_mod
    from app.mobile_api.config import mobile_settings

    data_dir = tmp_path / "data"
    monkeypatch.setattr(app_config.settings, "data_dir", data_dir)
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", data_dir)
    monkeypatch.setattr(mobile_settings, "admin_username", "startup_operator")
    monkeypatch.setattr(mobile_settings, "admin_password", "startup-password")
    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "startup_operator")

    app = main_mod.create_app()
    db_path = data_dir / "pipeline.db"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "startup_operator", "password": "startup-password"},
        )
        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )

    users = _fetch_users(db_path)
    assert login.status_code == 200
    assert me.status_code == 200
    assert me.json()["username"] == "startup_operator"
    assert len(users) == 1
    assert users[0]["username"] == "startup_operator"
