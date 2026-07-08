from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import get_job_logs, init_db, list_operational_events, record_job_log
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import jobs as jobs_router
from app.mobile_api.services.job_service import JobTracker


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


class RecordingJobService:
    def __init__(self) -> None:
        self.translate_kwargs: dict | None = None
        self.qa_kwargs: dict | None = None
        self.retry_kwargs: dict | None = None

    def start_translate_job(self, **kwargs) -> str:
        self.translate_kwargs = kwargs
        return "job-provider"

    def get_job_status(self, job_id: str) -> dict | None:
        if job_id == "job-empty":
            return {
                "job_id": job_id,
                "status": "completed",
                "target_ids": [],
                "message": "No chapters to translate",
            }
        return {
            "job_id": job_id,
            "status": "queued",
            "target_ids": [10],
            "message": "Translation job started",
        }

    def start_qa_job(self, **kwargs) -> str:
        self.qa_kwargs = kwargs
        return "job-qa-provider"

    def retry_failed_translation_job(self, job_id: str, **kwargs) -> str:
        self.retry_kwargs = {"job_id": job_id, **kwargs}
        return "job-retry-provider"

    def cancel_job(self, job_id: str) -> bool:
        return job_id == "job-running"


@pytest.mark.asyncio
async def test_translate_job_without_targets_returns_conflict(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)

    class EmptyJobService(RecordingJobService):
        def start_translate_job(self, **kwargs) -> str:
            self.translate_kwargs = kwargs
            return "job-empty"

    service = EmptyJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={"book_id": 1, "chapter_ids": [], "params": {"preset_id": "balanced"}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 409
    assert response.json()["detail"].startswith("No chapters to translate")


@pytest.mark.asyncio
async def test_translate_job_resolves_provider_id_to_supported_model_fields(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={
                    "book_id": 1,
                    "chapter_ids": [10],
                    "params": {"provider_id": "gemini", "style_profile_id": "kiem_hiep"},
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 200
    assert service.translate_kwargs is not None
    assert service.translate_kwargs["provider_id"] == "gemini"
    assert service.translate_kwargs["model"] == "gemini-2.5-flash-lite"
    assert service.translate_kwargs["host"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert service.translate_kwargs["api_key"] == "gemini-secret"
    assert service.translate_kwargs["style_profile_id"] == "kiem_hiep"


@pytest.mark.asyncio
async def test_job_start_records_operational_event(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={"book_id": 1, "chapter_ids": [10], "params": {"preset_id": "balanced"}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 200
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "job_start")
    assert event["job_id"] == "job-provider"
    assert event["details"]["job_type"] == "translate"


@pytest.mark.asyncio
async def test_translate_job_accepts_preset_without_user_selected_provider(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={
                    "book_id": 1,
                    "chapter_ids": [10],
                    "params": {"preset_id": "balanced", "style_profile_id": "kiem_hiep"},
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 200
    assert service.translate_kwargs is not None
    assert service.translate_kwargs["preset_id"] == "balanced"
    assert service.translate_kwargs["provider_id"] is None
    assert service.translate_kwargs["model"] is None
    assert service.translate_kwargs["style_profile_id"] == "kiem_hiep"


@pytest.mark.asyncio
async def test_translate_job_missing_provider_returns_404(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={"book_id": 1, "chapter_ids": [10], "params": {"provider_id": "missing"}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider missing not found"
    assert service.translate_kwargs is None


@pytest.mark.asyncio
async def test_translate_job_rejects_provider_without_required_api_key(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/translate",
                json={"book_id": 1, "chapter_ids": [10], "params": {"provider_id": "gemini"}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 400
    assert response.json()["detail"] == "Provider gemini requires GEMINI_API_KEY"
    assert service.translate_kwargs is None


@pytest.mark.asyncio
async def test_qa_job_rejects_default_provider_without_required_api_key(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/jobs/qa",
                json={"book_id": 1, "chapter_ids": [10], "params": {}},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 400
    assert response.json()["detail"] == "Provider deepseek requires DEEPSEEK_API_KEY"
    assert service.qa_kwargs is None


@pytest.mark.asyncio
async def test_retry_failed_translation_job_endpoint_starts_specific_retry() -> None:
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post("/api/jobs/job-failed/retry", headers=headers)
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-retry-provider",
        "status": "pending",
        "message": "Retry job started",
    }
    assert service.retry_kwargs == {"job_id": "job-failed", "api_key": None}


@pytest.mark.asyncio
async def test_job_retry_and_cancel_record_operational_events(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    init_db(temp_db_path)
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    service = RecordingJobService()
    app.dependency_overrides[jobs_router.get_job_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            retry_response = await client.post("/api/jobs/job-failed/retry", headers=headers)
            cancel_response = await client.post("/api/jobs/job-running/cancel", headers=headers)
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert retry_response.status_code == 200
    assert cancel_response.status_code == 200
    events = list_operational_events(temp_db_path, limit=20, severities=())
    retry_event = next(item for item in events if item["event_type"] == "job_retry")
    cancel_event = next(item for item in events if item["event_type"] == "job_cancel")
    assert retry_event["job_id"] == "job-retry-provider"
    assert retry_event["details"]["retry_of_job_id"] == "job-failed"
    assert cancel_event["job_id"] == "job-running"


@pytest.mark.asyncio
async def test_retry_failed_translation_job_endpoint_returns_friendly_error() -> None:
    class RejectingJobService(RecordingJobService):
        def retry_failed_translation_job(self, job_id: str, **kwargs) -> str:
            raise ValueError("Only failed translation jobs can be retried")

    app.dependency_overrides[jobs_router.get_job_service] = lambda: RejectingJobService()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post("/api/jobs/job-running/retry", headers=headers)
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert response.status_code == 400
    assert response.json()["detail"] == "Only failed translation jobs can be retried"
    assert "Traceback" not in response.text


@pytest.mark.asyncio
async def test_translate_job_events_stream_returned_job_id(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1)
    tracker.update_job(job.job_id, status="completed", progress=1, message="Done")

    class CompletedJobService(RecordingJobService):
        def __init__(self) -> None:
            super().__init__()
            self.tracker = tracker

        def start_translate_job(self, **kwargs) -> str:
            self.translate_kwargs = kwargs
            return job.job_id

        def get_job_status(self, job_id: str) -> dict | None:
            job_status = self.tracker.get_job(job_id)
            return job_status.to_dict() if job_status else None

    app.dependency_overrides[jobs_router.get_job_service] = lambda: CompletedJobService()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            start = await client.post(
                "/api/jobs/translate",
                json={"book_id": 1, "chapter_ids": [10], "params": {"preset_id": "balanced"}},
                headers=headers,
            )
            assert start.status_code == 200
            job_id = start.json()["job_id"]

            events = await client.get(f"/api/jobs/{job_id}/events", headers=headers)
    finally:
        app.dependency_overrides.pop(jobs_router.get_job_service, None)

    assert events.status_code == 200
    assert job_id in events.text
    assert '"status": "completed"' in events.text


@pytest.mark.asyncio
async def test_job_logs_endpoint_returns_sanitized_entries(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    record_job_log(
        temp_db_path,
        job_id="job-secret",
        event_type="state_transition",
        state="FAILED",
        step="TRANSLATING",
        message="Traceback with api_key=secret-token in /home/user/app",
        details={"authorization": "Bearer secret-token", "chapter_id": 10},
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/jobs/job-secret/logs", headers=headers)

    assert response.status_code == 200
    body = response.text
    payload = response.json()
    assert payload[0]["message"] == "Job event recorded. Check server logs."
    assert payload[0]["details"]["authorization"] == "[redacted]"
    assert payload[0]["details"]["chapter_id"] == 10
    assert "secret-token" not in body
    assert "Traceback" not in body
    assert "/home/user" not in body


@pytest.mark.asyncio
async def test_job_logs_endpoint_supports_bounded_pagination(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    for index in range(5):
        record_job_log(
            temp_db_path,
            job_id="job-page",
            event_type=f"event-{index}",
            state="TRANSLATING",
            step="TRANSLATING",
            message=f"event {index}",
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/jobs/job-page/logs?limit=2&offset=1", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert [item["event_type"] for item in payload] == ["event-3", "event-2"]


@pytest.mark.asyncio
async def test_job_logs_endpoint_clamps_large_limit(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    for index in range(110):
        record_job_log(temp_db_path, job_id="job-limit", event_type=f"event-{index}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/jobs/job-limit/logs?limit=500", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 100


@pytest.mark.asyncio
async def test_job_logs_endpoint_requires_auth_when_bypass_disabled(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(jobs_router, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr("app.mobile_api.main.auth_bypass_enabled", lambda: False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/jobs/job-secret/logs")

    assert response.status_code == 401


def test_job_log_messages_are_truncated_before_storage(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    record_job_log(
        temp_db_path,
        job_id="job-long",
        event_type="progress",
        message="x" * 2000,
        details={"note": "y" * 2000},
    )

    logs = get_job_logs(temp_db_path, "job-long")

    assert len(logs[0]["message"]) <= 500
    assert len(logs[0]["details"]["note"]) <= 500
