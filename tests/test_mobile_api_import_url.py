from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.database.db import get_chapter, init_db, update_managed_source
from app.database.db import list_operational_events
from app.ingestion.managed_sources import import_selected_catalog_sources
from app.ingestion.source_adapters import SourceBlockedError, SourceChapterContent
from app.ingestion.source_catalog import import_source_catalog_json
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.mobile_api.services.pipeline_service import PipelineService


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


def _seed_verified_managed_source(temp_db_path: Path, tmp_path: Path) -> str:
    catalog_path = tmp_path / "url-import-catalog.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "1",
                    "name": "69 Source",
                    "url": "https://www.69shuba.com/book/1",
                    "tags": "搜",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    summary = import_selected_catalog_sources(temp_db_path, ["yckceo:1"])
    source_id = summary.items[0]["id"]
    update_managed_source(
        temp_db_path,
        source_id,
        status="VERIFIED",
        trust_level="HIGH",
        last_test_status="success",
        last_tested_at="2026-07-09T00:00:00+00:00",
        last_successful_fetch_at="2026-07-09T00:00:00+00:00",
        last_error="",
    )
    return source_id


class FakePreviewPipeline:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def preview_source_url(self, url: str) -> dict:
        self.urls.append(url)
        return {
            "adapter_id": "69shuba",
            "adapter_label": "69shuba",
            "source": "www.69shuba.com",
            "source_url": url,
            "title": "凡人修仙传",
            "author": "忘语",
            "description": "修仙小说",
            "cover_url": "",
            "policy": {
                "source_id": "69shuba",
                "label": "69shuba",
                "delay_seconds": 8,
                "max_concurrency": 1,
                "retry_limit": 2,
            },
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第一章 山边小村",
                    "url": "https://www.69shuba.com/book/1/chapter/1",
                }
            ],
            "chapter_count": 1,
        }


class RecordingImportJobService:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def start_import_url_job(self, **kwargs) -> str:
        self.kwargs = kwargs
        return "job-import-url"


class BlockedPreviewPipeline:
    def preview_source_url(self, url: str) -> dict:
        raise SourceBlockedError("Source captcha or Cloudflare challenge detected")


class ExplodingPreviewPipeline:
    def preview_source_url(self, url: str) -> dict:
        raise RuntimeError("preview crashed at /tmp/provider-secret/cache.json")


