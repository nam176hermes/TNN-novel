from __future__ import annotations

import importlib
import os
import sqlite3
from pathlib import Path

import httpx
import pytest


def test_session_auth_uses_db_auth_repository_exports() -> None:
    from app.database import auth_repository
    from app.mobile_api import session_auth

    assert session_auth.get_auth_session is auth_repository.get_auth_session
    assert session_auth.touch_auth_session is auth_repository.touch_auth_session
    assert session_auth.auth_session_is_active is auth_repository.auth_session_is_active


def _build_app_with_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api import main as main_mod

    data_dir = tmp_path / "data"
    monkeypatch.setattr(app_config.settings, "data_dir", data_dir)
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", data_dir)
    return main_mod.create_app(), data_dir / "pipeline.db"


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    from app.mobile_api.config import mobile_settings

    response = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert response.status_code == 200
    return response.json()


def _csrf_header(client: httpx.AsyncClient) -> dict[str, str]:
    from app.mobile_api.config import mobile_settings

    token = client.cookies.get(mobile_settings.csrf_cookie_name)
    assert token
    return {mobile_settings.csrf_header_name: token}


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_for_url(url: str):
    from urllib.parse import urlparse

    from starlette.requests import Request

    parsed = urlparse(url)
    host = parsed.netloc or "test"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": parsed.scheme or "http",
            "path": parsed.path or "/",
            "root_path": "",
            "query_string": parsed.query.encode("utf-8"),
            "headers": [(b"host", host.encode("ascii"))],
            "client": ("127.0.0.1", 43210),
            "server": (parsed.hostname or "test", port),
        }
    )


@pytest.mark.asyncio
async def test_mobile_api_protects_books_by_default() -> None:
    from app.mobile_api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        ready = await client.get("/api/ready")
        unauthenticated_books = await client.get("/api/books")

    assert health.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] is True
    assert unauthenticated_books.status_code == 401


@pytest.mark.asyncio
async def test_public_ready_sanitizes_internal_diagnostics(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import Response

    from app.database.db import init_db
    from app.mobile_api.routers import health as health_router

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    monkeypatch.setattr(health_router.mobile_settings, "public_deploy", True)
    monkeypatch.setattr(health_router.mobile_settings, "secret_key", "a" * 40)
    monkeypatch.setattr(health_router.mobile_settings, "admin_username", "operator")
    monkeypatch.setattr(health_router.mobile_settings, "admin_password", "strong-public-password")
    monkeypatch.setattr(health_router.mobile_settings, "cors_origins", ["https://novel.example.com"])
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: db_path)

    response = Response()
    ready = await health_router.readiness_check(_request_for_url("https://novel.example.com/api/ready"), response)
    payload = ready.model_dump()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["checks"]["database"] is True
    assert payload["checks"]["storage"] is True
    assert payload["checks"]["jobs"] is True
    assert payload["checks"]["public_deploy"] is True
    serialized = str(payload)
    assert str(tmp_path) not in serialized
    assert "pipeline.db" not in serialized
    assert "/data" not in serialized


