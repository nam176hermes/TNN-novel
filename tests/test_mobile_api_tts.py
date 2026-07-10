from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, add_chapter, init_db, update_chapter_paths
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
import app.mobile_api.routers.tts as tts_router
from app.services.tts.tts_pipeline import TTSPipeline


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class RecordingJobService:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def start_tts_job(self, **kwargs) -> str:
        self.kwargs = kwargs
        return "tts-api-job"


@pytest.mark.asyncio
async def test_tts_chapter_endpoint_starts_existing_job_runner() -> None:
    service = RecordingJobService()
    app.dependency_overrides[tts_router.get_job_service] = lambda: service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/tts/chapter",
                json={"book_id": 1, "chapter_id": 9, "voice_config": {"voice": "vi-VN-Test", "rate": "-3%"}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(tts_router.get_job_service, None)

    assert response.status_code == 200
    assert response.json()["job_id"] == "tts-api-job"
    assert service.kwargs == {
        "book_id": 1,
        "chapter_ids": [9],
        "limit": 1,
        "voice": "vi-VN-Test",
        "rate": "-3%",
        "volume": "+0%",
    }


@pytest.mark.asyncio
async def test_tts_job_status_endpoint_returns_sanitized_chunk_status(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    translation_path = tmp_path / "translation.txt"
    translation_path.write_text("Một đoạn tiếng Việt.", encoding="utf-8")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translation_path)
    pipeline = TTSPipeline(temp_db_path, tmp_path)
    with __import__("sqlite3").connect(temp_db_path) as conn:
        now = "2026-07-01T00:00:00+00:00"
        conn.execute(
            """
            INSERT INTO tts_jobs
            (id, book_id, chapter_id, status, provider, model, progress, output_mp3_path, created_at, updated_at)
            VALUES ('tts-status', ?, ?, 'running', 'f5_vietnamese', 'vivioice', 30, ?, ?, ?)
            """,
            (book_id, chapter_id, str(tmp_path / "internal-output.mp3"), now, now),
        )
        conn.execute(
            """
            INSERT INTO tts_chunks
            (id, job_id, chunk_index, text, normalized_text, text_hash, status, wav_path, mp3_path, qa_report_json, created_at, updated_at)
            VALUES ('tts-status:0000', 'tts-status', 0, 'private text', 'private text', 'hash', 'running', ?, ?, '{}', ?, ?)
            """,
            (str(tmp_path / "internal.wav"), str(tmp_path / "internal.mp3"), now, now),
        )
        conn.commit()

    app.dependency_overrides[tts_router.get_tts_pipeline] = lambda: pipeline
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.get("/api/tts/jobs/tts-status", headers=headers)
    finally:
        app.dependency_overrides.pop(tts_router.get_tts_pipeline, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("job_id") == "tts-status" or payload.get("id") == "tts-status"
    assert payload["chunks"][0]["status"] == "running"
    assert "text" not in payload["chunks"][0]
    assert "normalized_text" not in payload["chunks"][0]
    assert "wav_path" not in payload["chunks"][0]
    assert "mp3_path" not in payload["chunks"][0]
    assert "output_mp3_path" not in payload
    assert "report_json_path" not in payload
    assert payload["output_mp3_download_url"].endswith("/api/tts/jobs/tts-status/download?format=mp3")


@pytest.mark.asyncio
async def test_tts_download_endpoint_requires_authentication_and_hides_internal_paths(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    output_path = tmp_path / "tts-output.mp3"
    output_path.write_bytes(b"mp3-bytes")
    now = "2026-07-01T00:00:00+00:00"
    with __import__("sqlite3").connect(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO tts_jobs
            (id, book_id, chapter_id, status, provider, model, progress, output_mp3_path, created_at, updated_at)
            VALUES ('tts-download', ?, ?, 'completed', 'f5_vietnamese', 'vivioice', 100, ?, ?, ?)
            """,
            (book_id, chapter_id, str(output_path), now, now),
        )
        conn.commit()

    pipeline = TTSPipeline(temp_db_path, tmp_path)
    app.dependency_overrides[tts_router.get_tts_pipeline] = lambda: pipeline
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthenticated = await client.get("/api/tts/jobs/tts-download/download")
            headers = await auth_headers(client)
            authenticated = await client.get("/api/tts/jobs/tts-download/download", headers=headers)
    finally:
        app.dependency_overrides.pop(tts_router.get_tts_pipeline, None)

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.content == b"mp3-bytes"
