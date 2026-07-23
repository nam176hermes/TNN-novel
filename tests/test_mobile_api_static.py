from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import httpx
import pytest


def _build_app_with_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api import main as main_mod

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", tmp_path / "data")
    return main_mod.create_app()


async def _login(client: httpx.AsyncClient) -> str:
    from app.mobile_api.config import mobile_settings

    response = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


@pytest.mark.asyncio
async def test_private_cover_requires_authentication(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    cover_path = tmp_path / "data" / "covers" / "private.jpg"
    cover_path.write_bytes(b"cover-bytes")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/covers/private.jpg")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_disabled_allows_local_review_without_bearer_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_mod

    monkeypatch.setattr(main_mod.mobile_settings, "public_deploy", False)
    monkeypatch.setattr(main_mod.mobile_settings, "disable_auth", True)
    monkeypatch.setattr(main_mod.mobile_settings, "allow_public_auth_bypass", False)
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    cover_path = tmp_path / "data" / "covers" / "private.jpg"
    asset_path = tmp_path / "data" / "book_assets" / "42" / "sword.png"
    cover_path.write_bytes(b"cover-bytes")
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"asset-bytes")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/system/status")
        me = await client.get("/api/auth/me")
        cover = await client.get("/covers/private.jpg")
        asset = await client.get("/book-assets/42/sword.png")

    assert status.status_code == 200
    assert status.json()["asset_protection_enabled"] is False
    assert me.status_code == 200
    assert me.json()["username"] == main_mod.mobile_settings.admin_username
    assert cover.status_code == 200
    assert cover.content == b"cover-bytes"
    assert asset.status_code == 200
    assert asset.content == b"asset-bytes"


@pytest.mark.asyncio
async def test_authenticated_user_can_fetch_private_cover_and_book_asset(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    cover_path = tmp_path / "data" / "covers" / "private.jpg"
    asset_path = tmp_path / "data" / "book_assets" / "42" / "sword.png"
    cover_path.write_bytes(b"cover-bytes")
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"asset-bytes")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client)
        cover_via_cookie = await client.get("/covers/private.jpg")
        asset_via_bearer = await client.get("/book-assets/42/sword.png", headers={"Authorization": f"Bearer {token}"})

    assert cover_via_cookie.status_code == 200
    assert cover_via_cookie.content == b"cover-bytes"
    assert asset_via_bearer.status_code == 200
    assert asset_via_bearer.content == b"asset-bytes"


@pytest.mark.asyncio
async def test_private_asset_responses_are_not_cacheable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    cover_path = tmp_path / "data" / "covers" / "private.jpg"
    asset_path = tmp_path / "data" / "book_assets" / "42" / "sword.png"
    cover_path.write_bytes(b"cover-bytes")
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"asset-bytes")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client)
        cover = await client.get("/covers/private.jpg")
        asset = await client.get("/book-assets/42/sword.png", headers={"Authorization": f"Bearer {token}"})

    for response in (cover, asset):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_asset_cookie_is_rejected_after_logout(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.config import mobile_settings

    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    cover_path = tmp_path / "data" / "covers" / "private.jpg"
    cover_path.write_bytes(b"cover-bytes")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client)
        asset_cookie = client.cookies.get(mobile_settings.asset_cookie_name)
        before_logout = await client.get("/covers/private.jpg")
        logout = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        after_logout = await client.get(
            "/covers/private.jpg",
            headers={"Cookie": f"{mobile_settings.asset_cookie_name}={asset_cookie}"},
        )

    assert asset_cookie
    assert before_logout.status_code == 200
    assert logout.status_code == 200
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_export_download_response_is_not_cacheable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.routers import exports as exports_router

    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    export_path = tmp_path / "book.txt"
    export_path.write_text("translated", encoding="utf-8")

    class FakeExportService:
        def export_book(self, book_id: int, format: str) -> dict:
            assert book_id == 7
            assert format == "txt"
            return {
                "path": str(export_path),
                "media_type": "text/plain; charset=utf-8",
                "filename": "book.txt",
            }

    app.dependency_overrides[exports_router.get_export_service] = lambda: FakeExportService()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {await _login(client)}"}
            response = await client.get("/api/books/7/exports/txt/download", headers=headers)
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert response.status_code == 200
    assert response.text == "translated"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_public_host_blocks_docs_even_without_public_deploy_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)
    app = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://novel.example.com") as client:
        docs = await client.get("/docs")
        redoc = await client.get("/redoc")
        openapi = await client.get("/openapi.json")
        env_probe = await client.get("/.env")
        data_probe = await client.get("/data/pipeline.db")

    assert docs.status_code == 404
    assert redoc.status_code == 404
    assert openapi.status_code == 404
    assert env_probe.status_code == 404
    assert data_probe.status_code == 404