@pytest.mark.asyncio
async def test_local_ready_keeps_useful_internal_diagnostics(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import Response

    from app.database.db import init_db
    from app.mobile_api.routers import health as health_router

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    monkeypatch.setattr(health_router.mobile_settings, "public_deploy", False)
    monkeypatch.setattr(health_router, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(health_router, "get_db_path", lambda: db_path)

    ready = await health_router.readiness_check(_request_for_url("http://test/api/ready"), Response())
    payload = ready.model_dump()

    assert payload["status"] == "ok"
    assert payload["details"]["data_dir"] == str(data_dir)
    assert payload["details"]["database"] == str(db_path)


@pytest.mark.asyncio
async def test_mobile_api_allows_authenticated_books_request() -> None:
    from app.mobile_api.config import mobile_settings
    from app.mobile_api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={
                "username": mobile_settings.admin_username,
                "password": mobile_settings.admin_password,
            },
        )
        token = login.json()["access_token"]
        books = await client.get("/api/books", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 200
    assert books.status_code == 200


@pytest.mark.asyncio
async def test_book_and_chapter_metadata_do_not_expose_internal_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import add_book, add_chapter, init_db, update_book, update_chapter_paths

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)
    init_db(db_path)
    cover_path = tmp_path / "private" / "cover.jpg"
    raw_path = tmp_path / "private" / "raw.txt"
    translated_path = tmp_path / "private" / "translated.txt"
    content_path = tmp_path / "private" / "chapter.html"
    audio_path = tmp_path / "private" / "chapter.mp3"
    book_id = add_book(db_path, "Path Safety")
    update_book(db_path, book_id, cover_path=str(cover_path))
    chapter_id = add_chapter(db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(
        db_path,
        chapter_id,
        cleaned_text_path=raw_path,
        translated_text_path=translated_path,
        content_html_path=content_path,
        audio_path=audio_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client)
        headers = _auth_header(token["access_token"])
        book = await client.get(f"/api/books/{book_id}", headers=headers)
        chapters = await client.get(f"/api/books/{book_id}/chapters", headers=headers)

    assert book.status_code == 200
    assert chapters.status_code == 200
    serialized = book.text + chapters.text
    assert str(tmp_path) not in serialized
    assert book.json()["cover_path"] == ""
    chapter = chapters.json()[0]
    assert chapter["raw_text_path"] == "available"
    assert chapter["cleaned_text_path"] == "available"
    assert chapter["translated_text_path"] == "available"
    assert chapter["content_html_path"] == "available"
    assert chapter["audio_path"] == "available"


@pytest.mark.asyncio
async def test_mobile_api_refresh_uses_httponly_cookie_and_csrf_header() -> None:
    from app.mobile_api.config import mobile_settings
    from app.mobile_api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={
                "username": mobile_settings.admin_username,
                "password": mobile_settings.admin_password,
            },
        )
        refresh = await client.post(
            "/api/auth/refresh",
            headers=_csrf_header(client),
        )

    assert login.status_code == 200
    assert "refresh_token" not in login.json()
    assert refresh.status_code == 200
    assert "access_token" in refresh.json()
    assert "refresh_token" not in refresh.json()
    set_cookie = login.headers.get_list("set-cookie")
    assert any("novel_refresh_session=" in value and "HttpOnly" in value for value in set_cookie)


@pytest.mark.asyncio
async def test_refresh_rejects_missing_or_mismatched_csrf_without_rotating_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client)
        missing = await client.post("/api/auth/refresh")
        mismatched = await client.post(
            "/api/auth/refresh",
            headers={"X-CSRF-Token": "not-the-cookie-value"},
        )

    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert missing.json()["detail"] == {
        "code": "csrf_rejected",
        "message": "Request verification failed",
    }
    with sqlite3.connect(db_path) as conn:
        session = conn.execute(
            "SELECT revoked_at, reuse_detected_at FROM auth_sessions"
        ).fetchone()
    assert session == ("", "")


