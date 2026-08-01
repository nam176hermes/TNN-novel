from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import stat
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.database.db import init_db, list_operational_events, record_provider_usage
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import providers as providers_router
from app.mobile_api.services import provider_service as provider_service_module
from app.mobile_api.services.provider_service import ProviderService
from app.mobile_api.services.provider_secret_store import ProviderSecretStore


def make_provider_service(db_path: Path) -> ProviderService:
    service = object.__new__(ProviderService)
    service.db_path = db_path
    return service


def make_synthetic_key() -> str:
    return secrets.token_urlsafe(32)


def assert_secret_matches(actual: str, expected: str) -> None:
    if not hmac.compare_digest(actual, expected):
        pytest.fail("persisted provider key did not match the generated value")


def assert_secret_absent(secret: str, *rendered_values: object) -> None:
    if any(secret in str(value) for value in rendered_values):
        pytest.fail("synthetic provider key was exposed")


def assert_file_unchanged(path: Path, expected: bytes) -> None:
    if path.read_bytes() != expected:
        pytest.fail("project environment file was mutated")


@pytest.fixture
def override_provider_service(
    temp_db_path: Path,
    tmp_path: Path,
) -> ProviderService:
    init_db(temp_db_path)
    service = make_provider_service(temp_db_path)
    service.secret_store_path = tmp_path / "data" / "secrets" / "provider-keys.json"

    async def provide_service() -> ProviderService:
        return service

    app.dependency_overrides[providers_router.get_provider_service] = provide_service
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


