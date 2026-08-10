from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import BackgroundTasks

from app.database.db import get_chapter, init_db, list_operational_events, update_managed_source
from app.database.import_jobs import ImportJobRepository, JobStatus
from app.ingestion.managed_sources import import_selected_catalog_sources
from app.ingestion.source_adapters import SourceChapterContent
from app.ingestion.source_catalog import import_source_catalog_json
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.mobile_api.services.pipeline_service import PipelineService
from app.runtime_status import WorkerRuntimeStatus
from app.services.import_job_factory import create_import_job_service
from app.services.import_job_quotas import ImportJobQuotaPolicy
from app.services.import_job_service import ImportJobService


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


class NeverRunPipeline:
    def run_stage(self, *_args, **_kwargs):
        raise AssertionError("URL start routes must not execute import work")

    def release_task(self, _task_id: int) -> None:
        return None


def _durable_service(
    db_path: Path,
    *,
    quota_policy: ImportJobQuotaPolicy | None = None,
) -> ImportJobService:
    return ImportJobService(
        ImportJobRepository(db_path),
        worker_id="api-test-worker",
        pipeline=NeverRunPipeline(),
        quota_policy=quota_policy,
    )


def _override_import_job_service(service: ImportJobService) -> None:
    app.dependency_overrides[import_routes.get_import_job_service] = lambda: service


def _clear_import_job_service_override() -> None:
    app.dependency_overrides.pop(import_routes.get_import_job_service, None)


def _override_ready_worker() -> None:
    app.dependency_overrides[import_routes.get_import_worker_runtime] = lambda: WorkerRuntimeStatus(
        status="ready",
        required=True,
        heartbeat_age_seconds=0.0,
        release_id="test",
        release_match=True,
        queue_claim_capable=True,
        reason="ready",
    )


def _clear_worker_runtime_override() -> None:
    app.dependency_overrides.pop(import_routes.get_import_worker_runtime, None)


