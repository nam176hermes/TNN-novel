from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import get_chapter, init_db
from app.mobile_api.config import mobile_settings


def _build_app_with_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_mod
    from app.mobile_api import main as main_mod
    from app.mobile_api.routers import import_routes
    from app.mobile_api import audit as audit_mod

    data_dir = tmp_path / "data"
    monkeypatch.setattr(app_config.settings, "data_dir", data_dir)
    monkeypatch.setattr(dependencies_mod.settings, "data_dir", data_dir)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: data_dir / "pipeline.db")
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: data_dir / "pipeline.db")
    return main_mod.create_app(), data_dir


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_wizard_text_import_stores_translated_chapters_in_translated_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "translated",
                "duplicate_strategy": "error",
                "chapters": [
                    {
                        "chapter_number": 1,
                        "chapter_title": "Vào núi",
                        "text": "Thiếu niên bước vào núi, gió đêm thổi qua rừng trúc.",
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_chapters"] == 1
    assert body["skipped_chapters"] == 0
    assert body["chapter_ids"]

    chapter = get_chapter(db_path, body["book_id"], 1)
    assert chapter is not None
    assert chapter["status"] == "translated"
    assert chapter["raw_text_path"] in (None, "")
    translated_path = Path(chapter["translated_text_path"])
    assert translated_path.exists()
    assert "Thiếu niên bước vào núi" in translated_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_wizard_text_import_skips_duplicates_without_overwriting_existing_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        first = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "translated",
                "chapters": [
                    {
                        "chapter_number": 1,
                        "chapter_title": "Bản cũ",
                        "text": "Bản dịch đã chỉnh sửa thủ công.",
                    }
                ],
            },
        )
        assert first.status_code == 200, first.text
        second = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "translated",
                "duplicate_strategy": "skip",
                "chapters": [
                    {
                        "chapter_number": 1,
                        "chapter_title": "Bản mới",
                        "text": "Bản dịch mới không được ghi đè khi chọn bỏ qua.",
                    }
                ],
            },
        )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["imported_chapters"] == 0
    assert body["skipped_chapters"] == 1
    assert body["overwritten_chapters"] == 0

    chapter = get_chapter(db_path, body["book_id"], 1)
    assert chapter is not None
    translated_text = Path(chapter["translated_text_path"]).read_text(encoding="utf-8")
    assert "Bản dịch đã chỉnh sửa thủ công" in translated_text
    assert "Bản dịch mới" not in translated_text


@pytest.mark.asyncio
async def test_wizard_text_import_overwrites_duplicate_only_when_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        created = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "raw",
                "chapters": [
                    {
                        "chapter_number": 2,
                        "chapter_title": "旧章",
                        "text": "第2章 旧章\n\n少年走入山中。",
                    }
                ],
            },
        )
        assert created.status_code == 200, created.text
        duplicate_error = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "raw",
                "duplicate_strategy": "error",
                "chapters": [
                    {
                        "chapter_number": 2,
                        "chapter_title": "新章",
                        "text": "第2章 新章\n\n新的内容。",
                    }
                ],
            },
        )
        overwrite = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "raw",
                "duplicate_strategy": "overwrite",
                "chapters": [
                    {
                        "chapter_number": 2,
                        "chapter_title": "新章",
                        "text": "第2章 新章\n\n新的内容。",
                    }
                ],
            },
        )

    assert duplicate_error.status_code == 409
    assert overwrite.status_code == 200, overwrite.text
    body = overwrite.json()
    assert body["imported_chapters"] == 0
    assert body["overwritten_chapters"] == 1

    chapter = get_chapter(db_path, body["book_id"], 2)
    assert chapter is not None
    assert chapter["title"] == "新章"
    raw_text = Path(chapter["raw_text_path"]).read_text(encoding="utf-8")
    assert "新的内容" in raw_text


@pytest.mark.asyncio
async def test_wizard_text_import_requires_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    init_db(data_dir / "pipeline.db")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/import/wizard/text",
            json={
                "title": "Độc Tu",
                "content_kind": "translated",
                "chapters": [{"chapter_number": 1, "chapter_title": "Mở đầu", "text": "Nội dung."}],
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wizard_text_import_rejects_empty_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    init_db(data_dir / "pipeline.db")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "raw",
                "chapters": [{"chapter_number": 1, "chapter_title": "Mở đầu", "text": "   \n\t  "}],
            },
        )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wizard_text_import_rejects_oversized_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    init_db(data_dir / "pipeline.db")

    from app.mobile_api.routers import import_routes

    monkeypatch.setattr(import_routes, "MAX_WIZARD_TEXT_IMPORT_BYTES", 64, raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Độc Tu",
                "content_kind": "raw",
                "chapters": [{"chapter_number": 1, "chapter_title": "Mở đầu", "text": "第1章\n" + ("x" * 128)}],
            },
        )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wizard_text_import_stores_reviewed_raw_and_translation_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    db_path = data_dir / "pipeline.db"
    init_db(db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Song ngữ",
                "content_kind": "both",
                "chapters": [
                    {
                        "chapter_number": 8,
                        "chapter_title": "Đêm mưa",
                        "raw_text": "第八章 雨夜\n\n少年抬头看雨。",
                        "translated_text": "Chương 8: Đêm mưa\n\nThiếu niên ngẩng đầu nhìn mưa.",
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_chapters"] == 1

    chapter = get_chapter(db_path, body["book_id"], 8)
    assert chapter is not None
    assert chapter["status"] == "translated"
    raw_text = Path(chapter["raw_text_path"]).read_text(encoding="utf-8")
    translated_text = Path(chapter["translated_text_path"]).read_text(encoding="utf-8")
    assert "少年抬头看雨" in raw_text
    assert "Thiếu niên ngẩng đầu nhìn mưa" in translated_text


@pytest.mark.asyncio
async def test_wizard_text_import_rejects_unknown_content_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, data_dir = _build_app_with_data_dir(tmp_path, monkeypatch)
    init_db(data_dir / "pipeline.db")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/api/import/wizard/text",
            headers=headers,
            json={
                "title": "Không rõ",
                "content_kind": "unknown",
                "chapters": [{"chapter_number": 1, "chapter_title": "Mở đầu", "text": "abc"}],
            },
        )

    assert response.status_code == 400
    assert "content mode" in response.json()["detail"].lower()