@pytest.mark.asyncio
async def test_login_cookie_flags_match_local_and_public_requests(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.config import mobile_settings

    app, _ = _build_app_with_data_dir(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    credentials = {
        "username": mobile_settings.admin_username,
        "password": mobile_settings.admin_password,
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as local_client:
        local = await local_client.post("/api/auth/login", json=credentials)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://novel.example.com",
    ) as public_client:
        public = await public_client.post("/api/auth/login", json=credentials)

    local_refresh = next(
        value for value in local.headers.get_list("set-cookie") if "novel_refresh_session=" in value
    )
    public_refresh = next(
        value for value in public.headers.get_list("set-cookie") if "novel_refresh_session=" in value
    )
    assert "HttpOnly" in local_refresh and "SameSite=lax" in local_refresh
    assert "Secure" not in local_refresh
    assert "HttpOnly" in public_refresh and "SameSite=lax" in public_refresh
    assert "Secure" in public_refresh


@pytest.mark.asyncio
async def test_login_creates_server_side_session(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token_response = await _login(client)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, username, refresh_token_hash, revoked_at FROM auth_sessions"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["session_id"]
    assert rows[0]["username"]
    assert rows[0]["refresh_token_hash"]
    assert "refresh_token" not in token_response
    assert rows[0]["revoked_at"] in ("", None)


@pytest.mark.asyncio
async def test_protected_api_works_with_valid_server_side_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token_response = await _login(client)
        response = await client.get("/api/books", headers=_auth_header(token_response["access_token"]))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_current_server_side_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token_response = await _login(client)
        access_token = token_response["access_token"]
        logout = await client.post("/api/auth/logout", headers=_auth_header(access_token))
        after_logout = await client.get("/api/books", headers=_auth_header(access_token))

    assert logout.status_code == 200
    assert after_logout.status_code == 401
    with sqlite3.connect(db_path) as conn:
        revoked_at = conn.execute("SELECT revoked_at FROM auth_sessions").fetchone()[0]
    assert revoked_at


@pytest.mark.asyncio
async def test_unknown_server_side_session_is_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token_response = await _login(client)
        access_token = token_response["access_token"]
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM auth_sessions")
            conn.commit()
        response = await client.get("/api/books", headers=_auth_header(access_token))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_revokes_all_operator_sessions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _login(client)
        second = await _login(client)
        logout_all = await client.post("/api/auth/logout-all", headers=_auth_header(first["access_token"]))
        first_after = await client.get("/api/books", headers=_auth_header(first["access_token"]))
        second_after = await client.get("/api/books", headers=_auth_header(second["access_token"]))

    assert logout_all.status_code == 200
    assert first_after.status_code == 401
    assert second_after.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_rejects_old_refresh_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token_response = await _login(client)
        from app.mobile_api.config import mobile_settings
        old_refresh = client.cookies.get(mobile_settings.refresh_cookie_name)
        assert old_refresh
        first_refresh = await client.post("/api/auth/refresh", headers=_csrf_header(client))
        new_refresh_token = client.cookies.get(mobile_settings.refresh_cookie_name)
        assert new_refresh_token and new_refresh_token != old_refresh
        new_refresh = await client.post("/api/auth/refresh", headers=_csrf_header(client))
        client.cookies.set(mobile_settings.refresh_cookie_name, old_refresh, path="/api/auth")
        second_refresh = await client.post("/api/auth/refresh", headers=_csrf_header(client))

    assert first_refresh.status_code == 200
    assert new_refresh.status_code == 200
    assert second_refresh.status_code == 401
    events = list_operational_events(db_path, limit=20, severities=())
    assert any(event["event_type"] == "session_refresh_success" for event in events)
    assert any(event["event_type"] == "session_refresh_reuse" for event in events)


@pytest.mark.asyncio
async def test_persistent_login_throttle_survives_limiter_recreation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events
    from app.mobile_api.routers import auth as auth_router

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(auth_router.mobile_settings, "login_rate_limit_attempts", 2)
    monkeypatch.setattr(auth_router.mobile_settings, "login_rate_limit_window_seconds", 300)
    auth_router.login_rate_limiter = auth_router.LoginRateLimiter(2, 300)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):
            response = await client.post(
                "/api/auth/login",
                json={"username": "persistent-lockout", "password": "wrong-password"},
            )
            assert response.status_code == 401

        auth_router.login_rate_limiter = auth_router.LoginRateLimiter(2, 300)
        blocked = await client.post(
            "/api/auth/login",
            json={"username": "persistent-lockout", "password": "wrong-password"},
        )

    assert blocked.status_code == 429
    events = list_operational_events(db_path, limit=10, severities=())
    assert any(event["event_type"] == "auth_login_lockout" for event in events)


@pytest.mark.asyncio
async def test_auth_audit_events_do_not_store_raw_tokens_or_passwords(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)
    password_marker = "wrong-password-secret"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/auth/login",
            json={"username": "operator", "password": password_marker},
        )
        token_response = await _login(client)
        refresh_response = await client.post(
            "/api/auth/refresh",
            headers=_csrf_header(client),
        )
        await client.post(
            "/api/auth/logout",
            headers=_auth_header(refresh_response.json()["access_token"]),
        )

    events = list_operational_events(db_path, limit=30, severities=())
    serialized = str(events)
    assert any(event["event_type"] == "session_create" for event in events)
    assert any(event["event_type"] == "session_refresh_success" for event in events)
    assert any(event["event_type"] == "auth_logout" for event in events)
    assert token_response["access_token"] not in serialized
    assert "refresh_token" not in token_response
    assert "refresh_token" not in refresh_response.json()
    assert password_marker not in serialized


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_repeated_bad_passwords(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mobile_api.routers import auth as auth_router

    app, _ = _build_app_with_data_dir(tmp_path, monkeypatch)
    auth_router.login_rate_limiter = auth_router.LoginRateLimiter(5, 300)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = []
        for _ in range(6):
            responses.append(
                await client.post(
                    "/api/auth/login",
                    json={"username": "rate-limit-user", "password": "wrong-password"},
                )
            )

    assert [response.status_code for response in responses[:5]] == [401, 401, 401, 401, 401]
    assert responses[5].status_code == 429
    assert responses[5].json()["detail"] == "Too many failed login attempts"


@pytest.mark.asyncio
async def test_login_failure_records_sanitized_operational_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "wrong-password-secret"},
        )

    assert response.status_code == 401
    events = list_operational_events(db_path, limit=10, severities=())
    login_failure = next(event for event in events if event["event_type"] == "auth_login_failure")
    assert login_failure["severity"] == "warning"
    assert login_failure["details"]["username"] == "operator"
    assert "wrong-password-secret" not in str(login_failure)


