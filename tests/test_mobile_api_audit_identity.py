from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _events(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT event_type, actor_user_id, owner_user_id, details_json, job_id
            FROM operational_events
            ORDER BY id
            """
        ).fetchall()
    events: list[dict] = []
    for row in rows:
        event = dict(row)
        event["details"] = json.loads(event.pop("details_json") or "{}")
        events.append(event)
    return events


def _build_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api import main as main_mod
    from app.mobile_api.config import mobile_settings

    data_dir = tmp_path / "data"
    monkeypatch.setattr(app_config.settings, "data_dir", data_dir)
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", data_dir)
    monkeypatch.setattr(mobile_settings, "admin_username", "audit_operator")
    monkeypatch.setattr(mobile_settings, "admin_password", "audit-password")
    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "audit_operator")
    app = main_mod.create_app()
    return app, data_dir / "pipeline.db"


def test_identity_metadata_columns_exist_after_init(temp_db_path: Path) -> None:
    from app.database.db import init_db

    init_db(temp_db_path)

    assert "user_id" in _columns(temp_db_path, "auth_sessions")
    assert {"actor_user_id", "owner_user_id"}.issubset(
        _columns(temp_db_path, "operational_events")
    )


def test_legacy_session_without_user_id_remains_valid(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import init_db
    from app.mobile_api import session_auth as session_auth_mod
    from app.mobile_api.security import create_access_token

    init_db(temp_db_path)
    now = "2026-06-30T00:00:00+00:00"
    expires = "2099-01-01T00:00:00+00:00"
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
            (
                session_id, username, refresh_token_hash, refresh_family_id,
                created_at, expires_at, revoked_at, last_seen_at,
                client_host, user_agent, request_id, reuse_detected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '', ?, '', '', '', '')
            """,
            ("legacy-session", "legacy_operator", "legacy-refresh-hash", "legacy-family", now, expires, now),
        )
        conn.commit()

    monkeypatch.setattr(session_auth_mod, "get_db_path", lambda: temp_db_path)
    token = create_access_token(
        {"sub": "legacy_operator"},
        session_id="legacy-session",
        token_id="legacy-token",
    )

    user = session_auth_mod.validate_access_token(token, touch=False)

    assert user["username"] == "legacy_operator"
    assert user["session_id"] == "legacy-session"
    assert user.get("user_id", "") == ""


@pytest.mark.asyncio
async def test_login_session_and_auth_events_store_seeded_operator_user_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db_path = _build_app(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "audit_operator", "password": "audit-password"},
        )

    assert login.status_code == 200
    token_response = login.json()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT * FROM users WHERE username = ?", ("audit_operator",)).fetchone()
        session = conn.execute("SELECT * FROM auth_sessions").fetchone()

    assert user is not None
    assert session["username"] == "audit_operator"
    assert session["user_id"] == user["id"]
    assert token_response["refresh_token"] not in session["refresh_token_hash"]

    events = _events(db_path)
    session_create = next(event for event in events if event["event_type"] == "session_create")
    login_success = next(event for event in events if event["event_type"] == "auth_login_success")
    assert session_create["actor_user_id"] == user["id"]
    assert session_create["owner_user_id"] == user["id"]
    assert login_success["actor_user_id"] == user["id"]
    assert login_success["owner_user_id"] == user["id"]
    serialized = str(events)
    assert "audit-password" not in serialized
    assert token_response["access_token"] not in serialized
    assert token_response["refresh_token"] not in serialized


@pytest.mark.asyncio
async def test_authenticated_provider_job_and_logout_events_store_actor_user_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.routers import jobs as jobs_router
    from app.mobile_api.routers import providers as providers_router
    from app.mobile_api.services.provider_service import ProviderService

    class RecordingJobService:
        def start_translate_job(self, **kwargs) -> str:
            return "job-audit-actor"

    app, db_path = _build_app(tmp_path, monkeypatch)
    provider_service = object.__new__(ProviderService)
    provider_service.db_path = db_path
    provider_service.env_path = tmp_path / ".env"
    app.dependency_overrides[providers_router.get_provider_service] = lambda: provider_service
    app.dependency_overrides[jobs_router.get_job_service] = lambda: RecordingJobService()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "audit_operator", "password": "audit-password"},
            )
            access_token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}
            provider = await client.post(
                "/api/providers/gemini/key",
                json={"api_key": "new-provider-secret"},
                headers=headers,
            )
            job = await client.post(
                "/api/jobs/translate",
                json={
                    "book_id": 1,
                    "chapter_ids": [10],
                    "params": {"preset_id": "balanced"},
                },
                headers=headers,
            )
            logout = await client.post("/api/auth/logout", headers=headers)
    finally:
        app.dependency_overrides.pop(providers_router.get_provider_service, None)
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert provider.status_code == 200
    assert job.status_code == 200
    assert logout.status_code == 200
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT * FROM users WHERE username = ?", ("audit_operator",)).fetchone()

    assert user is not None
    events = _events(db_path)
    by_type = {event["event_type"]: event for event in events}
    for event_type in ("provider_key_update", "job_start", "session_revoke", "auth_logout"):
        assert by_type[event_type]["actor_user_id"] == user["id"]
        assert by_type[event_type]["owner_user_id"] == user["id"]

    assert by_type["job_start"]["job_id"] == "job-audit-actor"
    serialized = str(events)
    assert "new-provider-secret" not in serialized
    assert access_token not in serialized
    assert "audit-password" not in serialized
