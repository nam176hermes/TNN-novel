from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.database.db import get_chapter, init_db
from app.database.db import list_operational_events
from app.ingestion.source_adapters import SourceBlockedError, SourceChapterContent
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
async def test_preview_source_url_endpoint_returns_adapter_preview(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    pipeline = FakePreviewPipeline()
    app.dependency_overrides[import_routes.get_pipeline] = lambda: pipeline

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    service = RecordingImportJobService()
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
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
async def test_import_source_url_endpoint_rejects_unknown_source_domain(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = RecordingImportJobService()
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
async def test_import_source_url_endpoint_rejects_mixed_source_domains(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = RecordingImportJobService()
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
async def test_import_source_url_endpoint_rejects_same_source_other_book(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = RecordingImportJobService()
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