@pytest.mark.asyncio
async def test_logout_records_operational_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events
    from app.mobile_api.config import mobile_settings

    app, db_path = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={
                "username": mobile_settings.admin_username,
                "password": mobile_settings.admin_password,
            },
        )
        response = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )

    assert response.status_code == 200
    events = list_operational_events(db_path, limit=10, severities=())
    assert any(event["event_type"] == "auth_logout" for event in events)


def test_mobile_api_cors_origins_are_not_wildcard() -> None:
    from app.mobile_api import main as main_mod

    middleware_options = [
        middleware.kwargs
        for middleware in main_mod.app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    ]

    assert middleware_options
    assert "*" not in middleware_options[0]["allow_origins"]


def test_public_deploy_safety_gate_rejects_unsafe_defaults() -> None:
    from app.mobile_api.config import MobileAPISettings, validate_public_deploy_settings

    settings = MobileAPISettings(
        public_deploy=True,
        secret_key="dev-secret-change-in-production",
        admin_username="admin",
        admin_password="change_me",
        disable_auth=True,
        cors_origins=["*", "http://localhost"],
    )

    errors = validate_public_deploy_settings(settings)

    assert any("MOBILE_API_SECRET" in error for error in errors)
    assert any("MOBILE_API_ADMIN_USERNAME" in error for error in errors)
    assert any("MOBILE_API_ADMIN_PASSWORD" in error for error in errors)
    assert any("MOBILE_API_CORS_ORIGINS" in error for error in errors)
    assert any("MOBILE_API_DISABLE_AUTH" in error for error in errors)


def test_external_bind_requires_public_deploy_safety_gate() -> None:
    from app.mobile_api.config import MobileAPISettings, validate_public_deploy_settings

    errors = validate_public_deploy_settings(
        MobileAPISettings(
            host="0.0.0.0",
            public_deploy=False,
            secret_key="dev-secret-change-in-production",
            admin_username="admin",
            admin_password="change_me",
        )
    )

    assert any("PUBLIC_DEPLOY=1" in error for error in errors)
    assert any("MOBILE_API_SECRET" in error for error in errors)
    assert any("MOBILE_API_ADMIN_USERNAME" in error for error in errors)
    assert any("MOBILE_API_ADMIN_PASSWORD" in error for error in errors)


def test_public_deploy_auth_bypass_requires_explicit_override() -> None:
    from app.mobile_api.config import MobileAPISettings, auth_bypass_enabled, validate_public_deploy_settings

    unsafe = MobileAPISettings(
        public_deploy=True,
        secret_key="0123456789abcdef0123456789abcdef",
        admin_username="private_operator",
        admin_password="correct horse battery staple 2026",
        cors_origins=["https://novel.example.com"],
        disable_auth=True,
        allow_public_auth_bypass=False,
    )
    explicit = unsafe.model_copy(update={"allow_public_auth_bypass": True})

    assert any("MOBILE_API_DISABLE_AUTH" in error for error in validate_public_deploy_settings(unsafe))
    assert validate_public_deploy_settings(explicit) == []
    assert auth_bypass_enabled(explicit) is True


def test_public_deploy_safety_gate_accepts_strong_single_operator_config() -> None:
    from app.mobile_api.config import (
        MobileAPISettings,
        assert_public_deploy_safe,
        validate_public_deploy_settings,
    )

    settings = MobileAPISettings(
        public_deploy=True,
        secret_key="0123456789abcdef0123456789abcdef",
        admin_username="private_operator",
        admin_password="correct horse battery staple 2026",
        cors_origins=["https://novel.example.com"],
    )

    assert validate_public_deploy_settings(settings) == []
    assert_public_deploy_safe(settings)