@pytest.mark.asyncio
async def test_list_import_sources_endpoint_returns_backend_policy_table(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/import/sources", headers=headers)

    assert response.status_code == 200
    sources = {source["source_id"]: source for source in response.json()["sources"]}
    assert sources["69shuba"]["adapter_id"] == "69shuba"
    assert sources["22biqu"]["adapter_id"] == "biquge"
    assert sources["22biqu"]["domains"] == ["22biqu.com"]
    assert sources["69shuba"]["delay_seconds"] == 8


@pytest.mark.asyncio
async def test_preview_source_url_endpoint_returns_adapter_preview(temp_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_db(temp_db_path)
    source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    pipeline = FakePreviewPipeline()
    app.dependency_overrides[import_routes.get_pipeline] = lambda: pipeline
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": "https://www.69shuba.com/book/1"},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 200
    assert response.json()["title"] == "凡人修仙传"
    assert response.json()["policy"]["source_id"] == "69shuba"
    assert response.json()["chapters"][0]["chapter_number"] == 1
    assert response.json()["managed_source_id"] == source_id
    assert response.json()["managed_source_status"] == "VERIFIED"
    assert response.json()["automation_allowed"] is True
    assert pipeline.urls == ["https://www.69shuba.com/book/1"]


@pytest.mark.asyncio
async def test_preview_source_url_endpoint_returns_blocked_source_error(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    app.dependency_overrides[import_routes.get_pipeline] = lambda: BlockedPreviewPipeline()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": "https://www.69shuba.com/book/58851.htm"},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 400
    assert "Cloudflare challenge" in response.text
    assert response.headers["X-Novel-Fetch-Error-Code"] == "user_verification_required"
    assert response.headers["X-Novel-Fetch-Retryable"] == "0"


@pytest.mark.asyncio
async def test_preview_source_url_endpoint_marks_unmanaged_sources_as_not_automatable(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    pipeline = FakePreviewPipeline()
    app.dependency_overrides[import_routes.get_pipeline] = lambda: pipeline
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": "https://www.69shuba.com/book/1"},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 200
    assert response.json()["automation_allowed"] is False
    assert "chưa được nhập vào Source Hub" in response.json()["automation_reason"]


@pytest.mark.asyncio
async def test_preview_source_url_endpoint_sanitizes_internal_errors(
    temp_db_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_pipeline] = lambda: ExplodingPreviewPipeline()

    try:
        transport = httpx.ASGITransport(app=app)
        with caplog.at_level("WARNING"):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await auth_headers(client)
                response = await client.post(
                    "/api/import/url/preview",
                    json={"url": "https://www.69shuba.com/book/58851.htm"},
                    headers=headers,
                )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 502
    assert response.json()["detail"] == "Source preview failed. Check the source URL and server logs."
    assert "/tmp/provider-secret" not in response.text
    assert "preview crashed at /tmp/provider-secret/cache.json" in caplog.text
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "import_failure")
    assert event["details"]["import_type"] == "url_preview"
    assert "/tmp/provider-secret" not in str(event)


@pytest.mark.asyncio
async def test_preview_source_url_endpoint_offloads_blocking_preview(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    pipeline = FakePreviewPipeline()
    app.dependency_overrides[import_routes.get_pipeline] = lambda: pipeline
    offloaded_calls = 0

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal offloaded_calls
        offloaded_calls += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": "https://www.69shuba.com/book/1"},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 200
    assert offloaded_calls == 1
    assert pipeline.urls == ["https://www.69shuba.com/book/1"]


@pytest.mark.asyncio
async def test_import_source_url_endpoint_starts_background_job(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = RecordingImportJobService()
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "凡人修仙传",
                    "author": "忘语",
                    "source": "www.69shuba.com",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "第一章 山边小村",
                            "url": "https://www.69shuba.com/book/1/chapter/1",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_job_service, None)

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-import-url"
    assert service.kwargs == {
        "url": "https://www.69shuba.com/book/1",
        "managed_source_id": managed_source_id,
        "title": "凡人修仙传",
        "author": "忘语",
        "source": "www.69shuba.com",
        "chapters": [
            {
                "url": "https://www.69shuba.com/book/1/chapter/1",
                "chapter_number": 1,
                "title": "第一章 山边小村",
            }
        ],
        "retry_limit": 2,
    }
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "import_start")
    assert event["job_id"] == "job-import-url"
    assert event["details"]["import_type"] == "url"
    assert event["details"]["chapter_count"] == 1


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_unverified_managed_source(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    catalog_path = tmp_path / "url-import-catalog.json"
    catalog_path.write_text(
        json.dumps([{"id": "1", "name": "69 Source", "url": "https://www.69shuba.com/book/1", "tags": "搜"}], ensure_ascii=False),
        encoding="utf-8",
    )
    import_source_catalog_json(temp_db_path, catalog_path)
    summary = import_selected_catalog_sources(temp_db_path, ["yckceo:1"])
    managed_source_id = summary.items[0]["id"]
    service = RecordingImportJobService()
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "凡人修仙传",
                    "source": "www.69shuba.com",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "第一章 山边小村",
                            "url": "https://www.69shuba.com/book/1/chapter/1",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_job_service, None)

    assert response.status_code == 400
    assert "Only VERIFIED sources" in response.text
    assert service.kwargs is None


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_unknown_source_domain(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = RecordingImportJobService()
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://example.com/book/1",
                    "title": "凡人修仙传",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "第一章 山边小村",
                            "url": "https://example.com/book/1/chapter/1",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_job_service, None)

    assert response.status_code == 400
    assert "Unsupported source domain" in response.text
    assert service.kwargs is None


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_mixed_source_domains(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = RecordingImportJobService()
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "凡人修仙传",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "第一章 山边小村",
                            "url": "https://www.biquge.tw/book/1/chapter/1",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_job_service, None)

    assert response.status_code == 400
    assert "same supported source" in response.text
    assert service.kwargs is None


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_same_source_other_book(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = RecordingImportJobService()
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    app.dependency_overrides[import_routes.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1/",
                    "title": "凡人修仙传",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "第一章 山边小村",
                            "url": "https://www.69shuba.com/book/999/1.html",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_job_service, None)

    assert response.status_code == 400
    assert "same source book" in response.text
    assert service.kwargs is None


def test_url_import_groups_chapters_with_same_normalized_book_title(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    service = object.__new__(PipelineService)
    service.db_path = temp_db_path
    service.data_dir = tmp_path

    def fake_fetch_source_chapter(url: str) -> SourceChapterContent:
        chapter_number = 1 if url.endswith("/1") else 2
        return SourceChapterContent(
            adapter_id="69shuba",
            source="www.69shuba.com",
            source_url=url,
            chapter_number=chapter_number,
            title=f"第{chapter_number}章",
            text=f"第{chapter_number}章\n\n张铁进入山村。",
        )

    monkeypatch.setattr(service, "fetch_source_chapter", fake_fetch_source_chapter)

    first = service.import_from_source_url(
        book_title="Yong Ye [raw]",
        source_url="https://www.69shuba.com/book",
        chapter_url="https://www.69shuba.com/book/1",
        chapter_number=1,
        chapter_title="第一章",
    )
    second = service.import_from_source_url(
        book_title="Yong-Ye",
        source_url="https://www.69shuba.com/book",
        chapter_url="https://www.69shuba.com/book/2",
        chapter_number=2,
        chapter_title="第二章",
    )

    assert first["book_id"] == second["book_id"]
    first_chapter = get_chapter(temp_db_path, first["book_id"], 1)
    assert first_chapter is not None
    assert first_chapter["adapter_id"] == "69shuba"


@pytest.mark.asyncio
async def test_url_fetch_returns_stored_chapter_metadata_without_content(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    pipeline.legacy_artifact_root = None

    monkeypatch.setattr(
        pipeline,
        "fetch_source_chapter",
        lambda url: SourceChapterContent(
            adapter_id="69shuba",
            source="www.69shuba.com",
            source_url=url,
            chapter_number=1,
            title="Chương một",
            text="Nội dung chương có đủ độ dài để được lưu an toàn.",
            fetch_method="direct_http",
            fetch_attempts=1,
            fetch_elapsed_ms=123,
        ),
    )
    app.dependency_overrides[import_routes.get_pipeline] = lambda: pipeline
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/fetch",
                json={
                    "title": "Sách URL",
                    "source_url": "https://www.69shuba.com/book/1",
                    "chapters": [
                        {
                            "url": "https://www.69shuba.com/book/1/chapter/1",
                            "chapter_number": 1,
                            "title": "Chương một",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 200, response.text
    chapter = response.json()["chapters"][0]
    assert chapter["success"] is True
    assert chapter["text_length"] > 0
    assert chapter["stored_text_length"] == chapter["text_length"]
    assert chapter["content_hash"]
    assert chapter["operation"] == "created"
    assert chapter["error_code"] == ""
    assert chapter["retryable"] is False
    assert chapter["attempts"] == 1
    assert chapter["fetch_method"] == "direct_http"
    assert chapter["elapsed_ms"] == 123
    assert chapter["started_at"]
    assert chapter["finished_at"]
    assert "text" not in chapter


@pytest.mark.asyncio
async def test_url_fetch_import_failure_returns_typed_safe_metadata(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    class FailingImportPipeline:
        def import_from_source_url(self, **_: object) -> dict:
            raise RuntimeError("chapter body must never be returned")

    app.dependency_overrides[import_routes.get_pipeline] = FailingImportPipeline
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url/fetch",
                json={
                    "title": "Sách lỗi",
                    "chapters": [
                        {
                            "url": "https://www.69shuba.com/book/1/chapter/1",
                            "chapter_number": 1,
                            "title": "Chương lỗi",
                        }
                    ],
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)

    assert response.status_code == 200, response.text
    chapter = response.json()["chapters"][0]
    assert chapter["success"] is False
    assert chapter["error_code"] == "import_failed"
    assert chapter["retryable"] is False
    assert chapter["operation"] == "failed"
    assert chapter["started_at"]
    assert chapter["finished_at"]
    assert "chapter body" not in chapter["error"]
