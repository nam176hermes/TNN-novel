from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import requests

from app.database.db import (
    add_book,
    add_chapter,
    get_book_by_id,
    get_book_by_title,
    get_chapter_by_id,
    get_connection,
    get_job_attempts,
    get_qa_report,
    init_db,
    record_job_attempt,
    record_provider_usage,
    save_qa_report,
    update_chapter_paths,
)
import app.mobile_api.services.pipeline_service as pipeline_mod
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import audio as audio_router
from app.mobile_api.routers import books as books_router
from app.mobile_api.routers import import_routes as import_router
from app.mobile_api.routers import jobs as jobs_router
from app.mobile_api.routers import qa as qa_router
from app.mobile_api.services import audio_service as audio_service_module
from app.mobile_api.services.qa_service import QAService
from app.mobile_api.services.audio_service import AudioService
from app.mobile_api.services.pipeline_service import PipelineService


def make_pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    pipeline.data_dir = data_dir
    return pipeline


@pytest.fixture
def temp_pipeline(temp_db_path: Path, tmp_path: Path) -> PipelineService:
    init_db(temp_db_path)
    return make_pipeline(temp_db_path, tmp_path)


@pytest.fixture
def override_books_pipeline(temp_pipeline: PipelineService):
    app.dependency_overrides[books_router.get_pipeline] = lambda: temp_pipeline
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(books_router.get_pipeline, None)


@pytest.fixture
def override_import_pipeline(temp_pipeline: PipelineService):
    app.dependency_overrides[import_router.get_pipeline] = lambda: temp_pipeline
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(import_router.get_pipeline, None)


@pytest.fixture
def override_audio_pipeline(temp_pipeline: PipelineService):
    app.dependency_overrides[audio_router.get_audio_service] = lambda: AudioService(temp_pipeline)
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(audio_router.get_audio_service, None)


@pytest.fixture
def override_qa_service(temp_pipeline: PipelineService):
    app.dependency_overrides[qa_router.get_qa_service] = lambda: QAService(temp_pipeline)
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(qa_router.get_qa_service, None)


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


