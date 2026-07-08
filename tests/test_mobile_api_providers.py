from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import requests

from app.database.db import init_db, list_operational_events, record_provider_usage
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import providers as providers_router
from app.mobile_api.services.provider_service import ProviderService


def make_provider_service(db_path: Path) -> ProviderService:
    service = object.__new__(ProviderService)
    service.db_path = db_path
    return service


@pytest.fixture
def override_provider_service(temp_db_path: Path) -> ProviderService:
    init_db(temp_db_path)
    service = make_provider_service(temp_db_path)
    app.dependency_overrides[providers_router.get_provider_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(providers_router.get_provider_service, None)


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
async def test_provider_list_and_defaults_are_authenticated(
    override_provider_service: ProviderService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauth = await client.get("/api/providers")
        headers = await auth_headers(client)
        providers = await client.get("/api/providers", headers=headers)
        defaults = await client.get("/api/providers/defaults", headers=headers)

    assert unauth.status_code == 401
    assert providers.status_code == 200
    assert any(item["id"] == "gemini" for item in providers.json()["providers"])
    assert "api_key_set" in providers.json()["providers"][0]
    assert defaults.status_code == 200
    assert defaults.json()["defaults"]["translate"] == "gemini"


@pytest.mark.asyncio
async def test_provider_key_update_persists_env_and_marks_key_configured(
    override_provider_service: ProviderService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MOBILE_API_ADMIN_USERNAME=admin\nGEMINI_API_KEY=old-secret\n", encoding="utf-8")
    override_provider_service.env_path = env_path
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": "new-secret"},
            headers=headers,
        )
        providers = await client.get("/api/providers", headers=headers)

    assert response.status_code == 200
    assert response.json()["provider"]["id"] == "gemini"
    assert response.json()["provider"]["api_key_set"] is True
    assert "GEMINI_API_KEY=new-secret" in env_path.read_text(encoding="utf-8")
    assert "old-secret" not in env_path.read_text(encoding="utf-8")
    assert os.environ["GEMINI_API_KEY"] == "new-secret"
    gemini = next(item for item in providers.json()["providers"] if item["id"] == "gemini")
    assert gemini["api_key_set"] is True
    assert "new-secret" not in str(response.json())


@pytest.mark.asyncio
async def test_provider_key_update_records_sanitized_operational_event(
    override_provider_service: ProviderService,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    env_path = tmp_path / ".env"
    override_provider_service.env_path = env_path
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": "new-provider-secret"},
            headers=headers,
        )

    assert response.status_code == 200
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_key_update")
    assert event["details"]["provider_id"] == "gemini"
    assert "new-provider-secret" not in str(event)


@pytest.mark.asyncio
async def test_provider_cost_estimate_endpoint(
    override_provider_service: ProviderService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/estimate",
            json={"provider_id": "gemini", "source_chars": 12000, "chapter_count": 2},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider_id"] == "gemini"
    assert data["model"] == "gemini-2.5-flash-lite"
    assert data["estimated_cost_usd"] >= 0
    assert data["within_budget"] is True


@pytest.mark.asyncio
async def test_provider_cost_estimate_missing_provider_returns_404(
    override_provider_service: ProviderService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/estimate",
            json={"provider_id": "missing", "source_chars": 12000},
            headers=headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider missing not found"


@pytest.mark.asyncio
async def test_job_cost_estimate_endpoint_returns_provider_service_result(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)
    expected = ProviderService().estimate_cost(
        provider_id="gemini",
        source_chars=12000,
        chapter_count=2,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/jobs/estimate",
            json={"provider_id": "gemini", "source_chars": 12000, "chapter_count": 2},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.asyncio
async def test_job_cost_estimate_missing_provider_returns_404(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.provider_service.get_db_path", lambda: temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/jobs/estimate",
            json={"provider_id": "missing", "source_chars": 12000},
            headers=headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider missing not found"


@pytest.mark.asyncio
async def test_provider_test_endpoint_returns_service_result(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_test_provider(provider_id: str, prompt: str) -> dict:
        assert provider_id == "gemini"
        assert prompt == "hello"
        return {
            "provider_id": provider_id,
            "model": "gemini-2.5-flash-lite",
            "ok": True,
            "sample": "xin chao",
        }

    monkeypatch.setattr(override_provider_service, "test_provider", fake_test_provider)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/test",
            json={"provider_id": "gemini", "prompt": "hello"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "provider_id": "gemini",
        "model": "gemini-2.5-flash-lite",
        "ok": True,
        "sample": "xin chao",
    }


@pytest.mark.asyncio
async def test_provider_test_missing_provider_returns_404(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        override_provider_service,
        "test_provider",
        lambda provider_id, prompt: (_ for _ in ()).throw(ValueError("Provider missing not found")),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/test",
            json={"provider_id": "missing", "prompt": "hello"},
            headers=headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider missing not found"


@pytest.mark.asyncio
async def test_provider_test_rejects_required_provider_without_api_key(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fail_post(*args, **kwargs):
        raise AssertionError("provider test should not call the remote API without a configured key")

    monkeypatch.setattr("app.mobile_api.services.provider_service.requests.post", fail_post)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/test",
            json={"provider_id": "gemini", "prompt": "hello"},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Provider gemini requires GEMINI_API_KEY"


@pytest.mark.asyncio
async def test_provider_test_request_error_returns_502(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        override_provider_service,
        "test_provider",
        lambda provider_id, prompt: (_ for _ in ()).throw(
            requests.ConnectionError("offline with provider-secret")
        ),
    )
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("WARNING"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/providers/test",
                json={"provider_id": "gemini", "prompt": "hello"},
                headers=headers,
            )

    assert response.status_code == 502
    assert response.json()["detail"] == "Provider test failed. Check provider settings and server logs."
    assert "provider-secret" not in response.text
    assert "offline with provider-secret" in caplog.text


@pytest.mark.asyncio
async def test_provider_test_failure_records_sanitized_operational_event(
    override_provider_service: ProviderService,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(
        override_provider_service,
        "test_provider",
        lambda provider_id, prompt: (_ for _ in ()).throw(
            requests.ConnectionError("offline with sk-provider-secret")
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/test",
            json={"provider_id": "gemini", "prompt": "private prompt text"},
            headers=headers,
        )

    assert response.status_code == 502
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_test_failure")
    assert event["details"]["provider_id"] == "gemini"
    assert "sk-provider-secret" not in str(event)
    assert "private prompt text" not in str(event)


@pytest.mark.asyncio
async def test_provider_test_malformed_response_error_returns_502(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        override_provider_service,
        "test_provider",
        lambda provider_id, prompt: (_ for _ in ()).throw(
            ValueError("malformed provider response from /tmp/provider-secret.json")
        ),
    )
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("WARNING"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.post(
                "/api/providers/test",
                json={"provider_id": "gemini", "prompt": "hello"},
                headers=headers,
            )

    assert response.status_code == 502
    assert response.json()["detail"] == "Provider test failed. Check provider settings and server logs."
    assert "/tmp/provider-secret.json" not in response.text
    assert "malformed provider response from /tmp/provider-secret.json" in caplog.text


@pytest.mark.asyncio
async def test_provider_usage_endpoint_returns_summary(
    override_provider_service: ProviderService,
) -> None:
    record_provider_usage(
        override_provider_service.db_path,
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        task_type="translate",
        prompt_tokens=200,
        completion_tokens=300,
        estimated_cost_usd=0.00014,
        job_id="job-api",
        chapter_id=1,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get("/api/providers/usage", headers=headers)

    assert response.status_code == 200
    assert response.json()["usage"] == {
        "total_prompt_tokens": 200,
        "total_completion_tokens": 300,
        "total_tokens": 500,
        "total_estimated_cost_usd": 0.00014,
    }
