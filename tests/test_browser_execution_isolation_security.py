from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

import pytest

from app.database.db import init_db
from app.import_contracts import BrowserResultState, ImportOperationKind
from app.import_worker import DurableImportWorker
from app.ingestion import source_adapters
from app.services.import_job_factory import create_import_job_service
from app.services.import_job_runtime import RetryPolicy


OWNER = "ws1-security-owner"
SOURCE_URL = "https://www.69shuba.com/book/901/"
CHAPTER_URL = "https://www.69shuba.com/book/901/1.html"


def _preview_mapping(*, fetch_method: str = "direct_http") -> dict[str, object]:
    return {
        "adapter_id": "69shuba",
        "adapter_label": "69shuba",
        "adapter_version": "security-fixture-v1",
        "parser_method": "local_fixture",
        "source": "www.69shuba.com",
        "source_url": SOURCE_URL,
        "title": "Fixture novel",
        "author": "Fixture author",
        "description": "Local fixture only",
        "cover_url": "",
        "chapters": [
            {
                "chapter_number": 1,
                "title": "Fixture chapter",
                "url": CHAPTER_URL,
            }
        ],
        "policy": {
            "source_id": "69shuba",
            "label": "69shuba",
            "delay_seconds": 8,
            "max_concurrency": 1,
            "retry_limit": 2,
        },
        "bypass_used": fetch_method != "direct_http",
        "bypass_method": fetch_method if fetch_method != "direct_http" else "",
        "fetch_method": fetch_method,
        "fetch_status_code": 200,
        "fetch_attempts": 2 if fetch_method != "direct_http" else 1,
        "fetch_elapsed_ms": 1,
        "fetch_bytes_received": 64,
        "fetch_final_url": SOURCE_URL,
        "fetch_cookies_refreshed": fetch_method != "direct_http",
        "fetch_cache_hit": False,
    }


def _enqueue_preview(service, *, config_snapshot: dict[str, object] | None = None):
    job = service.create_job(
        owner_user_id=OWNER,
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
        config_snapshot=config_snapshot,
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        correlation_id="ws1-security-preview",
    )
    return service.enqueue_job(job.id, OWNER)


def _service(db_path: Path, pipeline):
    service = create_import_job_service(
        worker_id="ws1-security-worker",
        pipeline=pipeline,
        db_path=db_path,
    )
    service.retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0)
    return service


def test_blocked_direct_fetch_invokes_browser_fallback_exactly_once_in_worker(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_html = "<html><body><h1>Fixture novel</h1></body></html>"
    browser_urls: list[str] = []

    class BlockedResponse:
        status_code = 403
        headers = {"server": "cloudflare", "Content-Type": "text/html"}

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = type(
                "Cookies",
                (),
                {"get_dict": lambda _self: {}, "set": lambda _self, *_args, **_kwargs: None},
            )()

        def get(self, *_args, **_kwargs):
            return BlockedResponse()

    def browser_fallback(url: str, *_args, **_kwargs) -> str:
        browser_urls.append(url)
        return local_html

    class FetchingPreviewPipeline:
        def preview_source_url(self, url: str) -> dict[str, object]:
            result = source_adapters.fetch_public_html_result(
                url,
                resolver=lambda _hostname, _port: ("93.184.216.34",),
            )
            assert result.html == local_html
            return _preview_mapping(fetch_method=result.method.value)

    monkeypatch.setattr(source_adapters.requests, "Session", FakeSession)
    monkeypatch.setattr(source_adapters, "apply_cookies_to_session", lambda *_args: None)
    monkeypatch.setattr(source_adapters, "_call_stealth_fallback", browser_fallback)
    init_db(temp_db_path)
    service = _service(temp_db_path, FetchingPreviewPipeline())
    job = _enqueue_preview(service)

    processed = DurableImportWorker(
        service,
        heartbeat_path=tmp_path / "security-worker.heartbeat",
        close_browser=lambda: None,
    ).run_once()

    completed = service.get_job(job.id, OWNER)
    assert processed == 1
    assert completed.result_state is BrowserResultState.COMPLETED
    assert completed.result_snapshot is not None
    assert completed.result_snapshot.payload is not None
    assert completed.result_snapshot.payload.fetch_method == "stealth_browser_headed"
    assert browser_urls == [SOURCE_URL]


def test_provider_secret_names_and_values_never_enter_worker_job_or_result(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_names = (
        "REMOTE_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "MOBILE_API_SECRET",
        "MOBILE_API_ADMIN_PASSWORD",
    )
    canaries = {name: f"ws1-canary-{index}-must-not-persist" for index, name in enumerate(secret_names)}
    for name, value in canaries.items():
        monkeypatch.setenv(name, value)

    class SecretFreePreviewPipeline:
        def preview_source_url(self, _url: str) -> dict[str, object]:
            return _preview_mapping()

    init_db(temp_db_path)
    service = _service(temp_db_path, SecretFreePreviewPipeline())
    job = _enqueue_preview(
        service,
        config_snapshot={
            "source": "69shuba",
            "provider_config": canaries,
        },
    )
    assert DurableImportWorker(
        service,
        heartbeat_path=tmp_path / "secret-boundary-worker.heartbeat",
        close_browser=lambda: None,
    ).run_once() == 1

    with sqlite3.connect(temp_db_path) as connection:
        row = connection.execute(
            "SELECT config_snapshot_json, result_snapshot_json FROM import_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
        event_json = [
            str(event[0])
            for event in connection.execute(
                "SELECT payload_json FROM import_job_events WHERE job_id = ? ORDER BY sequence",
                (job.id,),
            ).fetchall()
        ]
    assert row is not None
    persisted_json = "\n".join((str(row[0]), str(row[1]), *event_json))
    for name, value in canaries.items():
        assert name not in persisted_json
        assert value not in persisted_json
