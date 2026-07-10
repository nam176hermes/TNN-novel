#!/usr/bin/env python3
"""
Translator V1 endpoint contract tests.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import httpx
import pytest
from app.config import settings
from app.database.db import init_db
from app.database.db import update_chapter_paths
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_db_path

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
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_paste_import_returns_book_and_chapter_id():
    async with make_client() as client:
        headers = await auth_headers(client)
        resp = await client.post(
            "/api/import/paste",
            headers=headers,
            json={
                "title": "Translator V1 Book",
                "chapter_number": 1,
                "chapter_title": "入门",
                "text": "少年站在山门前。",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["book_id"] > 0
    assert data["chapter_id"] > 0
    assert data["message"] == "Imported from paste"


async def test_chapter_source_translation_save_and_fetch_round_trip():
    source_text = "他低声道谢。"
    translation_text = "Hắn khẽ nói lời cảm tạ."

    async with make_client() as client:
        headers = await auth_headers(client)
        import_resp = await client.post(
            "/api/import/paste",
            headers=headers,
            json={
                "title": "Translator V1 Round Trip",
                "chapter_number": 2,
                "chapter_title": "试炼",
                "text": source_text,
            },
        )
        assert import_resp.status_code == 200, import_resp.text
        imported = import_resp.json()
        book_id = imported["book_id"]
        chapter_id = imported["chapter_id"]

        source_resp = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}/source",
            headers=headers,
        )
        assert source_resp.status_code == 200, source_resp.text
        assert source_resp.json()["text"] == source_text

        initial_translation_resp = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}/translation",
            headers=headers,
        )
        assert initial_translation_resp.status_code == 200
        assert initial_translation_resp.json()["text"] == ""
        assert initial_translation_resp.json()["missing"] is True

        save_resp = await client.patch(
            f"/api/books/{book_id}/chapters/{chapter_id}/translation",
            headers=headers,
            json={"text": translation_text},
        )
        assert save_resp.status_code == 200, save_resp.text

        translation_resp = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}/translation",
            headers=headers,
        )
        assert translation_resp.status_code == 200, translation_resp.text
        assert translation_resp.json()["text"] == translation_text
        assert translation_resp.json()["missing"] is False


async def test_audio_stream_requires_authentication_and_allows_bearer_token():
    async with make_client() as client:
        headers = await auth_headers(client)
        import_resp = await client.post(
            "/api/import/paste",
            headers=headers,
            json={
                "title": "Audio Cookie Book",
                "chapter_number": 1,
                "chapter_title": "Audio",
                "text": "他低声道谢。",
            },
        )
        assert import_resp.status_code == 200, import_resp.text
        imported = import_resp.json()
        book_id = imported["book_id"]
        chapter_id = imported["chapter_id"]
        audio_path = settings.resolved_data_dir / "audio" / "cookie-chapter.mp3"
        audio_path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00audio-bytes")
        update_chapter_paths(get_db_path(), chapter_id, audio_path=audio_path, status="audio_done")

        client.cookies.clear()
        unauthenticated_resp = await client.get(f"/api/books/{book_id}/chapters/{chapter_id}/audio")
        stream_resp = await client.get(f"/api/books/{book_id}/chapters/{chapter_id}/audio", headers=headers)

    assert unauthenticated_resp.status_code in {401, 403}, unauthenticated_resp.text
    assert stream_resp.status_code == 200, stream_resp.text
    assert stream_resp.headers["content-type"].startswith("audio/mpeg")
    assert stream_resp.headers.get("cache-control") == "private, no-store"
