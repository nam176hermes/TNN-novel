from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3

import httpx
import pytest
from fastapi import BackgroundTasks

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, JobStatus, TaskStage
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.runtime_status import WorkerRuntimeStatus
from app.services.import_job_runtime import RetryPolicy
from app.services.import_job_service import ImportJobService, TaskImportOutcome


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


class SuccessfulPipeline:
    def run_stage(self, stage, task, *, cancel_check):
        assert not cancel_check()
        if stage is TaskStage.IMPORTING:
            return TaskImportOutcome(
                text_length=120 + task.chapter_number,
                content_hash=f"hash-{task.chapter_number}",
                fetch_method="direct_http",
                elapsed_ms=12,
            )
        return None


class PausedImportJobService(ImportJobService):
    def run_job(self, job_id: str, owner_user_id: str):
        return self.get_job(job_id, owner_user_id)


class FailOncePipeline(SuccessfulPipeline):
    def __init__(self) -> None:
        self.failed = False

    def run_stage(self, stage, task, *, cancel_check):
        if stage is TaskStage.FETCHING and not self.failed:
            self.failed = True
            raise SourceAdapterError(
                "Temporary source failure",
                code=FetchErrorCode.SOURCE_UNAVAILABLE,
                retryable=True,
            )
        return super().run_stage(stage, task, cancel_check=cancel_check)


def _service(
    db_path: Path,
    pipeline=None,
    *,
    paused: bool = False,
) -> ImportJobService:
    init_db(db_path)
    service_type = PausedImportJobService if paused else ImportJobService
    return service_type(
        ImportJobRepository(db_path),
        worker_id="api-test-worker",
        pipeline=pipeline or SuccessfulPipeline(),
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0),
        sleep=lambda _seconds: None,
        random_value=lambda: 0.5,
    )


def _payload(*, chapters: int = 2) -> dict:
    return {
        "source_url": "https://www.69shuba.com/book/1",
        "title": "Phàm Nhân Tu Tiên",
        "author": "Vong Ngữ",
        "source": "69shuba",
        "chapters": [
            {
                "url": f"https://www.69shuba.com/book/1/chapter/{number}",
                "chapter_number": number,
                "title": f"Chương {number}",
            }
            for number in range(1, chapters + 1)
        ],
    }


def _override_import_job_service(service: ImportJobService) -> None:
    dependency = getattr(import_routes, "get_import_job_service", None)
    if dependency is not None:
        app.dependency_overrides[dependency] = lambda: service


def _clear_import_job_service_override() -> None:
    dependency = getattr(import_routes, "get_import_job_service", None)
    if dependency is not None:
        app.dependency_overrides.pop(dependency, None)


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