def test_public_deploy_create_app_refuses_unsafe_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mobile_api import main as main_mod
    from app.mobile_api.config import MobileAPISettings

    unsafe = MobileAPISettings(
        public_deploy=True,
        secret_key="change-this-jwt-secret",
        admin_username="admin",
        admin_password="change_me",
        cors_origins=["https://novel.example.com"],
    )
    monkeypatch.setattr(main_mod, "mobile_settings", unsafe)

    with pytest.raises(RuntimeError, match="Unsafe PUBLIC_DEPLOY configuration"):
        main_mod.create_app()


def test_public_deploy_create_app_accepts_safe_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mobile_api import main as main_mod
    from app.mobile_api.config import MobileAPISettings

    safe = MobileAPISettings(
        public_deploy=True,
        secret_key="0123456789abcdef0123456789abcdef",
        admin_username="private_operator",
        admin_password="correct horse battery staple 2026",
        cors_origins=["https://novel.example.com"],
    )
    monkeypatch.setattr(main_mod, "mobile_settings", safe)
    monkeypatch.setattr(main_mod, "_prepare_runtime", lambda: None)

    app = main_mod.create_app()

    assert app.docs_url is None
    assert app.openapi_url is None


def test_mobile_api_settings_load_project_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MOBILE_API_SECRET=env-secret",
                "MOBILE_API_ADMIN_USERNAME=env-admin",
                "MOBILE_API_ADMIN_PASSWORD=env-password",
                "MOBILE_API_PORT=7999",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "MOBILE_API_SECRET",
        "MOBILE_API_ADMIN_USERNAME",
        "MOBILE_API_ADMIN_PASSWORD",
        "MOBILE_API_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NOVEL_PIPELINE_IGNORE_DOTENV", "0")

    import app.config as config_mod

    old_root = config_mod.PROJECT_ROOT
    config_mod.PROJECT_ROOT = tmp_path
    try:
        from app.mobile_api import config as mobile_config_mod

        for key in (
            "MOBILE_API_SECRET",
            "MOBILE_API_ADMIN_USERNAME",
            "MOBILE_API_ADMIN_PASSWORD",
            "MOBILE_API_PORT",
        ):
            os.environ.pop(key, None)
        reloaded = importlib.reload(mobile_config_mod)

        assert reloaded.mobile_settings.secret_key == "env-secret"
        assert reloaded.mobile_settings.admin_username == "env-admin"
        assert reloaded.mobile_settings.admin_password == "env-password"
        assert reloaded.mobile_settings.port == 7999
    finally:
        config_mod.PROJECT_ROOT = old_root
        for key in (
            "MOBILE_API_SECRET",
            "MOBILE_API_ADMIN_USERNAME",
            "MOBILE_API_ADMIN_PASSWORD",
            "MOBILE_API_PORT",
        ):
            os.environ.pop(key, None)
        monkeypatch.setenv("NOVEL_PIPELINE_IGNORE_DOTENV", "1")
        importlib.reload(mobile_config_mod)


@pytest.mark.asyncio
async def test_remote_api_key_does_not_block_bearer_authenticated_dashboard() -> None:
    old_key = os.environ.get("REMOTE_API_KEY")
    os.environ["REMOTE_API_KEY"] = "secret-test-key"

    try:
        from app.mobile_api.config import mobile_settings
        from app.mobile_api import main as main_mod

        reloaded = importlib.reload(main_mod)
        transport = httpx.ASGITransport(app=reloaded.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/auth/login",
                json={
                    "username": mobile_settings.admin_username,
                    "password": mobile_settings.admin_password,
                },
            )
            token = login.json()["access_token"]
            bearer_only = await client.get(
                "/api/books",
                headers={"Authorization": f"Bearer {token}"},
            )
            api_key_only = await client.get(
                "/api/books",
                headers={"X-API-Key": "secret-test-key"},
            )

        assert login.status_code == 200
        assert bearer_only.status_code == 200
        assert api_key_only.status_code == 401
    finally:
        if old_key is None:
            os.environ.pop("REMOTE_API_KEY", None)
        else:
            os.environ["REMOTE_API_KEY"] = old_key

        from app.mobile_api import main as main_mod

        importlib.reload(main_mod)