@pytest.mark.asyncio
async def test_public_host_readiness_fails_safe_and_hides_paths_when_public_deploy_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)
    app = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://novel.example.com") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["public_deploy"] is False
    assert data["details"]["public_deploy"] == "disabled"
    body = response.text
    assert str(tmp_path) not in body
    assert "/pipeline.db" not in body


@pytest.mark.asyncio
async def test_public_host_login_asset_cookie_is_secure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.config import mobile_settings

    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)
    app = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://novel.example.com") as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
        )

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie


@pytest.mark.asyncio
async def test_public_host_status_import_and_export_hide_local_paths(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.routers import exports as exports_router

    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    export_path = tmp_path / "book.txt"
    export_path.write_text("translated", encoding="utf-8")

    class FakeExportService:
        def export_book(self, book_id: int, format: str) -> dict:
            assert book_id == 7
            assert format == "txt"
            return {
                "book_id": book_id,
                "book_title": "Book",
                "format": format,
                "filename": "book.txt",
                "path": str(export_path),
                "media_type": "text/plain; charset=utf-8",
                "size_bytes": export_path.stat().st_size,
                "chapter_count": 1,
            }

    app.dependency_overrides[exports_router.get_export_service] = lambda: FakeExportService()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://novel.example.com") as client:
            token = await _login(client)
            headers = {"Authorization": f"Bearer {token}"}
            status = await client.get("/api/system/status", headers=headers)
            imported = await client.post(
                "/api/import/paste",
                json={
                    "title": "Audit Test",
                    "chapter_number": 1,
                    "chapter_title": "Chapter",
                    "text": "第一章\n测试内容。",
                },
                headers=headers,
            )
            exported = await client.post("/api/books/7/exports", json={"format": "txt"}, headers=headers)
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert status.status_code == 200
    status_data = status.json()
    assert "data_dir" not in status_data
    assert "database_path" not in status_data
    assert status_data["database_available"] is True
    assert status_data["data_directory_available"] is True
    assert status_data["storage_label"] == "Configured data storage"
    assert status_data["ollama_host"] == ""
    assert imported.status_code == 200
    assert imported.json()["path"] == ""
    assert exported.status_code == 200
    assert exported.json()["path"] == ""


@pytest.mark.asyncio
async def test_private_asset_path_traversal_is_denied(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app_with_data_dir(tmp_path, monkeypatch)
    (tmp_path / "data" / "covers" / "private.jpg").write_bytes(b"cover-bytes")
    (tmp_path / "data" / "secret.txt").write_text("secret", encoding="utf-8")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client)
        response = await client.get("/covers/%2e%2e/secret.txt")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_missing_private_asset_returns_404_for_authenticated_user(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app_with_data_dir(tmp_path, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client)
        response = await client.get("/book-assets/42/missing.png")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_deploy_disables_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_DEPLOY", "1")
    monkeypatch.setenv("MOBILE_API_SECRET", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("MOBILE_API_ADMIN_USERNAME", "private_operator")
    monkeypatch.setenv("MOBILE_API_ADMIN_PASSWORD", "correct horse battery staple 2026")
    monkeypatch.setenv("MOBILE_API_CORS_ORIGINS", "https://novel.example.com")

    from app.mobile_api import config as config_mod
    from app.mobile_api import main as main_mod

    importlib.reload(config_mod)
    reloaded = importlib.reload(main_mod)
    app = reloaded.create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        redoc = await client.get("/redoc")
        openapi = await client.get("/openapi.json")

    assert docs.status_code == 404
    assert redoc.status_code == 404
    assert openapi.status_code == 404

    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)
    monkeypatch.delenv("MOBILE_API_SECRET", raising=False)
    monkeypatch.delenv("MOBILE_API_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("MOBILE_API_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("MOBILE_API_CORS_ORIGINS", raising=False)
    importlib.reload(config_mod)
    importlib.reload(main_mod)


@pytest.mark.asyncio
async def test_local_mode_keeps_api_docs_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_DEPLOY", raising=False)

    from app.mobile_api import config as config_mod
    from app.mobile_api import main as main_mod

    importlib.reload(config_mod)
    reloaded = importlib.reload(main_mod)
    app = reloaded.create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200

    importlib.reload(config_mod)
    importlib.reload(main_mod)


@pytest.mark.asyncio
async def test_mobile_api_serves_web_dist_when_enabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><title>Novel Operator</title>", encoding="utf-8")
    (dist_dir / "reader-offline-sw.js").write_text("self.addEventListener('fetch', () => {})", encoding="utf-8")
    (dist_dir / "manifest.webmanifest").write_text('{"name":"Novel"}', encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")

    monkeypatch.setenv("MOBILE_API_SERVE_WEB", "1")
    monkeypatch.setenv("WEB_DIST_DIR", str(dist_dir))

    from app.mobile_api import config as config_mod
    from app.mobile_api import main as main_mod

    importlib.reload(config_mod)
    reloaded = importlib.reload(main_mod)
    app = reloaded.create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        nested = await client.get("/books/1")
        service_worker = await client.get("/reader-offline-sw.js")
        manifest = await client.get("/manifest.webmanifest")
        health = await client.get("/api/health")

    assert root.status_code == 200
    assert "Novel Operator" in root.text
    assert nested.status_code == 200
    assert "Novel Operator" in nested.text
    assert service_worker.status_code == 200
    assert "self.addEventListener" in service_worker.text
    assert "javascript" in service_worker.headers["content-type"]
    assert manifest.status_code == 200
    assert manifest.json()["name"] == "Novel"
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    monkeypatch.delenv("MOBILE_API_SERVE_WEB", raising=False)
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    importlib.reload(config_mod)
    importlib.reload(main_mod)


@pytest.mark.asyncio
async def test_relative_web_dist_dir_resolves_from_project_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import PROJECT_ROOT

    rel_dist = "tmp-web-dist-test"
    dist_dir = PROJECT_ROOT / rel_dist
    shutil.rmtree(dist_dir, ignore_errors=True)
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><title>Root Dist</title>", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOBILE_API_SERVE_WEB", "1")
    monkeypatch.setenv("WEB_DIST_DIR", rel_dist)

    from app.mobile_api import config as config_mod
    from app.mobile_api import main as main_mod

    try:
        importlib.reload(config_mod)
        reloaded = importlib.reload(main_mod)
        app = reloaded.create_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            root = await client.get("/")

        assert root.status_code == 200
        assert "Root Dist" in root.text
    finally:
        monkeypatch.delenv("MOBILE_API_SERVE_WEB", raising=False)
        monkeypatch.delenv("WEB_DIST_DIR", raising=False)
        importlib.reload(config_mod)
        importlib.reload(main_mod)
        shutil.rmtree(dist_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_mobile_api_does_not_mount_missing_web_dist(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_API_SERVE_WEB", "1")
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "missing"))

    from app.mobile_api import config as config_mod
    from app.mobile_api import main as main_mod

    importlib.reload(config_mod)
    reloaded = importlib.reload(main_mod)
    app = reloaded.create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        health = await client.get("/api/health")

    assert root.status_code == 404
    assert health.status_code == 200

    monkeypatch.delenv("MOBILE_API_SERVE_WEB", raising=False)
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    importlib.reload(config_mod)
    importlib.reload(main_mod)