@pytest.mark.asyncio
async def test_create_get_cancel_and_retry_import_jobs(temp_db_path: Path) -> None:
    service = _service(temp_db_path, FailOncePipeline())
    _override_import_job_service(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            created = await client.post("/api/import/jobs", json=_payload(chapters=1), headers=headers)
            assert created.status_code == 202, created.text
            job_id = created.json()["job_id"]
            stored_job = service.repository.get_job_internal(job_id)
            assert stored_job is not None
            assert stored_job.owner_user_id
            assert stored_job.owner_user_id != "other-owner"

            # A worker, not the request handler, performs durable work.
            service.run_job(job_id, stored_job.owner_user_id)

            failed = await client.get(f"/api/import/jobs/{job_id}", headers=headers)
            assert failed.status_code == 200
            assert failed.json()["status"] == "failed"
            assert failed.json()["tasks"][0]["status"] == "failed"

            retried = await client.post(f"/api/import/jobs/{job_id}/retry-failed", headers=headers)
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "queued"
            service.run_job(job_id, stored_job.owner_user_id)
            reconciled = await client.get(f"/api/import/jobs/{job_id}", headers=headers)
            assert reconciled.json()["status"] == "succeeded", reconciled.text
            assert reconciled.json()["tasks"][0]["status"] == "succeeded"

            retried_again = await client.post(f"/api/import/jobs/{job_id}/retry-failed", headers=headers)
            assert retried_again.status_code == 200
            assert retried_again.json()["status"] == "succeeded"
    finally:
        _clear_import_job_service_override()


@pytest.mark.asyncio
async def test_jobs_endpoint_always_leaves_execution_to_worker(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(temp_db_path)
    _override_import_job_service(service)
    original_add_task = BackgroundTasks.add_task

    def reject_durable_runner(self, func, *args, **kwargs):
        if func is import_routes._run_import_job_until_idle:
            raise AssertionError("API must not schedule the durable import runner")
        return original_add_task(self, func, *args, **kwargs)

    def reject_api_runner(*_args, **_kwargs):
        raise AssertionError("API must not run durable import jobs")

    monkeypatch.setattr(BackgroundTasks, "add_task", reject_durable_runner)
    monkeypatch.setattr(service, "run_job", reject_api_runner)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            created = await client.post("/api/import/jobs", json=_payload(chapters=1), headers=headers)
    finally:
        _clear_import_job_service_override()

    assert created.status_code == 202
    job = service.repository.get_job_internal(created.json()["job_id"])
    assert job is not None
    assert job.status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_retry_failed_endpoint_never_schedules_api_background_runner(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(temp_db_path, FailOncePipeline())
    _override_import_job_service(service)
    original_add_task = BackgroundTasks.add_task

    def reject_durable_runner(self, func, *args, **kwargs):
        if func is import_routes._run_import_job_until_idle:
            raise AssertionError("API must not schedule retry execution")
        return original_add_task(self, func, *args, **kwargs)

    def reject_api_runner(*_args, **_kwargs):
        raise AssertionError("API must not run retried durable work")

    monkeypatch.setattr(BackgroundTasks, "add_task", reject_durable_runner)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            created = await client.post("/api/import/jobs", json=_payload(chapters=1), headers=headers)
            job_id = created.json()["job_id"]
            owner_user_id = service.repository.get_job_internal(job_id).owner_user_id
            service.run_job(job_id, owner_user_id)
            assert service.get_job(job_id, owner_user_id).status is JobStatus.FAILED
            monkeypatch.setattr(service, "run_job", reject_api_runner)
            response = await client.post(f"/api/import/jobs/{job_id}/retry-failed", headers=headers)
    finally:
        _clear_import_job_service_override()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    task = service.list_tasks(job_id, owner_user_id)[0]
    assert task.status.value == "queued"


@pytest.mark.asyncio
async def test_import_job_endpoints_enforce_owner_isolation(temp_db_path: Path) -> None:
    service = _service(temp_db_path, paused=True)
    other = service.create_job(
        owner_user_id="other-owner",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[
            {
                "canonical_identity": "69shuba:chapter-1",
                "canonical_chapter_url": "https://www.69shuba.com/book/1/chapter/1",
                "chapter_number": 1,
                "title": "Chương 1",
            }
        ],
    )
    _override_import_job_service(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            responses = [
                await client.get(f"/api/import/jobs/{other.id}", headers=headers),
                await client.get(f"/api/import/jobs/{other.id}/events", headers=headers),
                await client.post(f"/api/import/jobs/{other.id}/cancel", headers=headers),
                await client.post(f"/api/import/jobs/{other.id}/retry-failed", headers=headers),
            ]
    finally:
        _clear_import_job_service_override()

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert all(response.json()["detail"]["code"] == "job_not_found" for response in responses)


@pytest.mark.asyncio
async def test_import_job_create_validates_url_and_chapter_quota(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(temp_db_path, paused=True)
    _override_import_job_service(service)
    monkeypatch.setattr(mobile_settings, "import_job_max_chapters", 1, raising=False)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            quota = await client.post("/api/import/jobs", json=_payload(chapters=2), headers=headers)
            private_payload = _payload(chapters=1)
            private_payload["source_url"] = "http://127.0.0.1/book/1"
            private_payload["chapters"][0]["url"] = "http://127.0.0.1/book/1/chapter/1"
            blocked = await client.post("/api/import/jobs", json=private_payload, headers=headers)
    finally:
        _clear_import_job_service_override()

    assert quota.status_code == 422
    assert quota.json()["detail"]["code"] == "chapter_quota_exceeded"
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "private_network_blocked"


def _sse_data(response: httpx.Response) -> list[dict]:
    payloads: list[dict] = []
    for block in response.text.split("\n\n"):
        data_line = next((line for line in block.splitlines() if line.startswith("data: ")), "")
        if data_line:
            payloads.append(json.loads(data_line[6:]))
    return payloads


@pytest.mark.asyncio
async def test_sse_orders_events_reconnects_and_finishes_for_terminal_job(temp_db_path: Path) -> None:
    service = _service(temp_db_path)
    _override_import_job_service(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            created = await client.post("/api/import/jobs", json=_payload(chapters=2), headers=headers)
            job_id = created.json()["job_id"]
            owner_user_id = service.repository.get_job_internal(job_id).owner_user_id
            service.run_job(job_id, owner_user_id)
            stream = await client.get(f"/api/import/jobs/{job_id}/events", headers=headers)
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            events = _sse_data(stream)
            sequences = [event["sequence"] for event in events]
            assert sequences == sorted(sequences)
            assert len(sequences) == len(set(sequences))
            assert events[-1]["data"]["status"] == "succeeded"
            assert all(event["type"] for event in events)
            assert all("html" not in json.dumps(event).lower() for event in events)

            cursor = sequences[-2]
            reconnected = await client.get(
                f"/api/import/jobs/{job_id}/events?cursor={cursor}",
                headers=headers,
            )
            assert [event["sequence"] for event in _sse_data(reconnected)] == [sequences[-1]]

            header_reconnected = await client.get(
                f"/api/import/jobs/{job_id}/events",
                headers={**headers, "Last-Event-ID": str(cursor)},
            )
            assert [event["sequence"] for event in _sse_data(header_reconnected)] == [sequences[-1]]
    finally:
        _clear_import_job_service_override()


@pytest.mark.asyncio
async def test_sse_disconnect_does_not_cancel_job(temp_db_path: Path) -> None:
    service = _service(temp_db_path, paused=True)
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[
            {
                "canonical_identity": "69shuba:chapter-1",
                "canonical_chapter_url": "https://www.69shuba.com/book/1/chapter/1",
                "chapter_number": 1,
                "title": "Chương 1",
            }
        ],
    )
    service.enqueue_job(job.id, "operator-a")

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    stream = import_routes._stream_import_job_events(
        DisconnectedRequest(),
        service,
        job.id,
        "operator-a",
        cursor=0,
    )
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    unchanged = service.get_job(job.id, "operator-a")
    assert unchanged.status is JobStatus.QUEUED
    assert unchanged.cancel_requested_at == ""


@pytest.mark.asyncio
async def test_sse_sends_keepalive_while_nonterminal(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(temp_db_path, paused=True)
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[],
    )
    service.enqueue_job(job.id, "operator-a")
    cursor = service.list_events(job.id, "operator-a")[-1].sequence
    monkeypatch.setattr(import_routes, "IMPORT_JOB_SSE_KEEPALIVE_SECONDS", 0.0)

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    stream = import_routes._stream_import_job_events(
        ConnectedRequest(),
        service,
        job.id,
        "operator-a",
        cursor=cursor,
    )
    assert await anext(stream) == ": keepalive\n\n"
    await stream.aclose()


class ApiOnlyImportJobService(ImportJobService):
    def run_job(self, job_id: str, owner_user_id: str):
        raise AssertionError("API must not execute durable import work")


@pytest.mark.asyncio
async def test_legacy_url_fetch_waits_for_external_worker_without_draining(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    api_service = ApiOnlyImportJobService(
        ImportJobRepository(temp_db_path),
        worker_id="api-test-worker",
        pipeline=SuccessfulPipeline(),
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0),
        sleep=lambda _seconds: None,
        random_value=lambda: 0.5,
    )
    worker_service = _service(temp_db_path)
    original_enqueue = api_service.enqueue_job

    def enqueue_and_wake_worker(job_id: str, owner_user_id: str):
        job = original_enqueue(job_id, owner_user_id)
        asyncio.get_running_loop().create_task(asyncio.to_thread(worker_service.run_job, job_id, owner_user_id))
        return job

    api_service.enqueue_job = enqueue_and_wake_worker
    _override_import_job_service(api_service)
    _override_ready_worker()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post("/api/import/url/fetch", json=_payload(chapters=2), headers=headers)
    finally:
        _clear_import_job_service_override()
        _clear_worker_runtime_override()

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert response.json()["succeeded"] == 2
    with sqlite3.connect(api_service.repository.db_path) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0])
    assert count == 1


@pytest.mark.asyncio
async def test_legacy_url_fetch_timeout_cancels_job_and_returns_safe_504(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    service = ApiOnlyImportJobService(
        ImportJobRepository(temp_db_path),
        worker_id="api-test-worker",
        pipeline=SuccessfulPipeline(),
    )
    _override_import_job_service(service)
    _override_ready_worker()
    monkeypatch.setattr(mobile_settings, "import_job_sync_wait_timeout_seconds", 0.01)
    monkeypatch.setattr(mobile_settings, "import_job_wait_poll_seconds", 0.001)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post("/api/import/url/fetch", json=_payload(chapters=1), headers=headers)
    finally:
        _clear_import_job_service_override()
        _clear_worker_runtime_override()

    assert response.status_code == 504, response.text
    assert response.json()["detail"]["code"] == "import_job_timed_out"
    with sqlite3.connect(temp_db_path) as connection:
        job_id = str(connection.execute("SELECT id FROM import_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    stored = service.repository.get_job_internal(job_id)
    assert stored is not None
    assert stored.status is JobStatus.CANCELLED


def test_import_job_openapi_documents_json_and_sse_contracts() -> None:
    schema = app.openapi()
    assert schema["paths"]["/api/import/jobs"]["post"]["responses"]["202"]
    event_response = schema["paths"]["/api/import/jobs/{job_id}/events"]["get"]["responses"]["200"]
    assert "text/event-stream" in event_response["content"]
    assert {
        "ImportJobCreateRequest",
        "ImportJobAcceptedResponse",
        "ImportJobSnapshotResponse",
        "ImportJobErrorResponse",
    }.issubset(schema["components"]["schemas"])