def _external_worker_service(db_path: Path, pipeline: object) -> ImportJobService:
    api_service = create_import_job_service(
        worker_id="api-test-worker",
        pipeline=pipeline,
        db_path=db_path,
    )
    worker_service = create_import_job_service(
        worker_id="worker-test-worker",
        pipeline=pipeline,
        db_path=db_path,
    )
    original_enqueue = api_service.enqueue_job

    def enqueue_and_wake_worker(job_id: str, owner_user_id: str):
        job = original_enqueue(job_id, owner_user_id)
        asyncio.get_running_loop().create_task(asyncio.to_thread(worker_service.run_job, job_id, owner_user_id))
        return job

    api_service.enqueue_job = enqueue_and_wake_worker
    return api_service


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
async def test_legacy_url_endpoint_returns_durable_job_without_jobservice(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)
    from app.mobile_api.services.job_service import JobService

    def reject_legacy_job_service(*_args, **_kwargs):
        raise AssertionError("legacy JobService must not start URL imports")

    monkeypatch.setattr(JobService, "start_import_url_job", reject_legacy_job_service)

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
        _clear_import_job_service_override()

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    stored = service.repository.get_job_internal(response.json()["job_id"])
    assert stored is not None
    assert stored.status is JobStatus.QUEUED
    assert stored.owner_user_id
    assert stored.source_url == "https://www.69shuba.com/book/1"
    assert stored.config_snapshot["title"] == "凡人修仙传"
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "import_start")
    assert event["job_id"] == response.json()["job_id"]
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
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

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
        _clear_import_job_service_override()

    assert response.status_code == 400
    assert "Only VERIFIED sources" in response.text
    assert service.repository.count_active_jobs("admin") == 0


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_unknown_source_domain(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

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
        _clear_import_job_service_override()

    assert response.status_code == 400
    assert "Unsupported source domain" in response.text
    assert service.repository.count_active_jobs("admin") == 0


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_mixed_source_domains(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

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
        _clear_import_job_service_override()

    assert response.status_code == 400
    assert "same supported source" in response.text
    assert service.repository.count_active_jobs("admin") == 0


@pytest.mark.asyncio
async def test_import_source_url_endpoint_rejects_same_source_other_book(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

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
        _clear_import_job_service_override()

    assert response.status_code == 400
    assert "same source book" in response.text
    assert service.repository.count_active_jobs("admin") == 0


@pytest.mark.asyncio
async def test_legacy_url_endpoint_rejects_duplicate_chapters_before_persisting_job(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "Duplicate chapters",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {"chapter_number": 1, "title": "One", "url": "https://www.69shuba.com/book/1/chapter/1"},
                        {"chapter_number": 2, "title": "Again", "url": "https://www.69shuba.com/book/1/chapter/1"},
                    ],
                },
                headers=headers,
            )
    finally:
        _clear_import_job_service_override()

    assert response.status_code == 409
    assert response.headers["x-novel-fetch-error-code"] == "duplicate"
    assert response.json()["detail"] == "Duplicate chapter selection"
    with sqlite3.connect(temp_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chapter_tasks").fetchone()[0] == 0
    assert any(event["event_type"] == "import_failure" for event in list_operational_events(temp_db_path, limit=10, severities=()))


@pytest.mark.asyncio
async def test_legacy_url_endpoint_maps_chapter_quota_without_persisting_job(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path, quota_policy=ImportJobQuotaPolicy(max_chapters_per_job=1))
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)

    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "Over chapter quota",
                    "managed_source_id": managed_source_id,
                    "chapters": [
                        {"chapter_number": 1, "title": "One", "url": "https://www.69shuba.com/book/1/chapter/1"},
                        {"chapter_number": 2, "title": "Two", "url": "https://www.69shuba.com/book/1/chapter/2"},
                    ],
                },
                headers=headers,
            )
    finally:
        _clear_import_job_service_override()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "chapter_quota_exceeded"
    with sqlite3.connect(temp_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chapter_tasks").fetchone()[0] == 0
    assert any(event["event_type"] == "import_failure" for event in list_operational_events(temp_db_path, limit=10, severities=()))


@pytest.mark.asyncio
async def test_legacy_url_endpoint_maps_active_job_quota_without_extra_job(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path, quota_policy=ImportJobQuotaPolicy(max_active_jobs_per_owner=1))
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)
    payload = {
        "url": "https://www.69shuba.com/book/1",
        "title": "Active quota",
        "managed_source_id": managed_source_id,
        "chapters": [{"chapter_number": 1, "title": "One", "url": "https://www.69shuba.com/book/1/chapter/1"}],
    }

    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            first = await client.post("/api/import/url", json=payload, headers=headers)
            response = await client.post("/api/import/url", json=payload, headers=headers)
    finally:
        _clear_import_job_service_override()

    assert first.status_code == 200
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "active_job_quota_exceeded"
    with sqlite3.connect(temp_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chapter_tasks").fetchone()[0] == 1
    assert any(event["event_type"] == "import_failure" for event in list_operational_events(temp_db_path, limit=10, severities=()))


@pytest.mark.asyncio
async def test_all_url_routes_leave_durable_jobs_for_external_worker(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    managed_source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service = _durable_service(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    _override_import_job_service(service)
    original_add_task = BackgroundTasks.add_task

    def reject_durable_runner(self, func, *args, **kwargs):
        if getattr(func, "__name__", "") == "_run_import_job_until_idle":
            raise AssertionError("API must not schedule durable URL execution")
        return original_add_task(self, func, *args, **kwargs)

    def reject_api_runner(*_args, **_kwargs):
        raise AssertionError("API must not execute durable URL work")

    monkeypatch.setattr(BackgroundTasks, "add_task", reject_durable_runner)
    monkeypatch.setattr(service, "run_job", reject_api_runner)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            jobs = await client.post(
                "/api/import/jobs",
                json={
                    "source_url": "https://www.69shuba.com/book/1",
                    "title": "Durable jobs",
                    "chapters": [{"url": "https://www.69shuba.com/book/1/chapter/1", "chapter_number": 1}],
                },
                headers=headers,
            )
            legacy = await client.post(
                "/api/import/url",
                json={
                    "url": "https://www.69shuba.com/book/1",
                    "title": "Durable legacy",
                    "managed_source_id": managed_source_id,
                    "chapters": [{"url": "https://www.69shuba.com/book/1/chapter/2", "chapter_number": 2}],
                },
                headers=headers,
            )
    finally:
        _clear_import_job_service_override()

    assert jobs.status_code == 202, jobs.text
    assert legacy.status_code == 200, legacy.text
    stored = [
        service.repository.get_job_internal(jobs.json()["job_id"]),
        service.repository.get_job_internal(legacy.json()["job_id"]),
    ]
    assert all(job is not None and job.status is JobStatus.QUEUED for job in stored)


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
    service = _external_worker_service(temp_db_path, pipeline)
    _override_import_job_service(service)
    _override_ready_worker()
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
        _clear_import_job_service_override()
        _clear_worker_runtime_override()

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
        def fetch_source_chapter(self, _url: str):
            raise RuntimeError("chapter body must never be returned")

    service = _external_worker_service(temp_db_path, FailingImportPipeline())
    _override_import_job_service(service)
    _override_ready_worker()
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
        _clear_import_job_service_override()
        _clear_worker_runtime_override()

    assert response.status_code == 200, response.text
    chapter = response.json()["chapters"][0]
    assert chapter["success"] is False
    assert chapter["error_code"] == "import_failed"
    assert chapter["retryable"] is False
    assert chapter["operation"] == "failed"
    assert chapter["started_at"]
    assert chapter["finished_at"]
    assert "chapter body" not in chapter["error"]