def test_provider_key_save_does_not_mutate_project_env(
    override_provider_service: ProviderService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_env_path = tmp_path / "read-only-root" / ".env"
    project_env_path.parent.mkdir()
    original_project_env = b"UNCHANGED=1\n"
    project_env_path.write_bytes(original_project_env)
    override_provider_service.env_path = project_env_path
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    override_provider_service.update_provider_key("gemini", make_synthetic_key())

    assert_file_unchanged(project_env_path, original_project_env)


def test_provider_service_override_does_not_evaluate_default_secret_path(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_default_resolution() -> Path:
        raise RuntimeError("default path must not be evaluated")

    monkeypatch.setattr(
        "app.mobile_api.services.provider_service.provider_secret_store_path",
        fail_default_resolution,
    )

    store = override_provider_service._secret_store()

    assert store.path == override_provider_service.secret_store_path


@pytest.mark.asyncio
async def test_provider_key_update_persists_env_and_marks_key_configured(
    override_provider_service: ProviderService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_env_path = tmp_path / "read-only-root" / ".env"
    project_env_path.parent.mkdir()
    original_project_env = b"UNCHANGED=1\n"
    project_env_path.write_bytes(original_project_env)
    override_provider_service.env_path = project_env_path
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    generated_key = make_synthetic_key()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": generated_key},
            headers=headers,
        )
        providers = await client.get("/api/providers", headers=headers)

    assert response.status_code == 200
    assert response.json()["provider"]["id"] == "gemini"
    assert response.json()["provider"]["api_key_set"] is True
    assert_file_unchanged(project_env_path, original_project_env)
    assert_secret_matches(os.environ["GEMINI_API_KEY"], generated_key)
    gemini = next(item for item in providers.json()["providers"] if item["id"] == "gemini")
    assert gemini["api_key_set"] is True
    assert_secret_absent(generated_key, response.text, providers.text)


@pytest.mark.asyncio
async def test_provider_key_update_reports_postcommit_fsync_failure_without_runtime_drift(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_key = make_synthetic_key()
    real_fsync = os.fsync
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": generated_key},
            headers=headers,
        )

    assert response.status_code == 503
    assert_secret_matches(os.environ["GEMINI_API_KEY"], generated_key)
    stored = ProviderSecretStore(override_provider_service.secret_store_path).load()
    assert_secret_matches(stored["GEMINI_API_KEY"], generated_key)
    assert_secret_absent(generated_key, response.text)


@pytest.mark.asyncio
async def test_provider_key_delete_reports_postcommit_fsync_failure_without_runtime_drift(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_key = make_synthetic_key()
    override_provider_service.update_provider_key("gemini", generated_key)
    real_fsync = os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.delete("/api/providers/gemini/key", headers=headers)

    assert response.status_code == 503
    assert "GEMINI_API_KEY" not in os.environ
    assert "GEMINI_API_KEY" not in ProviderSecretStore(
        override_provider_service.secret_store_path
    ).load()
    assert_secret_absent(generated_key, response.text)


@pytest.mark.asyncio
async def test_provider_key_delete_is_authenticated_and_clears_persisted_and_process_values(
    override_provider_service: ProviderService,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.mobile_api import audit as audit_mod

    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    override_provider_service.env_path = tmp_path / "legacy-write-target" / ".env"
    generated_key = make_synthetic_key()

    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthenticated = await client.delete("/api/providers/gemini/key")
            headers = await auth_headers(client)
            saved = await client.post(
                "/api/providers/gemini/key",
                json={"api_key": generated_key},
                headers=headers,
            )
            deleted = await client.delete("/api/providers/gemini/key", headers=headers)

    assert unauthenticated.status_code == 401
    assert saved.status_code == 200
    assert deleted.status_code == 200
    assert deleted.json()["provider"]["id"] == "gemini"
    assert deleted.json()["provider"]["api_key_set"] is False
    assert "GEMINI_API_KEY" not in os.environ
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_key_delete")
    assert event["details"]["provider_id"] == "gemini"
    assert_secret_absent(generated_key, saved.text, deleted.text, event, caplog.text)


@pytest.mark.asyncio
async def test_provider_key_delete_tombstone_defeats_baseline_env_after_restart_load(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_mod

    baseline_key = make_synthetic_key()
    saved_key = make_synthetic_key()
    monkeypatch.setattr(
        main_mod,
        "validate_access_token",
        lambda token: {"username": "admin", "user_id": "test-user", "session_id": "test"},
    )
    monkeypatch.setenv("GEMINI_API_KEY", baseline_key)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer test-token"}
        saved = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": saved_key},
            headers=headers,
        )
        deleted = await client.delete("/api/providers/gemini/key", headers=headers)

    monkeypatch.setenv("GEMINI_API_KEY", baseline_key)
    ProviderSecretStore(override_provider_service.secret_store_path).load_into_environment()

    assert saved.status_code == 200
    assert deleted.status_code == 200
    assert "GEMINI_API_KEY" not in os.environ
    assert override_provider_service.get_provider("gemini")["api_key_set"] is False
    raw_store = override_provider_service.secret_store_path.read_text(encoding="utf-8")
    assert_secret_absent(baseline_key, saved.text, deleted.text, raw_store)
    assert_secret_absent(saved_key, saved.text, deleted.text, raw_store)


@pytest.mark.asyncio
async def test_provider_key_malformed_body_returns_sanitized_422_without_leakage(
    override_provider_service: ProviderService,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.mobile_api import audit as audit_mod
    from app.mobile_api import main as main_mod

    generated_sensitive_input = make_synthetic_key()
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(
        main_mod,
        "validate_access_token",
        lambda token: {"username": "admin", "user_id": "test-user", "session_id": "test"},
    )
    malformed_json = json.dumps(
        {"api_key": {"nested": generated_sensitive_input}},
        separators=(",", ":"),
    ).encode("utf-8")

    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer test-token"}
            response = await client.post(
                "/api/providers/gemini/key",
                content=malformed_json,
                headers={**headers, "Content-Type": "application/json"},
            )

    assert response.status_code == 422
    assert response.json() == {"detail": "Provider key request is invalid"}
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_key_update")
    assert event["details"]["provider_id"] == "gemini"
    assert event["details"]["result"] == "failure"
    assert_secret_absent(
        generated_sensitive_input,
        response.text,
        dict(response.headers),
        caplog.text,
        event,
    )


@pytest.mark.asyncio
async def test_provider_key_update_records_sanitized_operational_event(
    override_provider_service: ProviderService,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    generated_key = make_synthetic_key()
    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/providers/gemini/key",
            json={"api_key": generated_key},
            headers=headers,
        )

    assert response.status_code == 200
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_key_update")
    assert event["details"]["provider_id"] == "gemini"
    assert_secret_absent(generated_key, response.text, event)


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
    def fail_sync_test_provider(provider_id: str, prompt: str) -> dict:
        raise AssertionError("provider test route called the synchronous compatibility method")

    async def fake_test_provider_async(provider_id: str, prompt: str) -> dict:
        assert provider_id == "gemini"
        assert prompt == "hello"
        return {
            "provider_id": provider_id,
            "model": "gemini-2.5-flash-lite",
            "ok": True,
            "sample": "xin chao",
        }

    monkeypatch.setattr(override_provider_service, "test_provider", fail_sync_test_provider)
    monkeypatch.setattr(
        override_provider_service,
        "test_provider_async",
        fake_test_provider_async,
        raising=False,
    )
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
async def test_provider_test_does_not_block_an_independent_authenticated_request(
    override_provider_service: ProviderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_mod

    provider_started = asyncio.Event()
    release_provider = asyncio.Event()

    async def slow_test_provider_async(provider_id: str, prompt: str) -> dict:
        provider_started.set()
        await release_provider.wait()
        return {
            "provider_id": provider_id,
            "model": "gemini-2.5-flash-lite",
            "ok": True,
            "sample": "xin chao",
        }

    monkeypatch.setattr(
        override_provider_service,
        "test_provider_async",
        slow_test_provider_async,
    )
    monkeypatch.setattr(
        main_mod,
        "validate_access_token",
        lambda token: {"username": "", "user_id": "", "session_id": "test"},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer synthetic-test-token"}
        provider_request = asyncio.create_task(
            client.post(
                "/api/providers/test",
                json={"provider_id": "gemini", "prompt": "hello"},
                headers=headers,
            )
        )
        try:
            await asyncio.wait_for(provider_started.wait(), timeout=5)
            independent = await asyncio.wait_for(
                client.get("/api/providers/defaults", headers=headers),
                timeout=5,
            )
            assert independent.status_code == 200
            assert provider_request.done() is False
        finally:
            release_provider.set()

        response = await asyncio.wait_for(provider_request, timeout=5)

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
    async def missing_provider(provider_id: str, prompt: str) -> dict:
        raise ValueError("Provider missing not found")

    monkeypatch.setattr(override_provider_service, "test_provider_async", missing_provider)
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

    class FailAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("provider test should not create a client without a configured key")

    def fail_post(*args, **kwargs):
        raise AssertionError("provider test should not call the remote API without a configured key")

    monkeypatch.setattr(
        provider_service_module,
        "httpx",
        SimpleNamespace(AsyncClient=FailAsyncClient),
        raising=False,
    )
    monkeypatch.setattr(
        provider_service_module,
        "requests",
        SimpleNamespace(post=fail_post),
        raising=False,
    )
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
    async def fail_provider_test(provider_id: str, prompt: str) -> dict:
        request = httpx.Request("POST", "https://provider-secret.example/v1")
        raise httpx.ConnectError("offline with provider-secret", request=request)

    monkeypatch.setattr(override_provider_service, "test_provider_async", fail_provider_test)
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
    assert "provider-secret" not in caplog.text


@pytest.mark.asyncio
async def test_provider_test_failure_records_sanitized_operational_event(
    override_provider_service: ProviderService,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import audit as audit_mod

    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)

    async def fail_provider_test(provider_id: str, prompt: str) -> dict:
        request = httpx.Request("POST", "https://sk-provider-secret.example/v1")
        raise httpx.ConnectError("offline with sk-provider-secret", request=request)

    monkeypatch.setattr(override_provider_service, "test_provider_async", fail_provider_test)
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
    async def malformed_provider_response(provider_id: str, prompt: str) -> dict:
        raise ValueError("malformed provider response from /tmp/provider-secret.json")

    monkeypatch.setattr(
        override_provider_service,
        "test_provider_async",
        malformed_provider_response,
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
    assert "/tmp/provider-secret.json" not in caplog.text


@pytest.mark.asyncio
async def test_provider_test_timeout_returns_sanitized_504_and_cancels_network_call(
    override_provider_service: ProviderService,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.mobile_api import audit as audit_mod
    from app.mobile_api import main as main_mod

    provider_started = asyncio.Event()
    provider_cancelled = asyncio.Event()
    client_closed = asyncio.Event()
    synthetic_key = "synthetic-timeout-key"
    private_prompt = "private timeout prompt"
    private_base_url = "https://private-timeout-provider.example/v1"

    class SlowAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            client_closed.set()

        async def post(self, url: str, **kwargs):
            provider_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                provider_cancelled.set()
                raise

    monkeypatch.setattr(audit_mod, "get_db_path", lambda: temp_db_path)
    monkeypatch.setattr(
        main_mod,
        "validate_access_token",
        lambda token: {"username": "", "user_id": "", "session_id": "test"},
    )
    monkeypatch.setenv("CUSTOM_TIMEOUT_KEY", synthetic_key)
    monkeypatch.setattr(
        override_provider_service,
        "get_provider",
        lambda provider_id: {
            "id": "custom-timeout",
            "base_url": private_base_url,
            "model": "private-timeout-model",
            "api_key_env": "CUSTOM_TIMEOUT_KEY",
            "temperature": 0.3,
            "timeout_seconds": 0.01,
        },
    )
    monkeypatch.setattr(
        provider_service_module,
        "httpx",
        SimpleNamespace(AsyncClient=SlowAsyncClient),
        raising=False,
    )
    monkeypatch.setattr(
        provider_service_module,
        "requests",
        SimpleNamespace(post=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())),
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("WARNING"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer synthetic-test-token"}
            response = await asyncio.wait_for(
                client.post(
                    "/api/providers/test",
                    json={"provider_id": "custom-timeout", "prompt": private_prompt},
                    headers=headers,
                ),
                timeout=5,
            )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "Provider test timed out. Check provider timeout settings and server logs."
    }
    assert provider_started.is_set()
    assert provider_cancelled.is_set()
    assert client_closed.is_set()
    events = list_operational_events(temp_db_path, limit=10, severities=())
    event = next(item for item in events if item["event_type"] == "provider_test_failure")
    assert event["details"] == {
        "provider_id": "custom-timeout",
        "result": "failure",
        "client_host": "127.0.0.1",
    }
    assert_secret_absent(
        synthetic_key,
        response.text,
        dict(response.headers),
        caplog.text,
        event,
    )
    assert private_prompt not in str((response.text, caplog.text, event))
    assert private_base_url not in str((response.text, caplog.text, event))


@pytest.mark.asyncio
async def test_provider_test_cancellation_propagates_to_async_network_call(
    override_provider_service: ProviderService,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_mod

    provider_started = asyncio.Event()
    provider_cancelled = asyncio.Event()
    client_closed = asyncio.Event()

    class SlowAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            client_closed.set()

        async def post(self, url: str, **kwargs):
            provider_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                provider_cancelled.set()
                raise

    monkeypatch.setattr(
        override_provider_service,
        "get_provider",
        lambda provider_id: {
            "id": "custom-cancel",
            "base_url": "https://provider.example/v1",
            "model": "custom-model",
            "api_key_env": "",
            "temperature": 0.3,
            "timeout_seconds": 60,
        },
    )
    monkeypatch.setattr(
        provider_service_module,
        "httpx",
        SimpleNamespace(AsyncClient=SlowAsyncClient),
        raising=False,
    )
    monkeypatch.setattr(
        provider_service_module,
        "requests",
        SimpleNamespace(post=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())),
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "validate_access_token",
        lambda token: {"username": "", "user_id": "", "session_id": "test"},
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer synthetic-test-token"}
        provider_request = asyncio.create_task(
            client.post(
                "/api/providers/test",
                json={"provider_id": "custom-cancel", "prompt": "hello"},
                headers=headers,
            )
        )
        try:
            await asyncio.wait_for(provider_started.wait(), timeout=5)
            provider_request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await provider_request
        finally:
            if not provider_request.done():
                provider_request.cancel()
                await asyncio.gather(provider_request, return_exceptions=True)

    assert provider_cancelled.is_set()
    assert client_closed.is_set()
    events = list_operational_events(temp_db_path, limit=10, severities=())
    assert all(event["event_type"] != "provider_test_failure" for event in events)


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
