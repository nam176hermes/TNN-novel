"""Safe, typed contracts for durable browser-capable import operations."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_PUBLIC_STRING_LENGTH = 2_000
MAX_CORRELATION_ID_LENGTH = 128
MAX_PREVIEW_CHAPTERS = 5_000
MAX_BROWSER_RESULT_BYTES = 1_048_576
_ERROR_CODE_PATTERN = re.compile(r"[a-z0-9_]{1,96}")

PublicText = Annotated[str, Field(max_length=MAX_PUBLIC_STRING_LENGTH)]


class ImportOperationKind(str, Enum):
    PREVIEW = "preview"
    IMPORT_CHAPTERS = "import_chapters"


class BrowserResultState(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class PreviewChapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_number: int
    title: PublicText
    url: PublicText


class PreviewPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: PublicText = ""
    label: PublicText = ""
    delay_seconds: int = 0
    max_concurrency: int = 1
    retry_limit: int = 0


class PreviewBrowserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: PublicText
    adapter_label: PublicText
    adapter_version: PublicText = ""
    parser_method: PublicText = ""
    source: PublicText
    source_url: PublicText
    title: PublicText
    author: PublicText = ""
    description: PublicText = ""
    cover_url: PublicText = ""
    chapters: list[PreviewChapterResult] = Field(default_factory=list, max_length=MAX_PREVIEW_CHAPTERS)
    policy: PreviewPolicyResult | None = None
    bypass_used: bool = False
    bypass_method: PublicText = ""
    fetch_method: PublicText = ""
    fetch_status_code: int | None = None
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0
    fetch_bytes_received: int = 0
    fetch_final_url: PublicText = ""
    fetch_cookies_refreshed: bool = False
    fetch_cache_hit: bool = False


class BrowserTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    correlation_id: Annotated[str, Field(min_length=1, max_length=MAX_CORRELATION_ID_LENGTH)]
    state: BrowserResultState
    payload: PreviewBrowserPayload | None = None
    error_code: str = ""
    error_message: PublicText = ""
    retryable: bool = False
    http_status: int | None = None

    @field_validator("error_code")
    @classmethod
    def validate_error_code(cls, value: str) -> str:
        if value and not _ERROR_CODE_PATTERN.fullmatch(value):
            raise ValueError("error_code must match [a-z0-9_]{1,96}")
        return value

    @field_validator("http_status")
    @classmethod
    def validate_http_status(cls, value: int | None) -> int | None:
        if value is not None and not 400 <= value <= 599:
            raise ValueError("http_status must be between 400 and 599")
        return value

    @model_validator(mode="after")
    def validate_terminal_state(self) -> BrowserTaskResult:
        if self.state is BrowserResultState.COMPLETED:
            if self.payload is None:
                raise ValueError("completed browser result requires a payload")
            if self.error_code or self.error_message:
                raise ValueError("completed browser result cannot include error fields")
            return self

        if self.payload is not None:
            raise ValueError("non-completed browser result cannot include a payload")
        if not self.error_code:
            raise ValueError("non-completed browser result requires an error_code")
        return self


def encode_browser_result(result: BrowserTaskResult) -> str:
    """Serialize a validated result to the canonical bounded JSON representation."""
    encoded = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > MAX_BROWSER_RESULT_BYTES:
        raise ValueError("browser result exceeds 1048576 bytes")
    return encoded


def decode_browser_result(value: str) -> BrowserTaskResult | None:
    """Decode a stored canonical result without reflecting untrusted JSON."""
    if not value:
        return None
    try:
        decoded = json.loads(value)
        return BrowserTaskResult.model_validate(decoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("invalid browser result") from None
