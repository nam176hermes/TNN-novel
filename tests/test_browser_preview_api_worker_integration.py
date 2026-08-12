from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid

import httpx
import pytest
from starlette.requests import Request as StarletteRequest

from app.database.db import init_db, update_managed_source
from app.database.import_jobs import (
    BrowserResultPublicationRejected,
    ImportJob,
    ImportJobRepository,
    JobStatus,
)
from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
    PreviewBrowserPayload,
)
from app.import_worker import DurableImportWorker
from app.ingestion.managed_sources import import_selected_catalog_sources
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.ingestion.source_catalog import import_source_catalog_json
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.mobile_api.services import pipeline_service as pipeline_service_module
from app.mobile_api.services.import_job_wait_service import ImportJobWaitError, wait_for_terminal_import_job
from app.mobile_api.services.pipeline_service import PipelineService
from app.runtime_status import WorkerRuntimeStatus
from app.services.import_job_factory import create_import_job_service
from app.services.import_job_runtime import RetryPolicy
from app.services.import_job_service import ImportJobService


SOURCE_URL = "https://www.69shuba.com/book/1"
CHAPTER_URL = "https://www.69shuba.com/book/1/chapter/1"
PUBLISHED_OWNER = "published-preview-owner"


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _worker_runtime(*, status: str = "ready", capable: bool = True) -> WorkerRuntimeStatus:
    return WorkerRuntimeStatus(
        status=status,
        required=True,
        heartbeat_age_seconds=1.0 if status != "missing" else None,
        release_id="test-release" if status != "missing" else "unknown",
        release_match=status not in {"missing", "release_mismatch"},
        queue_claim_capable=capable,
        reason="ready" if capable else f"worker_{status}",
    )


class PreviewWorkerPipeline:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    def preview_source_url(self, url: str) -> dict[str, object]:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return {
            "adapter_id": "69shuba",
            "adapter_label": "69shuba",
            "adapter_version": "69shuba-test-v1",
            "parser_method": "fixture",
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
                    "url": CHAPTER_URL,
                }
            ],
            "bypass_used": False,
            "bypass_method": "",
            "fetch_method": "direct_http",
            "fetch_status_code": 200,
            "fetch_attempts": 1,
            "fetch_elapsed_ms": 17,
            "fetch_bytes_received": 321,
            "fetch_final_url": url,
            "fetch_cookies_refreshed": False,
            "fetch_cache_hit": False,
        }


def _worker_service(db_path: Path, pipeline: PreviewWorkerPipeline) -> ImportJobService:
    service = create_import_job_service(
        worker_id="preview-worker-test",
        pipeline=pipeline,  # type: ignore[arg-type]
        db_path=db_path,
    )
    service.retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0)
    return service


def _worker(service: ImportJobService, heartbeat_path: Path) -> DurableImportWorker:
    return DurableImportWorker(
        service,
        heartbeat_path=heartbeat_path,
        poll_interval_seconds=0.01,
        close_browser=lambda: None,
    )