@pytest.mark.asyncio
async def test_patch_book_persists_changes(override_books_pipeline: PipelineService) -> None:
    book_id = add_book(
        override_books_pipeline.db_path,
        "Old Title",
        "Old Author",
        "manual",
        "old-url",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            f"/api/books/{book_id}",
            json={"title": "New Title", "source_url": "new-url"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["title"] == "New Title"
    book = get_book_by_id(override_books_pipeline.db_path, book_id)
    assert book is not None
    assert book["title"] == "New Title"
    assert book["author"] == "Old Author"
    assert book["source_url"] == "new-url"


@pytest.mark.asyncio
async def test_upload_book_cover_saves_image_and_updates_book(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Cover Book")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/cover",
            files={"cover": ("cover.jpg", b"fake-cover-image", "image/jpeg")},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == book_id
    assert payload["cover_url"].startswith("/covers/")
    book = get_book_by_id(override_books_pipeline.db_path, book_id)
    assert book is not None
    assert book["cover_path"]
    cover_path = Path(book["cover_path"])
    assert cover_path.exists()
    assert cover_path.read_bytes() == b"fake-cover-image"


@pytest.mark.asyncio
async def test_patch_book_title_merges_duplicate_book_into_existing_library_entry(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    target_book_id = add_book(override_books_pipeline.db_path, "Thanh Sơn", "Translator", "ebook", "")
    source_book_id = add_book(override_books_pipeline.db_path, "Thanh Sơn raw", "", "source", "https://example.test/raw")
    translated_path = tmp_path / "translated.txt"
    raw_path = tmp_path / "raw.txt"
    translated_path.write_text("Bản dịch chương một", encoding="utf-8")
    raw_path.write_text("原文第一章", encoding="utf-8")
    target_chapter_id = add_chapter(override_books_pipeline.db_path, target_book_id, 1, "Chương một")
    add_chapter(override_books_pipeline.db_path, source_book_id, 1, "Raw chương một", raw_text_path=raw_path)
    update_chapter_paths(
        override_books_pipeline.db_path,
        target_chapter_id,
        translated_text_path=translated_path,
        status="translated",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            f"/api/books/{source_book_id}",
            json={"title": "Thanh Sơn"},
            headers=headers,
        )
        books_response = await client.get("/api/books", headers=headers)
        library_response = await client.get("/api/library/books", headers=headers)
        chapters_response = await client.get(f"/api/books/{target_book_id}/chapters", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == target_book_id
    assert [book["title"] for book in books_response.json()] == ["Thanh Sơn"]
    assert [book["title"] for book in library_response.json()["books"]] == ["Thanh Sơn"]
    chapters = chapters_response.json()
    assert len(chapters) == 1
    assert chapters[0]["raw_text_path"] == str(raw_path)
    assert chapters[0]["translated_text_path"] == str(translated_path)
    assert get_book_by_id(override_books_pipeline.db_path, source_book_id) is None


@pytest.mark.asyncio
async def test_delete_book_removes_existing_book(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.db import list_operational_events
    from app.mobile_api import audit as audit_mod

    book_id = add_book(override_books_pipeline.db_path, "Book To Delete")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Chapter 1")
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: override_books_pipeline.db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.delete(f"/api/books/{book_id}", headers=headers)
        fetch_deleted = await client.get(f"/api/books/{book_id}", headers=headers)

    assert response.status_code == 200
    assert fetch_deleted.status_code == 404
    assert get_book_by_id(override_books_pipeline.db_path, book_id) is None
    assert get_chapter_by_id(override_books_pipeline.db_path, chapter_id) is None
    events = list_operational_events(override_books_pipeline.db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "delete_book")
    assert event["details"]["book_id"] == book_id


@pytest.mark.asyncio
async def test_delete_book_removes_library_files_and_assets(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.txt"
    cleaned_path = tmp_path / "cleaned.txt"
    translated_path = tmp_path / "translated.txt"
    content_html_path = tmp_path / "content.html"
    audio_path = tmp_path / "audio.mp3"
    cover_path = tmp_path / "covers" / "cover.jpg"
    for path, content in (
        (raw_path, "raw"),
        (cleaned_path, "cleaned"),
        (translated_path, "translated"),
        (content_html_path, "<p>translated</p>"),
    ):
        path.write_text(content, encoding="utf-8")
    audio_path.write_bytes(b"audio")
    cover_path.parent.mkdir(parents=True)
    cover_path.write_bytes(b"cover")

    book_id = add_book(
        override_books_pipeline.db_path,
        "Book With Files",
        cover_path=str(cover_path),
    )
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Chapter 1", raw_text_path=raw_path)
    update_chapter_paths(
        override_books_pipeline.db_path,
        chapter_id,
        cleaned_text_path=cleaned_path,
        translated_text_path=translated_path,
        content_html_path=content_html_path,
        audio_path=audio_path,
        status="audio_done",
    )
    asset_dir = override_books_pipeline.data_dir / "book_assets" / str(book_id)
    asset_dir.mkdir(parents=True)
    asset_path = asset_dir / "ch1_map.png"
    asset_path.write_bytes(b"asset")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.delete(f"/api/books/{book_id}", headers=headers)

    assert response.status_code == 200
    assert get_book_by_id(override_books_pipeline.db_path, book_id) is None
    assert get_chapter_by_id(override_books_pipeline.db_path, chapter_id) is None
    for path in (raw_path, cleaned_path, translated_path, content_html_path, audio_path, cover_path, asset_path):
        assert not path.exists()
    assert not asset_dir.exists()


@pytest.mark.asyncio
async def test_delete_missing_book_returns_404(override_books_pipeline: PipelineService) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.delete("/api/books/999", headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_library_books_endpoint_returns_translated_book_summaries(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    translated_book_id = add_book(
        override_books_pipeline.db_path,
        "Translated Book",
        "Author A",
        "manual",
        "https://example.test/book",
    )
    translated_path = tmp_path / "translated.txt"
    audio_path = tmp_path / "audio.mp3"
    translated_path.write_text("Bản dịch chương một", encoding="utf-8")
    audio_path.write_bytes(b"audio")
    first_chapter_id = add_chapter(override_books_pipeline.db_path, translated_book_id, 1, "Chương một")
    update_chapter_paths(
        override_books_pipeline.db_path,
        first_chapter_id,
        translated_text_path=translated_path,
        audio_path=audio_path,
        status="audio_done",
    )
    qa_low_chapter_id = add_chapter(override_books_pipeline.db_path, translated_book_id, 2, "Chương hai")
    update_chapter_paths(override_books_pipeline.db_path, qa_low_chapter_id, status="qa_low")
    add_chapter(override_books_pipeline.db_path, translated_book_id, 3, "Chương ba")

    untranslated_book_id = add_book(override_books_pipeline.db_path, "Untranslated Book")
    add_chapter(override_books_pipeline.db_path, untranslated_book_id, 1, "Raw Only")

    deleted_book_id = add_book(override_books_pipeline.db_path, "Deleted Translation Book")
    deleted_chapter_id = add_chapter(override_books_pipeline.db_path, deleted_book_id, 1, "Deleted")
    deleted_translation_path = tmp_path / "deleted.txt"
    deleted_translation_path.write_text("deleted", encoding="utf-8")
    update_chapter_paths(
        override_books_pipeline.db_path,
        deleted_chapter_id,
        translated_text_path=deleted_translation_path,
        status="translated",
    )
    assert override_books_pipeline.delete_chapter(deleted_book_id, deleted_chapter_id) is True

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/library/books", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert [book["title"] for book in payload["books"]] == ["Translated Book"]

    summary = payload["books"][0]
    assert summary["id"] == translated_book_id
    assert summary["author"] == "Author A"
    assert summary["source_url"] == "https://example.test/book"
    assert summary["total_chapters"] == 3
    assert summary["translated_chapters"] == 2
    assert summary["audio_chapters"] == 1
    assert summary["qa_low_chapters"] == 1
    assert summary["failed_chapters"] == 0
    assert summary["first_translated_chapter_id"] == first_chapter_id
    assert summary["latest_translated_chapter_id"] == qa_low_chapter_id
    assert summary["latest_chapter_number"] == 2
    assert summary["latest_chapter_title"] == "Chương hai"


@pytest.mark.asyncio
async def test_chapter_source_requires_matching_book(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_a = add_book(override_books_pipeline.db_path, "Book A")
    book_b = add_book(override_books_pipeline.db_path, "Book B")
    raw_path = tmp_path / "book-b-source.txt"
    raw_path.write_text("secret source", encoding="utf-8")
    chapter_b = add_chapter(override_books_pipeline.db_path, book_b, 1, "B1", raw_text_path=raw_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_a}/chapters/{chapter_b}/source",
            headers=headers,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_translation_update_requires_matching_book(
    override_books_pipeline: PipelineService,
) -> None:
    book_a = add_book(override_books_pipeline.db_path, "Book A")
    book_b = add_book(override_books_pipeline.db_path, "Book B")
    chapter_b = add_chapter(override_books_pipeline.db_path, book_b, 1, "B1")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.patch(
            f"/api/books/{book_a}/chapters/{chapter_b}/translation",
            json={"text": "wrong book"},
            headers=headers,
        )

    assert response.status_code == 404
    chapter = get_chapter_by_id(override_books_pipeline.db_path, chapter_b)
    assert chapter is not None
    assert chapter["translated_text_path"] is None


@pytest.mark.asyncio
async def test_audio_stream_requires_matching_book(
    override_audio_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_a = add_book(override_audio_pipeline.db_path, "Book A")
    book_b = add_book(override_audio_pipeline.db_path, "Book B")
    chapter_b = add_chapter(override_audio_pipeline.db_path, book_b, 1, "B1")
    audio_path = tmp_path / "chapter-b.mp3"
    audio_path.write_bytes(b"fake mp3")
    update_chapter_paths(override_audio_pipeline.db_path, chapter_b, audio_path=audio_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_a}/chapters/{chapter_b}/audio",
            headers=headers,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_audio_playlist_returns_client_urls_without_local_paths(
    override_audio_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    book_id = add_book(override_audio_pipeline.db_path, "Audio Book")
    chapter_id = add_chapter(override_audio_pipeline.db_path, book_id, 1, "Chương có audio")
    audio_path = tmp_path / "chapter-1.mp3"
    audio_path.write_bytes(b"fake mp3")
    update_chapter_paths(override_audio_pipeline.db_path, chapter_id, audio_path=audio_path)

    class FakeAudioMetadata:
        class info:
            length = 123.45

    monkeypatch.setattr(audio_service_module, "MutagenFile", lambda _path: FakeAudioMetadata(), raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/audio/playlist",
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["book_id"] == book_id
    assert payload["chapters"] == [
        {
            "chapter_id": chapter_id,
            "chapter_number": 1,
            "title": "Chương có audio",
            "duration_seconds": 123.45,
            "download_url": f"/api/books/{book_id}/chapters/{chapter_id}/audio/download",
            "filename": "chapter-1.mp3",
            "order": 0,
            "size_bytes": len(b"fake mp3"),
            "stream_url": f"/api/books/{book_id}/chapters/{chapter_id}/audio",
        }
    ]
    assert "audio_path" not in payload["chapters"][0]


def test_audio_playlist_openapi_documents_client_url_payload() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    response_schema = schema["paths"]["/api/books/{book_id}/audio/playlist"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"] == "#/components/schemas/PlaylistResponse"
    playlist_item = schema["components"]["schemas"]["PlaylistItem"]
    properties = playlist_item["properties"]
    assert "stream_url" in properties
    assert "download_url" in properties
    assert "filename" in properties
    assert "size_bytes" in properties
    assert "audio_path" not in properties


@pytest.mark.asyncio
async def test_job_attempts_endpoint_returns_attempts_for_job(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    first_id = record_job_attempt(
        temp_db_path,
        job_id="job-api",
        chapter_id=1,
        stage="translate",
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        status="failed",
        error="rate limit",
        elapsed_ms=1234,
    )
    second_id = record_job_attempt(
        temp_db_path,
        job_id="job-api",
        chapter_id=2,
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        status="success",
    )
    record_job_attempt(
        temp_db_path,
        job_id="other-job",
        chapter_id=3,
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        status="success",
    )
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path, raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/jobs/job-api/attempts", headers=headers)

    assert response.status_code == 200
    attempts = response.json()["attempts"]
    assert [attempt["id"] for attempt in attempts] == [second_id, first_id]
    assert all(attempt["job_id"] == "job-api" for attempt in attempts)
    assert attempts[0]["status"] == "success"
    assert attempts[1]["stage"] == "translate"
    assert attempts[1]["error"] == "rate limit"
    assert attempts[1]["elapsed_ms"] == 1234


@pytest.mark.asyncio
async def test_job_attempts_endpoint_requires_authentication() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/jobs/job-api/attempts")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_qa_report_returns_no_content(override_qa_service: PipelineService) -> None:
    book_id = add_book(override_qa_service.db_path, "Book")
    chapter_id = add_chapter(override_qa_service.db_path, book_id, 1, "Chapter")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(f"/api/books/{book_id}/chapters/{chapter_id}/qa", headers=headers)

    assert response.status_code == 204
    assert response.content == b""


def test_translate_chapter_requires_matching_book(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_a = add_book(temp_pipeline.db_path, "Book A")
    book_b = add_book(temp_pipeline.db_path, "Book B")
    raw_path = tmp_path / "book-b-source.txt"
    raw_path.write_text("source", encoding="utf-8")
    chapter_b = add_chapter(temp_pipeline.db_path, book_b, 1, "B1", raw_text_path=raw_path)
    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.translate_chapter",
        lambda **_: "translated",
    )

    with pytest.raises(ValueError, match="Chapter .* not found"):
        temp_pipeline.translate_chapter(book_a, chapter_b)


def test_translate_chapter_passes_style_profile_id_to_translation_client(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("source", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    captured: dict[str, object] = {}

    def fake_translate(**kwargs):
        captured.update(kwargs)
        return "translated"

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.translate_chapter", fake_translate)

    temp_pipeline.translate_chapter(book_id, chapter_id, style_profile_id="kiem_hiep")

    assert captured["style_profile_id"] == "kiem_hiep"


def test_translate_chapter_with_pipeline_runs_translate_polish_and_qa(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("陆哥，我多谢你。", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    calls: list[tuple[str, dict]] = []

    def fake_provider_options(preset_id: str, task_type: str) -> dict:
        return {
            "provider_id": f"{preset_id}-{task_type}",
            "model": f"{task_type}-model",
            "host": "https://provider.example/v1",
            "api_key": "secret",
        }

    def fake_translate(**kwargs):
        calls.append(("translate", kwargs))
        return "Lục ca, tôi cảm ơn anh."

    def fake_call_llm(**kwargs):
        calls.append((kwargs["task_type"], kwargs))
        assert "Pronoun memory" in kwargs["prompt"]
        return "Lục ca, ta cảm tạ huynh."

    def fake_qa(**kwargs):
        calls.append(("qa", kwargs))
        return {
            "quality_score": 8.5,
            "fidelity_score": 9,
            "style_score": 8,
            "glossary_score": 8,
            "audiobook_score": 9,
            "verdict": "PASS",
            "issues": [],
        }

    monkeypatch.setattr(temp_pipeline, "_provider_options_for_preset_task", fake_provider_options, raising=False)
    monkeypatch.setattr(pipeline_mod, "translate_chapter", fake_translate)
    monkeypatch.setattr(pipeline_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(pipeline_mod, "run_qa_check", fake_qa)

    result = temp_pipeline.translate_chapter_with_pipeline(
        book_id,
        chapter_id,
        preset_id="balanced",
        style_profile_id="tien_hiep",
        job_id="job-pipeline",
    )

    assert result["text"] == "Lục ca, ta cảm tạ huynh."
    assert [name for name, _ in calls] == ["translate", "polish", "qa"]
    assert calls[0][1]["provider_id"] == "balanced-translate"
    assert calls[0][1]["task_type"] == "translate"
    assert calls[0][1]["style_profile_id"] == "tien_hiep"
    assert calls[1][1]["provider_id"] == "balanced-polish"
    assert calls[2][1]["provider_id"] == "balanced-qa"
    assert temp_pipeline.get_chapter_translation(chapter_id) == "Lục ca, ta cảm tạ huynh."
    report = get_qa_report(temp_pipeline.db_path, book_id, chapter_id)
    assert report is not None
    assert report["verdict"] == "PASS"


def test_fast_draft_pipeline_only_translates_and_records_stage_timing(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("陆哥，我多谢你。", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    calls: list[dict] = []

    def fake_provider_options(preset_id: str, task_type: str) -> dict:
        return {
            "provider_id": f"{preset_id}-{task_type}",
            "model": f"{task_type}-model",
            "host": "https://provider.example/v1",
            "api_key": "secret",
        }

    def fake_translate(**kwargs):
        calls.append(kwargs)
        return "Chủ nhà hoàn thành ẩn vụ và nhận tích phân."

    def forbidden_llm(**kwargs):
        raise AssertionError(f"fast_draft should not call {kwargs.get('task_type')}")

    monkeypatch.setattr(temp_pipeline, "_provider_options_for_preset_task", fake_provider_options, raising=False)
    monkeypatch.setattr(pipeline_mod, "translate_chapter", fake_translate)
    monkeypatch.setattr(pipeline_mod, "call_llm", forbidden_llm)
    monkeypatch.setattr(pipeline_mod, "run_qa_check", forbidden_llm)

    result = temp_pipeline.translate_chapter_with_pipeline(
        book_id,
        chapter_id,
        preset_id="fast_draft",
        style_profile_id="huyen_huyen",
        job_id="job-fast-draft",
    )

    assert len(calls) == 1
    assert calls[0]["chunk_size"] == 3500
    assert result["text"] == "Ký chủ hoàn thành nhiệm vụ ẩn và nhận điểm tích lũy."
    assert result["qa_report"] is None
    assert temp_pipeline.get_chapter_translation(chapter_id) == "Ký chủ hoàn thành nhiệm vụ ẩn và nhận điểm tích lũy."
    assert get_qa_report(temp_pipeline.db_path, book_id, chapter_id) is None

    attempts = get_job_attempts(temp_pipeline.db_path, job_id="job-fast-draft")
    assert len(attempts) == 1
    assert attempts[0]["stage"] == "translate"
    assert attempts[0]["provider_id"] == "fast_draft-translate"
    assert attempts[0]["model"] == "translate-model"
    assert attempts[0]["status"] == "success"
    assert attempts[0]["elapsed_ms"] >= 0


def test_translate_chapter_with_pipeline_normalizes_polished_system_output(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("叮！检测到宿主完成隐藏任务，奖励积分一万点，是否领取？", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)

    monkeypatch.setattr(
        temp_pipeline,
        "_provider_options_for_preset_task",
        lambda preset_id, task_type: {
            "provider_id": f"{preset_id}-{task_type}",
            "model": f"{task_type}-model",
            "host": "https://provider.example/v1",
            "api_key": "secret",
        },
        raising=False,
    )
    monkeypatch.setattr(
        pipeline_mod,
        "translate_chapter",
        lambda **_: "[Đinh! Phát hiện ký chủ hoàn thành nhiệm vụ ẩn.]",
    )
    monkeypatch.setattr(
        pipeline_mod,
        "call_llm",
        lambda **_: "Đinh! Phát hiện ký chủ hoàn thành ẩn vụ, ban thưởng một vạn tích phân, có nhận hay không?",
    )
    monkeypatch.setattr(
        pipeline_mod,
        "run_qa_check",
        lambda **_: {
            "quality_score": 9,
            "fidelity_score": 9,
            "style_score": 9,
            "glossary_score": 9,
            "audiobook_score": 9,
            "verdict": "PASS",
            "issues": [],
        },
    )

    result = temp_pipeline.translate_chapter_with_pipeline(book_id, chapter_id, preset_id="balanced")

    expected = (
        "[Đinh! Phát hiện ký chủ hoàn thành nhiệm vụ ẩn.]\n"
        "[Phần thưởng: một vạn điểm tích lũy.]\n"
        "[Có nhận không?]"
    )
    assert result["text"] == expected
    assert temp_pipeline.get_chapter_translation(chapter_id) == expected


def test_translate_chapter_with_pipeline_keeps_rough_translation_when_polish_is_temporarily_unavailable(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("宿主完成隐藏任务，奖励积分一万点。", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    qa_inputs: list[str] = []

    def fake_provider_options(preset_id: str, task_type: str) -> dict:
        return {
            "provider_id": f"{preset_id}-{task_type}",
            "model": f"{task_type}-model",
            "host": "https://provider.example/v1",
            "api_key": "secret",
        }

    response = requests.Response()
    response.status_code = 503
    response.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    polish_error = requests.HTTPError("503 Server Error: Service Unavailable", response=response)

    monkeypatch.setattr(temp_pipeline, "_provider_options_for_preset_task", fake_provider_options, raising=False)
    monkeypatch.setattr(
        pipeline_mod,
        "translate_chapter",
        lambda **_: "Chủ nhà hoàn thành ẩn vụ và nhận tích phân một vạn điểm.",
    )
    monkeypatch.setattr(pipeline_mod, "call_llm", lambda **_: (_ for _ in ()).throw(polish_error))

    def fake_qa(**kwargs):
        qa_inputs.append(kwargs["translated_text"])
        return {
            "quality_score": 7,
            "fidelity_score": 8,
            "style_score": 7,
            "glossary_score": 8,
            "audiobook_score": 8,
            "verdict": "WARN",
            "issues": [{"type": "provider_fallback", "message": "Polish provider unavailable"}],
        }

    monkeypatch.setattr(pipeline_mod, "run_qa_check", fake_qa)

    result = temp_pipeline.translate_chapter_with_pipeline(
        book_id,
        chapter_id,
        preset_id="balanced",
        job_id="job-polish-fallback",
    )

    expected = "Ký chủ hoàn thành nhiệm vụ ẩn và nhận điểm tích lũy một vạn điểm."
    assert result["text"] == expected
    assert qa_inputs == [expected]
    assert temp_pipeline.get_chapter_translation(chapter_id) == expected

    attempts = get_job_attempts(temp_pipeline.db_path, job_id="job-polish-fallback")
    polish_attempts = sorted(
        [attempt for attempt in attempts if attempt["stage"] == "polish"],
        key=lambda attempt: attempt["id"],
    )
    assert [attempt["status"] for attempt in polish_attempts] == ["failed", "fallback"]


def test_high_quality_pipeline_rewrites_translation_when_qa_flags_issues(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    raw_path.write_text("陆哥，我多谢你。", encoding="utf-8")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    llm_tasks: list[str] = []

    monkeypatch.setattr(
        temp_pipeline,
        "_provider_options_for_preset_task",
        lambda preset_id, task_type: {
            "provider_id": f"{preset_id}-{task_type}",
            "model": f"{task_type}-model",
            "host": "https://provider.example/v1",
            "api_key": "secret",
        },
        raising=False,
    )
    monkeypatch.setattr(pipeline_mod, "translate_chapter", lambda **_: "Lục ca, tôi cảm ơn anh.")

    def fake_call_llm(**kwargs):
        llm_tasks.append(kwargs["task_type"])
        if kwargs["task_type"] == "rewrite":
            assert "QA issues" in kwargs["prompt"]
            return "Lục ca, ta cảm tạ huynh."
        return "Lục ca, tôi cảm ơn anh."

    def fake_qa(**kwargs):
        return {
            "quality_score": 5,
            "fidelity_score": 8,
            "style_score": 4,
            "glossary_score": 8,
            "audiobook_score": 8,
            "verdict": "FAIL",
            "issues": [{"type": "pronoun_modern", "message": "Modern pronoun tôi"}],
        }

    monkeypatch.setattr(pipeline_mod, "call_llm", fake_call_llm)
    monkeypatch.setattr(pipeline_mod, "run_qa_check", fake_qa)

    result = temp_pipeline.translate_chapter_with_pipeline(
        book_id,
        chapter_id,
        preset_id="quality_high",
        style_profile_id="tien_hiep",
    )

    assert llm_tasks == ["polish", "rewrite"]
    assert result["text"] == "Lục ca, ta cảm tạ huynh."
    assert temp_pipeline.get_chapter_translation(chapter_id) == "Lục ca, ta cảm tạ huynh."


def test_generate_audio_requires_matching_book(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_a = add_book(temp_pipeline.db_path, "Book A")
    book_b = add_book(temp_pipeline.db_path, "Book B")
    chapter_b = add_chapter(temp_pipeline.db_path, book_b, 1, "B1")
    translation_path = tmp_path / "book-b-translation.txt"
    translation_path.write_text("translation", encoding="utf-8")
    update_chapter_paths(temp_pipeline.db_path, chapter_b, translated_text_path=translation_path)
    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.text_to_speech_file",
        lambda **_: None,
    )

    assert temp_pipeline.generate_audio(book_a, chapter_b) is None


def test_run_qa_check_requires_matching_book(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_a = add_book(temp_pipeline.db_path, "Book A")
    book_b = add_book(temp_pipeline.db_path, "Book B")
    raw_path = tmp_path / "book-b-source.txt"
    trans_path = tmp_path / "book-b-translation.txt"
    raw_path.write_text("source", encoding="utf-8")
    trans_path.write_text("translation", encoding="utf-8")
    chapter_b = add_chapter(temp_pipeline.db_path, book_b, 1, "B1", raw_text_path=raw_path)
    update_chapter_paths(temp_pipeline.db_path, chapter_b, translated_text_path=trans_path)
    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.run_qa_check",
        lambda **_: {"quality_score": 100},
    )

    with pytest.raises(ValueError, match="Chapter .* not found"):
        temp_pipeline.run_qa_check(book_a, chapter_b)


def test_update_chapter_translation_writes_under_pipeline_data_dir(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter")

    assert temp_pipeline.update_chapter_translation(chapter_id, "translated text") is True

    chapter = get_chapter_by_id(temp_pipeline.db_path, chapter_id)
    assert chapter is not None
    translated_path = Path(chapter["translated_text_path"])
    assert temp_pipeline.data_dir in translated_path.parents
    assert translated_path.read_text(encoding="utf-8") == "translated text"
    assert chapter["status"] == "translated"


def test_update_chapter_translation_removes_previous_generated_translation(
    temp_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter")
    old_translation = tmp_path / "old-translation.txt"
    old_translation.write_text("old text", encoding="utf-8")
    update_chapter_paths(
        temp_pipeline.db_path,
        chapter_id,
        translated_text_path=old_translation,
        status="failed",
    )

    assert temp_pipeline.update_chapter_translation(chapter_id, "new text") is True

    chapter = get_chapter_by_id(temp_pipeline.db_path, chapter_id)
    assert chapter is not None
    assert chapter["translated_text_path"] != str(old_translation)
    assert not old_translation.exists()
    assert Path(chapter["translated_text_path"]).read_text(encoding="utf-8") == "new text"


def test_generate_audio_writes_under_pipeline_data_dir(
    temp_pipeline: PipelineService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter")
    translation_path = tmp_path / "translation.txt"
    translation_path.write_text("translation", encoding="utf-8")
    update_chapter_paths(temp_pipeline.db_path, chapter_id, translated_text_path=translation_path)

    class FakeTTSPipeline:
        def __init__(self, db_path: Path, data_dir: Path, **_: object) -> None:
            self.data_dir = data_dir

        def generate_chapter(self, *, book_id: int, chapter_id: int, job_id: str, voice_config: dict[str, str]):
            output_path = self.data_dir / "audio" / f"book{book_id}_ch{chapter_id}_{job_id or 'tts'}.mp3"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake mp3")
            return type(
                "FakeTTSReport",
                (),
                {"status": "completed", "output_mp3_path": str(output_path), "error_message": ""},
            )()

    monkeypatch.setattr(pipeline_mod, "TTSPipeline", FakeTTSPipeline)

    audio_path = temp_pipeline.generate_audio(book_id, chapter_id)

    assert audio_path is not None
    assert temp_pipeline.data_dir in audio_path.parents
    assert audio_path.read_bytes() == b"fake mp3"


def test_import_from_text_writes_under_pipeline_data_dir(
    temp_pipeline: PipelineService,
) -> None:
    result = temp_pipeline.import_from_text("Imported Book", 1, "Chapter", "raw text")

    chapters = temp_pipeline.list_chapters(result["book_id"])
    assert len(chapters) == 1
    assert chapters[0]["id"] == result["chapter_id"]
    raw_path = Path(chapters[0]["raw_text_path"])
    assert temp_pipeline.data_dir in raw_path.parents
    assert raw_path.read_text(encoding="utf-8") == "raw text"


def test_import_from_text_detects_metadata_groups_normalized_title_and_rejects_duplicate(
    temp_pipeline: PipelineService,
) -> None:
    first = temp_pipeline.import_from_text(
        "",
        1,
        "",
        "《Yong Ye [raw]》\n第十二章 雪夜来客\n秦铭推开门。",
    )
    second = temp_pipeline.import_from_text(
        "Yong-Ye",
        13,
        "",
        "第十三章 风雪归人\n陆泽进山。",
    )

    first_book = get_book_by_id(temp_pipeline.db_path, first["book_id"])
    second_book = get_book_by_id(temp_pipeline.db_path, second["book_id"])
    chapters = temp_pipeline.list_chapters(first["book_id"])

    assert first_book is not None
    assert first_book["title"] == "Yong Ye"
    assert second_book is not None
    assert second_book["id"] == first_book["id"]
    assert [chapter["chapter_number"] for chapter in chapters] == [13, 12]
    assert chapters[1]["title"] == "雪夜来客"

    with pytest.raises(ValueError, match="Duplicate chapter"):
        temp_pipeline.import_from_text(
            "Yong Ye",
            12,
            "雪夜来客",
            "《Yong Ye》\n第十二章 雪夜来客\n秦铭推开门。",
        )


def test_delete_chapter_translation_keeps_source_and_clears_generated_artifacts(
    temp_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    translated_path = tmp_path / "translation.txt"
    audio_path = tmp_path / "audio.mp3"
    raw_path.write_text("source", encoding="utf-8")
    translated_path.write_text("translation", encoding="utf-8")
    audio_path.write_bytes(b"audio")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(
        temp_pipeline.db_path,
        chapter_id,
        translated_text_path=translated_path,
        audio_path=audio_path,
        status="translated",
    )
    save_qa_report(temp_pipeline.db_path, book_id, chapter_id, 8, 8, 8, 8, 8, "PASS", "{}")
    record_provider_usage(
        temp_pipeline.db_path,
        provider_id="gemini",
        model="gemini-live",
        task_type="translate",
        prompt_tokens=10,
        completion_tokens=5,
        estimated_cost_usd=0.01,
        job_id="job-translation",
        chapter_id=chapter_id,
    )
    record_job_attempt(
        temp_pipeline.db_path,
        job_id="job-translation",
        chapter_id=chapter_id,
        provider_id="gemini",
        model="gemini-live",
        status="success",
    )

    assert temp_pipeline.delete_chapter_translation(book_id, chapter_id) is True

    chapter = get_chapter_by_id(temp_pipeline.db_path, chapter_id)
    assert chapter is not None
    assert chapter["raw_text_path"] == str(raw_path)
    assert chapter["translated_text_path"] is None
    assert chapter["audio_path"] is None
    assert chapter["status"] == "cleaned"
    assert temp_pipeline.get_chapter_source(chapter_id) == "source"
    assert temp_pipeline.get_chapter_translation(chapter_id) is None
    assert get_qa_report(temp_pipeline.db_path, book_id, chapter_id) is None
    assert get_job_attempts(temp_pipeline.db_path, chapter_id=chapter_id) == []
    with get_connection(temp_pipeline.db_path) as conn:
        usage_count = conn.execute(
            "SELECT COUNT(*) FROM provider_usage WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()[0]
    assert usage_count == 0


def test_delete_chapter_soft_deletes_and_hides_chapter(
    temp_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    translated_path = tmp_path / "translation.txt"
    audio_path = tmp_path / "audio.mp3"
    raw_path.write_text("source", encoding="utf-8")
    translated_path.write_text("translation", encoding="utf-8")
    audio_path.write_bytes(b"audio")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(
        temp_pipeline.db_path,
        chapter_id,
        translated_text_path=translated_path,
        audio_path=audio_path,
        status="translated",
    )

    assert temp_pipeline.delete_chapter(book_id, chapter_id) is True

    assert temp_pipeline.get_chapter(chapter_id) is None
    assert temp_pipeline.list_chapters(book_id) == []
    with get_connection(temp_pipeline.db_path) as conn:
        deleted = conn.execute(
            "SELECT status, deleted_at, raw_text_path, translated_text_path, audio_path FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    assert deleted is not None
    assert deleted["status"] == "deleted"
    assert deleted["deleted_at"]
    assert deleted["raw_text_path"] is None
    assert deleted["translated_text_path"] is None
    assert deleted["audio_path"] is None


def test_library_books_hide_books_that_only_have_deleted_chapters(
    temp_pipeline: PipelineService,
) -> None:
    active_book_id = add_book(temp_pipeline.db_path, "Active Book")
    add_chapter(temp_pipeline.db_path, active_book_id, 1, "Active Chapter")
    deleted_book_id = add_book(temp_pipeline.db_path, "Deleted Only Book")
    deleted_chapter_id = add_chapter(temp_pipeline.db_path, deleted_book_id, 1, "Deleted Chapter")

    assert temp_pipeline.delete_chapter(deleted_book_id, deleted_chapter_id) is True

    titles = [book["title"] for book in temp_pipeline.list_books()]

    assert "Active Book" in titles
    assert "Deleted Only Book" not in titles


@pytest.mark.asyncio
async def test_chapter_delete_endpoints_apply_cleanup(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Book")
    raw_path = tmp_path / "source.txt"
    translated_path = tmp_path / "translation.txt"
    content_html_path = tmp_path / "translation.html"
    raw_path.write_text("source", encoding="utf-8")
    translated_path.write_text("translation", encoding="utf-8")
    content_html_path.write_text('<p>translation</p><img src="/book-assets/1/sword.png"/>', encoding="utf-8")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(
        override_books_pipeline.db_path,
        chapter_id,
        translated_text_path=translated_path,
        content_html_path=content_html_path,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        content_response = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}/content",
            headers=headers,
        )
        clear_response = await client.delete(
            f"/api/books/{book_id}/chapters/{chapter_id}/translation",
            headers=headers,
        )
        chapter_response = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}",
            headers=headers,
        )
        delete_response = await client.delete(
            f"/api/books/{book_id}/chapters/{chapter_id}",
            headers=headers,
        )
        fetch_deleted = await client.get(
            f"/api/books/{book_id}/chapters/{chapter_id}",
            headers=headers,
        )

    assert content_response.status_code == 200
    assert content_response.json() == {
        "chapter_id": chapter_id,
        "text": "translation",
        "html": '<p>translation</p><img src="/book-assets/1/sword.png"/>',
    }
    assert clear_response.status_code == 200
    assert chapter_response.status_code == 200
    assert chapter_response.json()["translated_text_path"] is None
    assert chapter_response.json()["content_html_path"] is None
    assert delete_response.status_code == 200
    assert fetch_deleted.status_code == 404


@pytest.mark.asyncio
async def test_import_paste_autodetects_metadata_and_returns_duplicate_conflict(
    override_import_pipeline: PipelineService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/paste",
            json={
                "title": "",
                "chapter_number": 1,
                "chapter_title": "",
                "text": "《Yong Ye [raw]》\n第12章 雪夜来客\n秦铭推开门。",
            },
            headers=headers,
        )
        duplicate = await client.post(
            "/api/import/paste",
            json={
                "title": "Yong-Ye",
                "chapter_number": 12,
                "chapter_title": "雪夜来客",
                "text": "《Yong Ye》\n第十二章 雪夜来客\n秦铭推开门。",
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    book = get_book_by_title(override_import_pipeline.db_path, "Yong Ye")
    assert book is not None
    assert payload["book_id"] == book["id"]
    assert payload["chapter_number"] == 12
    assert payload["chapter_title"] == "雪夜来客"
    assert duplicate.status_code == 409


def test_add_url_note_writes_under_pipeline_data_dir(
    temp_pipeline: PipelineService,
) -> None:
    book_id = temp_pipeline.add_url_note("URL Book", "https://example.invalid/ch1", "note")

    chapters = temp_pipeline.list_chapters(book_id)
    assert len(chapters) == 1
    raw_path = Path(chapters[0]["raw_text_path"])
    assert temp_pipeline.data_dir in raw_path.parents
    assert "https://example.invalid/ch1" in raw_path.read_text(encoding="utf-8")
