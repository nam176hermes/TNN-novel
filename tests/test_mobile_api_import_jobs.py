from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, JobStatus, TaskStage
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.services.import_job_runtime import BoundedTaskRunner, RetryPolicy
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

            failed = await client.get(f"/api/import/jobs/{job_id}", headers=headers)
            assert failed.status_code == 200
            assert failed.json()["status"] == "failed"
            assert failed.json()["tasks"][0]["status"] == "failed"

            retried = await client.post(f"/api/import/jobs/{job_id}/retry-failed", headers=headers)
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "queued"
            reconciled = await client.get(f"/api/import/jobs/{job_id}", headers=headers)
            assert reconciled.json()["status"] == "succeeded", reconciled.text
            assert reconciled.json()["tasks"][0]["status"] == "succeeded"

            retried_again = await client.post(f"/api/import/jobs/{job_id}/retry-failed", headers=headers)
            assert retried_again.status_code == 200
            assert retried_again.json()["status"] == "succeeded"
    finally:
        _clear_import_job_service_override()

    paused = _service(temp_db_path, paused=True)
    _override_import_job_service(paused)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            created = await client.post("/api/import/jobs", json=_payload(chapters=1), headers=headers)
            job_id = created.json()["job_id"]
            first = await client.post(f"/api/import/jobs/{job_id}/cancel", headers=headers)
            second = await client.post(f"/api/import/jobs/{job_id}/cancel", headers=headers)
            assert first.status_code == second.status_code == 200
            assert first.json()["status"] == second.json()["status"] == "cancelled"
    finally:
        _clear_import_job_service_override()


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


@pytest.mark.asyncio
async def test_legacy_url_fetch_uses_durable_job_engine(temp_db_path: Path) -> None:
    service = _service(temp_db_path)
    _override_import_job_service(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post("/api/import/url/fetch", json=_payload(chapters=2), headers=headers)
    finally:
        _clear_import_job_service_override()

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert response.json()["succeeded"] == 2
    with sqlite3.connect(service.repository.db_path) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0])
    assert count == 1


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


def test_api_runner_drains_multiple_bounded_batches(temp_db_path: Path) -> None:
    service = _service(temp_db_path)
    service.bounded_runner = BoundedTaskRunner(
        direct_global_limit=2,
        direct_per_host_limit=1,
        browser_global_limit=1,
        max_queue_size=2,
    )
    job = service.create_job(
        owner_user_id="operator-a",
        source="69shuba",
        source_url="https://www.69shuba.com/book/1",
        tasks=[
            {
                "canonical_identity": f"69shuba:chapter-{number}",
                "canonical_chapter_url": f"https://www.69shuba.com/book/1/chapter/{number}",
                "chapter_number": number,
                "title": f"Chương {number}",
            }
            for number in range(1, 4)
        ],
    )
    service.enqueue_job(job.id, "operator-a")

    completed = import_routes._run_import_job_until_idle(service, job.id, "operator-a")

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.succeeded_count == 3
