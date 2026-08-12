from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

import pytest

from app.database.db import init_db
from app.database.import_jobs import ImportJobRepository, JobStatus
from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
    PreviewBrowserPayload,
)
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


def _durable_text_dump(db_path: Path) -> str:
    values: list[str] = []
    with sqlite3.connect(db_path) as connection:
        for table in ("import_jobs", "chapter_tasks", "import_job_events"):
            text_columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                if "TEXT" in str(row[2]).upper()
            ]
            if not text_columns:
                continue
            selected = ", ".join(f'"{column}"' for column in text_columns)
            for row in connection.execute(f"SELECT {selected} FROM {table}").fetchall():
                values.extend(str(value) for value in row if value is not None)
    return "\n".join(values)


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
    obfuscated_names = (
        "apiKey",
        "api-key",
        "apikey",
        "API.KEY",
        "PROVIDER_API_KEY",
        "_API_KEY_",
        "prefixApiKeySuffix",
    )
    all_secret_names = (*secret_names, *obfuscated_names)
    canaries = {
        name: f"ws1-canary-{index}-must-not-persist"
        for index, name in enumerate(all_secret_names)
    }
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
            "provider_config": [
                {
                    "safe_setting": f"keep-{index}",
                    "nested": [{name: canaries[name]}],
                }
                for index, name in enumerate(all_secret_names)
            ],
            "declared_provider_secrets": {
                name: canaries[name]
                for name in secret_names
            },
            "unrelated": {
                "retry_limit": 2,
                "display_label": "keep-this-public-setting",
            },
        },
    )
    assert DurableImportWorker(
        service,
        heartbeat_path=tmp_path / "secret-boundary-worker.heartbeat",
        close_browser=lambda: None,
    ).run_once() == 1

    completed = service.get_job(job.id, OWNER)
    assert completed.config_snapshot == {
        "source": "69shuba",
        "provider_config": [
            {"safe_setting": f"keep-{index}", "nested": [{}]}
            for index in range(len(all_secret_names))
        ],
        "unrelated": {
            "retry_limit": 2,
            "display_label": "keep-this-public-setting",
        },
    }
    persisted_json = _durable_text_dump(temp_db_path)
    for name, value in canaries.items():
        assert name not in persisted_json
        assert value not in persisted_json


def test_durable_job_and_task_urls_reject_credential_queries_before_persistence(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    job_canary = "ws1-job-query-canary"
    with pytest.raises(ValueError, match="credential query"):
        repository.create_job(
            owner_user_id=OWNER,
            source="69shuba",
            source_url=f"{SOURCE_URL}?apiKey={job_canary}",
            total=1,
        )
    assert repository.count_active_jobs(OWNER) == 0
    assert job_canary not in _durable_text_dump(temp_db_path)

    clean_job = repository.create_job(
        owner_user_id=OWNER,
        source="69shuba",
        source_url=f"{SOURCE_URL}?chapter=1",
        total=1,
    )
    task_canary = "ws1-task-query-canary"
    with pytest.raises(ValueError, match="credential query"):
        repository.create_task(
            job_id=clean_job.id,
            owner_user_id=OWNER,
            canonical_identity="69shuba:credential-query",
            canonical_chapter_url=f"{CHAPTER_URL}?API-KEY={task_canary}",
            chapter_number=1,
            title="Fixture chapter",
        )
    assert repository.list_tasks(clean_job.id, OWNER) == []
    assert task_canary not in _durable_text_dump(temp_db_path)


@pytest.mark.parametrize("url_field", ["source_url", "fetch_final_url", "chapter_url"])
def test_browser_result_publication_rejects_credential_query_urls(
    url_field: str,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    service = _service(temp_db_path, type("Pipeline", (), {})())
    job = _enqueue_preview(service)
    running = service.repository.transition_job(job.id, OWNER, JobStatus.RUNNING)
    claimed = service.repository.claim_next_task(job.id, OWNER, worker_id="query-result-worker")
    assert claimed is not None
    clean_payload = PreviewBrowserPayload.model_validate(_preview_mapping())
    canary = f"ws1-result-{url_field}-canary"
    credential_url = f"{SOURCE_URL}?API%2EKEY={canary}"
    if url_field == "chapter_url":
        chapter = clean_payload.chapters[0].model_copy(update={"url": credential_url})
        bad_payload = clean_payload.model_copy(update={"chapters": [chapter]})
    else:
        bad_payload = clean_payload.model_copy(update={url_field: credential_url})
    bypassed_result = BrowserTaskResult.model_construct(
        correlation_id=job.correlation_id,
        state=BrowserResultState.COMPLETED,
        payload=bad_payload,
    )

    with pytest.raises(ValueError, match="credential query"):
        service.repository.publish_browser_result(
            job.id,
            OWNER,
            task_id=claimed.id,
            lease_token=claimed.lease_token,
            lease_owner=claimed.lease_owner,
            expected_job_version=running.version,
            expected_task_version=claimed.version,
            result=bypassed_result,
        )

    unpublished = service.get_job(job.id, OWNER)
    assert unpublished.result_snapshot is None
    assert canary not in _durable_text_dump(temp_db_path)
    clean_result = BrowserTaskResult(
        correlation_id=job.correlation_id,
        state=BrowserResultState.COMPLETED,
        payload=clean_payload,
    )
    published = service.repository.publish_browser_result(
        job.id,
        OWNER,
        task_id=claimed.id,
        lease_token=claimed.lease_token,
        lease_owner=claimed.lease_owner,
        expected_job_version=running.version,
        expected_task_version=claimed.version,
        result=clean_result,
    )
    assert published.result_state is BrowserResultState.COMPLETED
    assert published.result_snapshot == clean_result