def _seed_verified_managed_source(db_path: Path, tmp_path: Path) -> str:
    catalog_path = tmp_path / "preview-worker-catalog.json"
    catalog_path.write_text(
        json.dumps(
            [{"id": "1", "name": "69 Source", "url": SOURCE_URL, "tags": "搜"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import_source_catalog_json(db_path, catalog_path)
    summary = import_selected_catalog_sources(db_path, ["yckceo:1"])
    source_id = summary.items[0]["id"]
    update_managed_source(
        db_path,
        source_id,
        status="VERIFIED",
        trust_level="HIGH",
        last_test_status="success",
        last_tested_at="2026-08-10T00:00:00+00:00",
        last_successful_fetch_at="2026-08-10T00:00:00+00:00",
        last_error="",
    )
    return source_id


def _set_runtime_override(runtime: WorkerRuntimeStatus) -> None:
    dependency = getattr(import_routes, "get_import_worker_runtime", None)
    if dependency is not None:
        app.dependency_overrides[dependency] = lambda: runtime


def _clear_runtime_override() -> None:
    dependency = getattr(import_routes, "get_import_worker_runtime", None)
    if dependency is not None:
        app.dependency_overrides.pop(dependency, None)


def _set_service_override(service: object) -> None:
    app.dependency_overrides[import_routes.get_import_job_service] = lambda: service


def _clear_service_override() -> None:
    app.dependency_overrides.pop(import_routes.get_import_job_service, None)


def _raise_if_api_previews(_self: PipelineService, _url: str) -> dict:
    raise AssertionError("the API process must never execute source preview")


async def _post_preview_while_worker_runs(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    worker: DurableImportWorker,
    repository: ImportJobRepository,
) -> tuple[httpx.Response, int]:
    request_task = asyncio.create_task(
        client.post(
            "/api/import/url/preview",
            json={"url": SOURCE_URL},
            headers=headers,
        )
    )
    for _ in range(200):
        if repository.list_runnable_jobs(limit=1) or request_task.done():
            break
        await asyncio.sleep(0.005)
    processed = await asyncio.to_thread(worker.run_once)
    return await request_task, processed


class PublishedPreviewService:
    """Return one real worker-published row to isolate API result mapping."""

    def __init__(self, delegate: ImportJobService, job: ImportJob) -> None:
        self.delegate = delegate
        self.job = job
        self.repository = delegate.repository

    def create_job(self, **_kwargs: object) -> ImportJob:
        return self.job

    def enqueue_job(self, _job_id: str, _owner_user_id: str) -> ImportJob:
        return self.job

    def get_job(self, _job_id: str, _owner_user_id: str) -> ImportJob:
        return self.delegate.get_job(self.job.id, PUBLISHED_OWNER)

    def request_cancel(self, _job_id: str, _owner_user_id: str) -> ImportJob:
        return self.delegate.request_cancel(self.job.id, PUBLISHED_OWNER)


def _published_preview(
    db_path: Path,
    tmp_path: Path,
    *,
    pipeline: PreviewWorkerPipeline,
    expired: bool = False,
) -> tuple[PublishedPreviewService, ImportJob]:
    service = _worker_service(db_path, pipeline)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    if expired:
        deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    job = service.create_job(
        owner_user_id=PUBLISHED_OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[
            {
                "canonical_identity": f"69shuba:{SOURCE_URL}",
                "canonical_chapter_url": SOURCE_URL,
                "chapter_number": 0,
                "title": "",
            }
        ],
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=deadline.isoformat(),
        correlation_id=str(uuid.uuid4()),
    )
    service.enqueue_job(job.id, PUBLISHED_OWNER)
    assert _worker(service, tmp_path / f"{job.id}.heartbeat").run_once() == 1
    published = service.get_job(job.id, PUBLISHED_OWNER)
    assert published.result_snapshot is not None
    return PublishedPreviewService(service, published), published


@pytest.mark.asyncio
async def test_api_worker_preview_contract_matches_legacy_preview_fixture(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(pipeline_service_module, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    pipeline = PreviewWorkerPipeline()
    worker_service = _worker_service(temp_db_path, pipeline)
    preview_worker = _worker(worker_service, tmp_path / "preview-worker.heartbeat")
    _set_runtime_override(_worker_runtime())

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            response, processed = await _post_preview_while_worker_runs(
                client,
                headers=headers,
                worker=preview_worker,
                repository=worker_service.repository,
            )
    finally:
        _clear_runtime_override()

    assert processed == 1
    assert response.status_code == 200, response.text
    assert response.json() == {
        "adapter_id": "69shuba",
        "adapter_label": "69shuba",
        "source": "www.69shuba.com",
        "source_url": SOURCE_URL,
        "title": "凡人修仙传",
        "author": "忘语",
        "description": "修仙小说",
        "cover_url": "",
        "chapters": [
            {
                "chapter_number": 1,
                "title": "第一章 山边小村",
                "url": CHAPTER_URL,
            }
        ],
        "chapter_count": 1,
        "policy": {
            "source_id": "69shuba",
            "label": "69shuba",
            "delay_seconds": 8,
            "max_concurrency": 1,
            "retry_limit": 2,
        },
        "managed_source_id": "",
        "managed_source_status": "",
        "managed_source_trust_level": "",
        "automation_allowed": False,
        "automation_reason": "Nguồn này chưa được nhập vào Source Hub và xác minh.",
        "bypass_used": False,
        "bypass_method": "",
        "fetch_method": "direct_http",
        "fetch_status_code": 200,
        "fetch_attempts": 1,
        "fetch_elapsed_ms": 17,
        "fetch_bytes_received": 321,
        "fetch_final_url": SOURCE_URL,
        "fetch_cookies_refreshed": False,
        "fetch_cache_hit": False,
    }
    with sqlite3.connect(temp_db_path) as connection:
        row = connection.execute(
            "SELECT owner_user_id, operation_kind, total, correlation_id, deadline_at, result_state FROM import_jobs"
        ).fetchone()
    assert row is not None
    assert row[0]
    assert row[1] == "preview"
    assert row[2] == 1
    uuid.UUID(row[3])
    assert datetime.fromisoformat(row[4]) > datetime.now(timezone.utc)
    assert row[5] == "COMPLETED"
    assert pipeline.calls == [SOURCE_URL]


def test_stale_worker_result_cannot_overwrite_newer_preview_request(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    service = _worker_service(temp_db_path, PreviewWorkerPipeline())
    old_job = service.create_job(
        owner_user_id=PUBLISHED_OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[
            {
                "canonical_identity": f"old:69shuba:{SOURCE_URL}",
                "canonical_chapter_url": SOURCE_URL,
                "chapter_number": 0,
                "title": "Old preview",
            }
        ],
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        correlation_id="old-preview-request",
    )
    newer_job = service.create_job(
        owner_user_id=PUBLISHED_OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[
            {
                "canonical_identity": f"new:69shuba:{SOURCE_URL}",
                "canonical_chapter_url": SOURCE_URL,
                "chapter_number": 0,
                "title": "New preview",
            }
        ],
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        correlation_id="new-preview-request",
    )
    service.enqueue_job(old_job.id, PUBLISHED_OWNER)
    service.enqueue_job(newer_job.id, PUBLISHED_OWNER)
    running = service.repository.transition_job(newer_job.id, PUBLISHED_OWNER, JobStatus.RUNNING)
    claimed = service.repository.claim_next_task(
        newer_job.id,
        PUBLISHED_OWNER,
        worker_id="new-preview-worker",
    )
    assert claimed is not None

    stale_result = BrowserTaskResult(
        correlation_id="old-preview-request",
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload(
            adapter_id="69shuba",
            adapter_label="69shuba",
            source="www.69shuba.com",
            source_url=SOURCE_URL,
            title="Stale title",
        ),
    )
    with pytest.raises(BrowserResultPublicationRejected) as caught:
        service.repository.publish_browser_result(
            newer_job.id,
            PUBLISHED_OWNER,
            task_id=claimed.id,
            lease_token=claimed.lease_token,
            lease_owner=claimed.lease_owner,
            expected_job_version=running.version,
            expected_task_version=claimed.version,
            result=stale_result,
        )

    current = service.get_job(newer_job.id, PUBLISHED_OWNER)
    assert caught.value.code == "stale_lease"
    assert current.result_snapshot is None
    assert current.result_state is None


@pytest.mark.asyncio
async def test_preview_endpoint_never_calls_api_pipeline_preview(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    service, published = _published_preview(
        temp_db_path,
        tmp_path,
        pipeline=PreviewWorkerPipeline(),
    )
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    _set_runtime_override(_worker_runtime())
    _set_service_override(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": SOURCE_URL},
                headers=headers,
            )
    finally:
        _clear_service_override()
        _clear_runtime_override()

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "凡人修仙传"
    assert published.result_state is BrowserResultState.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_status", ["missing", "stale", "release_mismatch"])
async def test_preview_endpoint_returns_503_when_worker_missing_or_stale(
    worker_status: str,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(pipeline_service_module, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    _set_runtime_override(_worker_runtime(status=worker_status, capable=False))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": SOURCE_URL},
                headers=headers,
            )
    finally:
        _clear_runtime_override()

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "worker_unavailable",
        "retryable": True,
        "message": "Import worker is unavailable",
    }
    with sqlite3.connect(temp_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_preview_rejects_obfuscated_credential_query_before_durable_enqueue(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(pipeline_service_module, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    enqueue_attempts: list[str] = []

    class EnqueueMustNotBeReached:
        def create_job(self, **kwargs: object) -> ImportJob:
            enqueue_attempts.append(str(kwargs.get("source_url") or ""))
            raise AssertionError("credential query reached durable job creation")

    _set_service_override(EnqueueMustNotBeReached())  # type: ignore[arg-type]
    _set_runtime_override(_worker_runtime())
    cases = (
        ("apiKey", "ws1-route-camel-canary"),
        ("API-KEY", "ws1-route-hyphen-canary"),
        ("API.KEY", "ws1-route-dot-canary"),
        ("api%5Fkey", "ws1-route-percent-underscore-canary"),
        ("access%2Dtoken", "ws1-route-percent-token-canary"),
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            responses = [
                await client.post(
                    "/api/import/url/preview",
                    json={"url": f"{SOURCE_URL}?{query_key}={canary}"},
                    headers=headers,
                )
                for query_key, canary in cases
            ]
    finally:
        _clear_service_override()
        _clear_runtime_override()

    assert [response.status_code for response in responses] == [400] * len(cases)
    assert enqueue_attempts == []
    for response in responses:
        assert response.headers["X-Novel-Fetch-Error-Code"] == "invalid_url"
    with sqlite3.connect(temp_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chapter_tasks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM import_job_events").fetchone()[0] == 0
        durable_text: list[str] = []
        for table in ("import_jobs", "chapter_tasks", "import_job_events"):
            text_columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                if "TEXT" in str(row[2]).upper()
            ]
            selected = ", ".join(f'"{column}"' for column in text_columns)
            for row in connection.execute(f"SELECT {selected} FROM {table}").fetchall():
                durable_text.extend(str(value) for value in row if value is not None)
    persisted = "\n".join(durable_text)
    for query_key, canary in cases:
        assert query_key not in persisted
        assert canary not in persisted


@pytest.mark.asyncio
async def test_preview_endpoint_maps_blocked_failed_and_timed_out_results(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    _set_runtime_override(_worker_runtime())
    cases = [
        (
            PreviewWorkerPipeline(
                error=SourceAdapterError(
                    "Complete source verification in the worker browser",
                    code=FetchErrorCode.USER_VERIFICATION_REQUIRED,
                    retryable=False,
                    http_status=403,
                )
            ),
            False,
            403,
            "user_verification_required",
            "Complete source verification in the worker browser",
        ),
        (
            PreviewWorkerPipeline(error=RuntimeError("private provider exception")),
            False,
            502,
            "browser_task_failed",
            "Browser task failed",
        ),
        (
            PreviewWorkerPipeline(
                error=SourceAdapterError(
                    "The source is temporarily unavailable",
                    code=FetchErrorCode.SOURCE_UNAVAILABLE,
                    retryable=True,
                    http_status=503,
                )
            ),
            False,
            503,
            "source_unavailable",
            "The source is temporarily unavailable",
        ),
        (
            PreviewWorkerPipeline(),
            True,
            504,
            "browser_task_timed_out",
            "Browser task deadline exceeded",
        ),
    ]
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            for pipeline, expired, status_code, error_code, safe_message in cases:
                service, _published = _published_preview(
                    temp_db_path,
                    tmp_path,
                    pipeline=pipeline,
                    expired=expired,
                )
                _set_service_override(service)
                response = await client.post(
                    "/api/import/url/preview",
                    json={"url": SOURCE_URL},
                    headers=headers,
                )
                assert response.status_code == status_code, response.text
                if error_code in {"user_verification_required", "source_unavailable"}:
                    assert response.json()["detail"] == safe_message
                    assert response.headers["X-Novel-Fetch-Error-Code"] == error_code
                    assert response.headers["X-Novel-Fetch-Retryable"] == (
                        "1" if error_code == "source_unavailable" else "0"
                    )
                else:
                    assert response.json()["detail"] == {
                        "code": error_code,
                        "retryable": False,
                        "message": safe_message,
                    }
    finally:
        _clear_service_override()
        _clear_runtime_override()


@pytest.mark.asyncio
async def test_preview_disconnect_requests_durable_cancellation(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(pipeline_service_module, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    _set_runtime_override(_worker_runtime())
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            original = StarletteRequest.is_disconnected

            async def disconnected(request: StarletteRequest) -> bool:
                if request.url.path == "/api/import/url/preview":
                    return True
                return await original(request)

            monkeypatch.setattr(StarletteRequest, "is_disconnected", disconnected)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": SOURCE_URL},
                headers=headers,
            )
    finally:
        _clear_runtime_override()

    assert response.status_code == 499
    assert response.json()["detail"]["code"] == "client_disconnected"
    with sqlite3.connect(temp_db_path) as connection:
        row = connection.execute(
            "SELECT status, cancel_requested_at, result_state FROM import_jobs"
        ).fetchone()
        task = connection.execute(
            "SELECT status, lease_token, lease_owner FROM chapter_tasks"
        ).fetchone()
    assert row is not None and task is not None
    assert row[0] == "cancelled"
    assert row[1]
    assert row[2] == "CANCELLED"
    assert tuple(task) == ("cancelled", "", "")


@pytest.mark.asyncio
async def test_preview_result_keeps_managed_source_enrichment_in_api(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    source_id = _seed_verified_managed_source(temp_db_path, tmp_path)
    service, _published = _published_preview(
        temp_db_path,
        tmp_path,
        pipeline=PreviewWorkerPipeline(),
    )
    monkeypatch.setattr(import_routes, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(PipelineService, "preview_source_url", _raise_if_api_previews)
    _set_runtime_override(_worker_runtime())
    _set_service_override(service)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _auth_headers(client)
            response = await client.post(
                "/api/import/url/preview",
                json={"url": SOURCE_URL},
                headers=headers,
            )
    finally:
        _clear_service_override()
        _clear_runtime_override()

    assert response.status_code == 200, response.text
    assert response.json()["managed_source_id"] == source_id
    assert response.json()["managed_source_status"] == "VERIFIED"
    assert response.json()["managed_source_trust_level"] == "HIGH"
    assert response.json()["automation_allowed"] is True
    assert response.json()["automation_reason"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_kind", "expected_result_state"),
    [
        (ImportOperationKind.PREVIEW, BrowserResultState.TIMED_OUT),
        (ImportOperationKind.IMPORT_CHAPTERS, None),
    ],
)
async def test_wait_timeout_terminalizes_preview_and_cancels_chapter_import(
    operation_kind: ImportOperationKind,
    expected_result_state: BrowserResultState | None,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    service = _worker_service(temp_db_path, PreviewWorkerPipeline())
    kwargs: dict[str, object] = {}
    if operation_kind is ImportOperationKind.PREVIEW:
        kwargs = {
            "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        }
    job = service.create_job(
        owner_user_id=PUBLISHED_OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[
            {
                "canonical_identity": f"69shuba:{CHAPTER_URL}",
                "canonical_chapter_url": CHAPTER_URL,
                "chapter_number": 1,
                "title": "Chapter 1",
            }
        ],
        operation_kind=operation_kind,
        **kwargs,
    )
    service.enqueue_job(job.id, PUBLISHED_OWNER)

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    with pytest.raises(ImportJobWaitError, match="browser_task_timed_out"):
        await wait_for_terminal_import_job(
            ConnectedRequest(),  # type: ignore[arg-type]
            service,
            job.id,
            PUBLISHED_OWNER,
            timeout_seconds=0.000001,
            poll_seconds=0.001,
        )

    terminal = service.get_job(job.id, PUBLISHED_OWNER)
    assert terminal.status is (JobStatus.FAILED if expected_result_state else JobStatus.CANCELLED)
    assert terminal.cancel_requested_at
    assert terminal.result_state is expected_result_state


@pytest.mark.asyncio
async def test_preview_wait_returns_completed_result_when_publication_wins_timeout_race(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    service = _worker_service(temp_db_path, PreviewWorkerPipeline())
    repository = service.repository
    job = service.create_job(
        owner_user_id=PUBLISHED_OWNER,
        source="69shuba",
        source_url=SOURCE_URL,
        tasks=[
            {
                "canonical_identity": f"69shuba:{SOURCE_URL}",
                "canonical_chapter_url": SOURCE_URL,
                "chapter_number": 0,
                "title": "Preview",
            }
        ],
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        correlation_id="publication-wins-timeout",
    )
    service.enqueue_job(job.id, PUBLISHED_OWNER)
    running = repository.transition_job(job.id, PUBLISHED_OWNER, JobStatus.RUNNING)
    claimed = repository.claim_next_task(
        job.id,
        PUBLISHED_OWNER,
        worker_id="publishing-worker",
    )
    assert claimed is not None

    completed_result = BrowserTaskResult(
        correlation_id="publication-wins-timeout",
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload(
            adapter_id="69shuba",
            adapter_label="69shuba",
            source="www.69shuba.com",
            source_url=SOURCE_URL,
            title="Publication won",
        ),
    )

    class PublicationWinsRepository:
        def __init__(self, delegate: ImportJobRepository) -> None:
            self.delegate = delegate

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

        def expire_browser_job(self, job_id: str, owner_user_id: str) -> ImportJob:
            self.delegate.publish_browser_result(
                job_id,
                owner_user_id,
                task_id=claimed.id,
                lease_token=claimed.lease_token,
                lease_owner=claimed.lease_owner,
                expected_job_version=running.version,
                expected_task_version=claimed.version,
                result=completed_result,
            )
            return self.delegate.expire_browser_job(job_id, owner_user_id)

    service.repository = PublicationWinsRepository(repository)  # type: ignore[assignment]

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    completed = await wait_for_terminal_import_job(
        ConnectedRequest(),  # type: ignore[arg-type]
        service,
        job.id,
        PUBLISHED_OWNER,
        timeout_seconds=0.000001,
        poll_seconds=0.001,
    )

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result_state is BrowserResultState.COMPLETED
    assert completed.result_snapshot == completed_result
    assert repository.list_tasks(job.id, PUBLISHED_OWNER)[0].lease_token == ""
