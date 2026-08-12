from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    PreviewBrowserPayload,
    PreviewChapterResult,
    PreviewPolicyResult,
    decode_browser_result,
    encode_browser_result,
)


def _preview_payload(**changes: object) -> dict[str, object]:
    """Return the complete durable allowlist for a source-preview result."""
    payload: dict[str, object] = {
        "adapter_id": "69shuba",
        "adapter_label": "69shu-ba",
        "adapter_version": "2026.08",
        "parser_method": "html_parser",
        "source": "69shuba",
        "source_url": "https://www.69shuba.com/book/123",
        "title": "A novel",
        "author": "Author",
        "description": "Public summary",
        "cover_url": "https://cdn.example.test/cover.jpg",
        "chapters": [{"chapter_number": 1, "title": "Chapter 1", "url": "https://www.69shuba.com/chapter/1"}],
        "policy": {
            "source_id": "69shuba",
            "label": "69shu-ba",
            "delay_seconds": 1,
            "max_concurrency": 1,
            "retry_limit": 3,
        },
        "bypass_used": False,
        "bypass_method": "",
        "fetch_method": "direct",
        "fetch_status_code": 200,
        "fetch_attempts": 1,
        "fetch_elapsed_ms": 25,
        "fetch_bytes_received": 1234,
        "fetch_final_url": "https://www.69shuba.com/book/123",
        "fetch_cookies_refreshed": False,
        "fetch_cache_hit": False,
    }
    payload.update(changes)
    return payload


def test_preview_result_round_trip_preserves_only_the_public_contract() -> None:
    """A completed preview persists only the explicitly allowlisted metadata."""
    result = BrowserTaskResult(
        correlation_id="preview-123",
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload.model_validate(_preview_payload()),
    )

    encoded = encode_browser_result(result)
    decoded = decode_browser_result(encoded)

    assert encoded == json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert decoded == result
    assert decoded is not None
    assert decoded.payload == PreviewBrowserPayload(
        adapter_id="69shuba",
        adapter_label="69shu-ba",
        adapter_version="2026.08",
        parser_method="html_parser",
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        title="A novel",
        author="Author",
        description="Public summary",
        cover_url="https://cdn.example.test/cover.jpg",
        chapters=[PreviewChapterResult(chapter_number=1, title="Chapter 1", url="https://www.69shuba.com/chapter/1")],
        policy=PreviewPolicyResult(source_id="69shuba", label="69shu-ba", delay_seconds=1, max_concurrency=1, retry_limit=3),
        bypass_used=False,
        bypass_method="",
        fetch_method="direct",
        fetch_status_code=200,
        fetch_attempts=1,
        fetch_elapsed_ms=25,
        fetch_bytes_received=1234,
        fetch_final_url="https://www.69shuba.com/book/123",
        fetch_cookies_refreshed=False,
        fetch_cache_hit=False,
    )


@pytest.mark.parametrize("field", ["html", "content", "cookie", "authorization"])
def test_preview_result_rejects_unknown_sensitive_and_oversized_fields(field: str) -> None:
    """Sensitive or unbounded data cannot enter the durable preview envelope."""
    with pytest.raises(ValidationError):
        PreviewBrowserPayload.model_validate(_preview_payload(**{field: "must-not-persist"}))

    with pytest.raises(ValidationError):
        PreviewBrowserPayload.model_validate(_preview_payload(title="x" * 2_001))

    with pytest.raises(ValidationError):
        PreviewBrowserPayload.model_validate(
            _preview_payload(chapters=[{"chapter_number": index, "title": "chapter", "url": "https://example.test/chapter"} for index in range(5_001)])
        )

    oversized = BrowserTaskResult(
        correlation_id="preview-123",
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload.model_validate(_preview_payload(description="x" * 2_000)),
    )
    oversized_payload = oversized.payload.model_copy(
        update={
            "chapters": [
                PreviewChapterResult(
                    chapter_number=index,
                    title="x" * 2_000,
                    url="https://example.test/chapter",
                )
                for index in range(600)
            ]
        }
    )
    with pytest.raises(ValueError, match="browser result exceeds 1048576 bytes"):
        encode_browser_result(oversized.model_copy(update={"payload": oversized_payload}))


def test_browser_terminal_state_requires_payload_only_for_completed_preview() -> None:
    """Terminal result states cannot mix success payloads with failures."""
    completed_payload = PreviewBrowserPayload.model_validate(_preview_payload())

    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.COMPLETED)
    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.COMPLETED, payload=completed_payload, error_code="source_failed")
    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.FAILED, payload=completed_payload, error_code="source_failed")
    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.BLOCKED, error_code="")
    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.CANCELLED, error_code="")
    with pytest.raises(ValidationError):
        BrowserTaskResult(correlation_id="preview-123", state=BrowserResultState.TIMED_OUT, error_code="invalid-code")

    assert BrowserTaskResult(
        correlation_id="preview-123",
        state=BrowserResultState.FAILED,
        error_code="source_failed",
        error_message="Source returned an error.",
        retryable=True,
        http_status=502,
    ).state is BrowserResultState.FAILED


@pytest.mark.parametrize(
    "error_metadata",
    [
        {"retryable": True},
        {"http_status": 500},
    ],
)
def test_completed_preview_result_rejects_error_metadata(error_metadata: dict[str, object]) -> None:
    """A completed preview cannot carry retry or HTTP-error fields."""
    with pytest.raises(ValidationError):
        BrowserTaskResult(
            correlation_id="preview-123",
            state=BrowserResultState.COMPLETED,
            payload=PreviewBrowserPayload.model_validate(_preview_payload()),
            **error_metadata,
        )


@pytest.mark.parametrize(
    ("field", "credential_url"),
    [
        ("source_url", "https://www.69shuba.com/book/123?apiKey=canary"),
        ("fetch_final_url", "https://www.69shuba.com/book/123?API-KEY=canary"),
        ("chapter_url", "https://www.69shuba.com/chapter/1?API%2EKEY=canary"),
    ],
)
def test_preview_result_rejects_credential_query_urls(
    field: str,
    credential_url: str,
) -> None:
    payload = _preview_payload()
    if field == "chapter_url":
        payload["chapters"] = [
            {
                "chapter_number": 1,
                "title": "Chapter 1",
                "url": credential_url,
            }
        ]
    else:
        payload[field] = credential_url

    with pytest.raises(ValidationError, match="credential query"):
        PreviewBrowserPayload.model_validate(payload)
