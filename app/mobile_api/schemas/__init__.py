from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    username: str


# ── Health ────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, bool]
    details: dict[str, str] = {}
    core: dict[str, str] = Field(default_factory=dict)
    job_processing: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    release: dict[str, str] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    version: str
    frontend_version: str = ""
    git_sha: str = "unknown"
    build_timestamp: str = "unknown"
    release_id: str = "development"
    image_tag: str = "unknown"
    image_digest: str = "unknown"
    schema_revision: str = ""
    component: str = "api"
    build: str = ""


class RetentionRunSummaryResponse(BaseModel):
    last_run_at: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    result: Literal["completed", "skipped"]


class RetentionStatusResponse(BaseModel):
    table_counts: dict[str, int] = Field(default_factory=dict)
    auth_session_counts: dict[str, int] = Field(default_factory=dict)
    last_run: RetentionRunSummaryResponse | None = None


class RecoveryFreshnessResponse(BaseModel):
    state: Literal["missing", "corrupt", "future", "wrong_release", "stale", "fresh"] = "missing"
    age_seconds: int | None = None
    completed_at: str | None = None
    archive_hash_id: str | None = None
    validation_counts: dict[str, int] = Field(default_factory=dict)
    producer_version: str | None = None
    threshold_seconds: int


class SystemStatusResponse(BaseModel):
    db_size_bytes: int = 0
    data_size_bytes: int = 0
    cache_count: int = 0
    cache_size_bytes: int = 0
    ollama_host: str = ""
    ollama_model: str = ""
    database_available: bool = False
    data_directory_available: bool = False
    storage_health: str = "unknown"
    storage_label: str = "Configured data storage"
    public_deploy: bool = False
    api_ready: bool = False
    active_provider: str = ""
    upload_max_bytes: int = 0
    asset_protection_enabled: bool = False
    active_jobs: int = 0
    running_jobs: int = 0
    queued_jobs: int = 0
    retrying_jobs: int = 0
    interrupted_jobs: int = 0
    failed_jobs: int = 0
    last_failed_job: dict[str, Any] | None = None
    recent_operational_errors: list[dict[str, Any]] = Field(default_factory=list)
    recent_operational_events: list[dict[str, Any]] = Field(default_factory=list)
    recent_backup_events: list[dict[str, Any]] = Field(default_factory=list)
    retention: RetentionStatusResponse = Field(default_factory=RetentionStatusResponse)
    app_version: str = ""
    build: str = ""
    backup_recommendation: str = ""
    external_backup: RecoveryFreshnessResponse = Field(
        default_factory=lambda: RecoveryFreshnessResponse(threshold_seconds=172800)
    )
    restore_drill: RecoveryFreshnessResponse = Field(
        default_factory=lambda: RecoveryFreshnessResponse(threshold_seconds=691200)
    )


# ── Books ────────────────────────────────────────────────────────────────

class BookCreate(BaseModel):
    title: str
    author: str = ""
    source: str = "manual"
    source_url: str = ""


class BookUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    source: str | None = None
    source_url: str | None = None


class BookResponse(BaseModel):
    id: int
    title: str
    author: str = ""
    source: str = "manual"
    source_url: str = ""
    created_at: str = ""
    updated_at: str = ""


# ── Chapters ─────────────────────────────────────────────────────────────

class ChapterResponse(BaseModel):
    id: int
    book_id: int
    chapter_number: int
    title: str
    status: str = ""
    source_url: str = ""
    raw_text_path: str | None = None
    cleaned_text_path: str | None = None
    translated_text_path: str | None = None
    audio_path: str | None = None
    translated_at: str | None = None
    audio_created_at: str | None = None
    created_at: str = ""
    word_count: int = 0


class TranslationEdit(BaseModel):
    text: str


class TextResponse(BaseModel):
    text: str


# ── Reader State ─────────────────────────────────────────────────────────

class ReaderProgressAnchor(BaseModel):
    version: Literal[1] = 1
    text: str = Field(default="", max_length=256)
    offset: int = Field(default=0, ge=0)
    prefix: str = Field(default="", max_length=128)
    suffix: str = Field(default="", max_length=128)


class ReaderProgressUpdate(BaseModel):
    chapter_id: int
    mode: Literal["scroll", "paginated"] = "scroll"
    percent: int = Field(default=0, ge=0, le=100)
    paragraph_index: int = Field(default=0, ge=0)
    char_offset: int = Field(default=0, ge=0)
    absolute_char_offset: int = Field(default=0, ge=0)
    page_index: int = Field(default=0, ge=0)
    anchor: ReaderProgressAnchor | None = None


class ReaderAnnotationCreate(BaseModel):
    kind: Literal["bookmark", "highlight", "note"]
    paragraph_index: int = Field(default=0, ge=0)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)
    selected_text: str = ""
    note: str = ""
    color: str = "yellow"


class ReaderAnnotationUpdate(BaseModel):
    kind: Literal["bookmark", "highlight", "note"] | None = None
    paragraph_index: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    selected_text: str | None = None
    note: str | None = None
    color: str | None = None


class ReaderAnnotationImportItem(BaseModel):
    client_id: str | None = None
    chapter_id: int | None = Field(default=None, ge=0)
    chapter_number: int | None = Field(default=None, ge=0)
    kind: Literal["bookmark", "highlight", "note"]
    paragraph_index: int = Field(default=0, ge=0)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)
    selected_text: str = ""
    note: str = ""
    color: str = "yellow"


class ReaderAnnotationImportRequest(BaseModel):
    annotations: list[ReaderAnnotationImportItem] = Field(default_factory=list)


class ReaderSyncProgress(ReaderProgressUpdate):
    updated_at: str = ""


class ReaderSyncAnnotation(BaseModel):
    id: int | None = None
    client_id: str | None = None
    chapter_id: int
    kind: Literal["bookmark", "highlight", "note"]
    paragraph_index: int = Field(default=0, ge=0)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)
    selected_text: str = ""
    note: str = ""
    color: str = "yellow"
    created_at: str = ""
    updated_at: str = ""
    deleted_at: str | None = None


class ReaderSyncRequest(BaseModel):
    device_id: str = ""
    last_sync_at: str | None = None
    progress: ReaderSyncProgress | None = None
    annotations: list[ReaderSyncAnnotation] = Field(default_factory=list)


class ReaderExplainRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    context_before: str = Field(default="", max_length=3000)
    context_after: str = Field(default="", max_length=3000)
    spoiler_mode: Literal["no_spoiler", "allow_spoiler"] = "no_spoiler"


class ReaderExplainTerm(BaseModel):
    source: str = ""
    target: str = ""
    note: str = ""


class ReaderExplainResponse(BaseModel):
    explanation: str
    terms: list[ReaderExplainTerm] = Field(default_factory=list)


class ReaderXrayEnrichRequest(BaseModel):
    chapter_id: int | None = None
    spoiler_mode: Literal["no_spoiler", "allow_spoiler"] = "no_spoiler"


# ── Import ───────────────────────────────────────────────────────────────

class PasteImport(BaseModel):
    title: str
    chapter_number: int = 1
    chapter_title: str = ""
    text: str


class WizardTextImportChapter(BaseModel):
    chapter_number: int = Field(default=1, ge=1)
    chapter_title: str = ""
    text: str = ""
    raw_text: str = ""
    translated_text: str = ""


class WizardTextImport(BaseModel):
    title: str = ""
    author: str = ""
    target_book_id: int | None = None
    content_kind: Literal["raw", "translated", "both", "unknown"] = "unknown"
    duplicate_strategy: Literal["error", "skip", "overwrite"] = "skip"
    source_type: Literal["paste", "txt", "wizard"] | str = "wizard"
    chapters: list[WizardTextImportChapter] = Field(default_factory=list)


class WizardTextImportResult(BaseModel):
    book_id: int
    title: str
    content_kind: str
    chapter_count: int
    imported_chapters: int
    skipped_chapters: int
    overwritten_chapters: int
    chapter_ids: list[int] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    message: str = "Imported reviewed text"


class URLNoteImport(BaseModel):
    url: str
    title: str = ""
    notes: str = ""
    chapter_number: int = 1
    chapter_title: str = ""


class URLPreviewRequest(BaseModel):
    url: str


class SourceChapterPreview(BaseModel):
    chapter_number: int
    title: str
    url: str


class SourcePolicyPreview(BaseModel):
    source_id: str = ""
    label: str = ""
    delay_seconds: int = 0
    max_concurrency: int = 1
    retry_limit: int = 0


class SourceCapability(BaseModel):
    source_id: str
    label: str
    domains: list[str] = Field(default_factory=list)
    adapter_id: str = ""
    adapter_label: str = ""
    extraction: str = "generic"
    direct_import: bool = True
    delay_seconds: int = 0
    max_concurrency: int = 1
    retry_limit: int = 0
    notes: str = ""


class SourceCapabilityList(BaseModel):
    sources: list[SourceCapability] = Field(default_factory=list)


class SourceCatalogEntry(BaseModel):
    id: str
    external_id: str = ""
    catalog_source: str = "yckceo"
    name: str = ""
    url: str = ""
    domain: str = ""
    author: str = ""
    downloads: int = 0
    version: str = ""
    raw_tags: str = ""
    tags: list[str] = Field(default_factory=list)
    unknown_tags: list[str] = Field(default_factory=list)
    supported: bool = False
    supported_status: str = "unsupported"
    supported_source_id: str = ""
    invalid_reason: str = ""
    updated_label: str = ""
    last_check_status: str = ""
    last_check_at: str = ""
    last_check_error: str = ""
    last_check_http_status: int | None = None
    last_check_final_url: str = ""
    managed_source_id: str = ""
    managed_status: str = ""
    managed_trust_level: str = ""
    managed_last_test_status: str = ""
    managed_last_tested_at: str = ""
    managed_last_successful_fetch_at: str = ""
    managed_last_error: str = ""
    managed_rate_limit_requests_per_minute: int = 0
    managed_rate_limit_delay_ms: int = 0
    managed_max_concurrent_requests: int = 0
    managed_cooldown_after_error_seconds: int = 0
    managed_notes: str = ""
    managed_parser_type: str = ""
    managed_language: str = ""
    can_use_in_jobs: bool = False
    created_at: str = ""
    updated_at: str = ""


class SourceCatalogList(BaseModel):
    items: list[SourceCatalogEntry] = Field(default_factory=list)
    entries: list[SourceCatalogEntry] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50
    page_size: int = 50


class SourceCatalogHealthResponse(BaseModel):
    catalog_entry_id: str
    domain: str = ""
    status: Literal["reachable", "timeout", "blocked", "captcha", "unsupported", "preview_ok", "error"] | str
    reason: str = ""
    checked_at: str
    final_url: str = ""
    http_status: int | None = None


class SourceCatalogHealthSummary(BaseModel):
    total_sources: int = 0
    supported_sources: int = 0
    unhealthy_sources: int = 0
    last_checked_at: str = ""
    status_counts: dict[str, int] = Field(default_factory=dict)


class ParserCandidateCreateRequest(BaseModel):
    sample_url: str = ""


class SourceAdapterCandidate(BaseModel):
    id: str = ""
    catalog_entry_id: str
    domain: str = ""
    sample_url: str = ""
    detected_title: str = ""
    detected_chapter_list: list[dict[str, Any]] = Field(default_factory=list)
    parser_confidence: Literal["high", "medium", "low", "failed"] | str = "low"
    failure_reason: str = ""
    status: Literal["draft", "needs_review", "rejected", "promoted"] | str = "draft"
    created_at: str = ""
    updated_at: str = ""
    reviewed_at: str = ""
    reviewed_by: str = ""


class SourceAdapterCandidateList(BaseModel):
    items: list[SourceAdapterCandidate] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50
    page_size: int = 50


class SourcePreviewResponse(BaseModel):
    adapter_id: str
    adapter_label: str
    source: str
    source_url: str
    title: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    chapters: list[SourceChapterPreview] = Field(default_factory=list)
    chapter_count: int = 0
    policy: SourcePolicyPreview | None = None
    managed_source_id: str = ""
    managed_source_status: str = ""
    managed_source_trust_level: str = ""
    automation_allowed: bool = False
    automation_reason: str = ""
    bypass_used: bool = False
    bypass_method: str = ""
    fetch_method: str = ""
    fetch_status_code: int | None = None
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0
    fetch_bytes_received: int = 0
    fetch_final_url: str = ""
    fetch_cookies_refreshed: bool = False
    fetch_cache_hit: bool = False


class URLImportChapter(BaseModel):
    url: str
    chapter_number: int = 1
    title: str = ""


class URLFetchChapterRequest(BaseModel):
    url: str
    chapter_number: int = 1
    title: str = ""


class URLFetchRequest(BaseModel):
    source_url: str = ""
    title: str = ""
    author: str = ""
    source: str = ""
    chapters: list[URLFetchChapterRequest] = Field(default_factory=list)


class URLFetchChapterResult(BaseModel):
    chapter_number: int
    title: str = ""
    url: str = ""
    success: bool = False
    error: str = ""
    text_length: int = 0
    book_id: int = 0
    chapter_id: int = 0
    stored_text_length: int = 0
    content_hash: str = ""
    operation: str = ""
    warnings: list[str] = Field(default_factory=list)
    error_code: str = ""
    retryable: bool = False
    attempts: int = 0
    fetch_method: str = ""
    elapsed_ms: int = 0
    started_at: str = ""
    finished_at: str = ""


class URLFetchResponse(BaseModel):
    title: str = ""
    book_id: int = 0
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    chapters: list[URLFetchChapterResult] = Field(default_factory=list)


class ImportJobCreateRequest(URLFetchRequest):
    """Create a durable import job from the existing URL chapter selection."""


class ImportJobAcceptedResponse(BaseModel):
    job_id: str
    status: str = "queued"
    total: int = 0


class ImportJobTaskSummary(BaseModel):
    id: int
    chapter_number: int
    title: str = ""
    status: str
    stage: str
    attempts: int = 0
    next_attempt_at: str = ""
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    fetch_method: str = ""
    text_length: int = 0
    content_hash: str = ""
    elapsed_ms: int = 0
    started_at: str = ""
    finished_at: str = ""
    book_id: int | None = None
    chapter_id: int | None = None


class ImportJobSnapshotResponse(BaseModel):
    job_id: str
    status: str
    source: str = ""
    book_id: int | None = None
    total: int = 0
    queued_count: int = 0
    running_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    waiting_retry_count: int = 0
    verification_required_count: int = 0
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    cancel_requested_at: str = ""
    error_summary: str = ""
    tasks: list[ImportJobTaskSummary] = Field(default_factory=list)


class ImportJobEventData(BaseModel):
    sequence: int
    job_id: str
    task_id: int | None = None
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class ImportJobErrorDetail(BaseModel):
    code: str
    retryable: bool = False
    message: str


class ImportJobErrorResponse(BaseModel):
    detail: ImportJobErrorDetail


class URLImportStart(BaseModel):
    url: str
    title: str = ""
    author: str = ""
    source: str = ""
    managed_source_id: str = ""
    chapters: list[URLImportChapter] = Field(default_factory=list)
    retry_limit: int = Field(default=2, ge=0, le=5)


class ManagedSource(BaseModel):
    id: str
    catalog_entry_id: str = ""
    name: str = ""
    base_url: str = ""
    domain: str = ""
    language: str = "zh-CN"
    parser_type: str = "policy_supported"
    parser_config: dict[str, Any] = Field(default_factory=dict)
    status: Literal["IMPORTED", "NEEDS_REVIEW", "VERIFIED", "BROKEN", "BLOCKED"] | str = "NEEDS_REVIEW"
    trust_level: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH", "MANUAL_ONLY"] | str = "MANUAL_ONLY"
    supported_source_id: str = ""
    last_test_status: str = ""
    last_tested_at: str = ""
    last_successful_fetch_at: str = ""
    last_error: str = ""
    rate_limit_requests_per_minute: int = 0
    rate_limit_delay_ms: int = 0
    max_concurrent_requests: int = 1
    cooldown_after_error_seconds: int = 0
    notes: str = ""
    can_use_in_jobs: bool = False
    created_at: str = ""
    updated_at: str = ""


class ManagedSourceList(BaseModel):
    items: list[ManagedSource] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50
    page_size: int = 50


class ManagedSourceTestResponse(BaseModel):
    source_id: str
    domain: str = ""
    status: Literal["reachable", "blocked_by_policy", "timeout", "invalid_url", "fetch_failed", "parse_failed", "parser_config_missing", "success"] | str
    reason: str = ""
    tested_at: str
    final_url: str = ""
    http_status: int | None = None


class ManagedSourceImportRequest(BaseModel):
    entry_ids: list[str] = Field(default_factory=list)


class ManagedSourceImportSummary(BaseModel):
    selected: int = 0
    inserted: int = 0
    duplicates: int = 0
    invalid: int = 0
    skipped: int = 0
    items: list[ManagedSource] = Field(default_factory=list)


class ManagedSourceUpdateRequest(BaseModel):
    status: str | None = None
    trust_level: str | None = None
    parser_type: str | None = None
    parser_config: dict[str, Any] | None = None
    notes: str | None = None
    rate_limit_requests_per_minute: int | None = None
    rate_limit_delay_ms: int | None = None
    max_concurrent_requests: int | None = None
    cooldown_after_error_seconds: int | None = None


class ImportResponse(BaseModel):
    book_id: int
    chapter_id: int
    path: str = ""
    message: str = "ok"


# ── Jobs ─────────────────────────────────────────────────────────────────

class JobStart(BaseModel):
    book_id: int | None = None
    chapter_ids: list[int] | None = None
    limit: int = 15
    params: dict[str, Any] = {}


class JobResponse(BaseModel):
    job_id: str
    status: str = "pending"
    message: str = ""


class JobStatus(BaseModel):
    job_id: str
    job_type: str = ""
    status: str
    state: str = ""
    progress: int = 0
    total: int = 0
    current_book_id: int = 0
    current_chapter_id: int = 0
    current_chunk_index: int = 0
    total_chunks: int = 0
    current_step: str = ""
    provider: str = ""
    model: str = ""
    target_ids: list[int] = Field(default_factory=list)
    message: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    failed_at: str = ""
    finished_at: str | None = None
    cancel_requested: bool = False
    last_safe_error: str = ""
    internal_error_ref: str = ""
    preset_id: str = ""
    chunk_size: int | None = None
    active_stage: str = ""
    stage_timings: list[dict[str, Any]] = Field(default_factory=list)
    retry_of_job_id: str = ""
    retry_count: int = 0
    previous_error: str = ""
    last_retry_job_id: str = ""
    skipped_completed_chapter_ids: list[int] = Field(default_factory=list)


class JobListResponse(BaseModel):
    jobs: list[JobStatus]


class JobLogEntry(BaseModel):
    id: int
    job_id: str
    event_type: str
    state: str = ""
    step: str = ""
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


# ── Export ────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    format: str = Field(..., pattern="^(txt|docx|epub)$")


class ExportResponse(BaseModel):
    book_id: int
    book_title: str
    format: str
    filename: str
    path: str
    download_url: str = ""
    media_type: str
    size_bytes: int
    chapter_count: int


class SystemBackupRequest(BaseModel):
    include_audio: bool = True
    include_exports: bool = False
    include_job_logs: bool = False
    include_secrets: bool = False
    passphrase: str = ""

    def validate_for_queue(self) -> None:
        if self.include_secrets and not self.passphrase.strip():
            raise ValueError("A passphrase is required when including secrets")


class SystemBackupItem(BaseModel):
    filename: str
    size_bytes: int = 0
    created_at: str = ""
    encrypted: bool = False
    secrets_included: bool = False
    included_modules: list[str] = Field(default_factory=list)
    excluded_modules: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    metadata_status: str = "METADATA_MISSING"
    repair_needed: bool = False
    manifest_available: bool = False
    archive_available: bool = False
    warning: str = ""
    download_url: str = ""


class SystemBackupListResponse(BaseModel):
    items: list[SystemBackupItem] = Field(default_factory=list)


# ── Audio ────────────────────────────────────────────────────────────────

class PlaylistItem(BaseModel):
    chapter_id: int
    chapter_number: int
    title: str
    duration_seconds: float = 0
    download_url: str
    filename: str
    order: int = 0
    size_bytes: int = 0
    stream_url: str


class PlaylistResponse(BaseModel):
    book_id: int
    book_title: str = ""
    chapters: list[PlaylistItem]


# ── Glossary ─────────────────────────────────────────────────────────────

class GlossaryTermCreate(BaseModel):
    source_term: str
    target_term: str
    book_id: int = 0
    category: str = "term"
    mode: str = "translate"
    pinyin: str = ""
    notes_vi: str = ""
    variants: str = ""
    approved: int = 1
    priority: int = 0
    locked: int = 0
    genre: str = ""
    term_type: str = "term"
    alternatives: str = ""
    gender: str = ""
    first_seen_chapter_id: int = 0
    first_seen_chapter_number: int = 0
    review_status: str = ""
    source_context: str = ""


class GlossaryTermUpdate(BaseModel):
    target_term: str | None = None
    category: str | None = None
    mode: str | None = None
    pinyin: str | None = None
    notes_vi: str | None = None
    variants: str | None = None
    approved: int | None = None
    priority: int | None = None
    locked: int | None = None
    genre: str | None = None
    term_type: str | None = None
    alternatives: str | None = None
    gender: str | None = None
    review_status: str | None = None
    source_context: str | None = None
    expected_version: int | None = Field(default=None, ge=0)


class GlossaryBulkTermRef(BaseModel):
    id: int = Field(gt=0)
    expected_version: int = Field(ge=0)


class GlossaryBulkRequest(BaseModel):
    action: Literal["approve", "reject", "lock", "archive"]
    terms: list[GlossaryBulkTermRef] = Field(min_length=1, max_length=200)


class GlossaryMergePreviewRequest(BaseModel):
    canonical_id: int = Field(gt=0)
    duplicate_ids: list[int] = Field(min_length=1, max_length=199)


class GlossaryMergeApplyRequest(GlossaryMergePreviewRequest):
    digest: str = Field(min_length=1, max_length=128)


class TranslationMemoryEntryCreate(BaseModel):
    source_text: str = Field(..., min_length=1)
    translation_text: str = Field(..., min_length=1)
    score: int = Field(default=85, ge=0, le=100)
    book_id: int = 0
    chapter_number: int | None = None
    source_lang: str = "zh"
    target_lang: str = "vi"


class GlossaryTermResponse(BaseModel):
    id: int
    book_id: int
    source_term: str
    target_term: str
    category: str = "term"
    mode: str = "translate"
    approved: int = 1
    pinyin: str = ""
    notes_vi: str = ""
    variants: str = ""
    occurrence_count: int = 0
    last_seen: str = ""
    priority: int = 0
    locked: int = 0
    genre: str = ""
    term_type: str = "term"
    alternatives: str = ""
    gender: str = ""
    first_seen_chapter_id: int = 0
    first_seen_chapter_number: int = 0
    review_status: str = ""
    source_context: str = ""
    created_at: str = ""
    updated_at: str = ""
    version: int = 0
    canonical_status: str = ""
    inherited: bool = False
    evidence_count: int = 0


class GlossarySearchResponse(BaseModel):
    results: list[GlossaryTermResponse]
    total: int = 0


class GlossaryListResponse(BaseModel):
    items: list[GlossaryTermResponse]
    total: int = 0
    page: int = 1
    per_page: int = 50
    pages: int = 0
    scope: str = "all"
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)


class ImportGlossaryResponse(BaseModel):
    added: int = 0
    updated: int = 0
    errors: list[str] = []


# ── Style Profiles ────────────────────────────────────────────────────────

class StyleProfileResponse(BaseModel):
    id: str
    label: str
    pronoun_rules: str = ""
    han_viet_level: str = "balanced"
    preferred_terms: str = ""
    banned_modern_terms: str = ""
    prompt_rules: str = ""
    is_default: int = 0
    created_at: str = ""
    updated_at: str = ""


class StyleProfileListResponse(BaseModel):
    profiles: list[StyleProfileResponse]


class StyleProfileDefaultResponse(BaseModel):
    profile: StyleProfileResponse


class StyleProfileDefaultUpdate(BaseModel):
    style_profile_id: str


# ── Providers ─────────────────────────────────────────────────────────────

class ProviderResponse(BaseModel):
    id: str
    label: str
    base_url: str
    model: str
    api_key_env: str = ""
    api_key_set: bool = False
    temperature: float = 0.3
    timeout_seconds: int = 180
    supports_streaming: int = 0
    supports_batch: int = 0
    cost_input_per_1m: float = 0
    cost_output_per_1m: float = 0
    enabled: int = 1
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class ProviderTestRequest(BaseModel):
    provider_id: str
    prompt: str = "Translate this Chinese sentence to Vietnamese: 他拿起灵石。"


class ProviderKeyUpdateRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


class CostEstimateRequest(BaseModel):
    provider_id: str
    source_chars: int = Field(..., ge=0)
    chapter_count: int = Field(default=1, ge=1)
    prompt_overhead_tokens: int = Field(default=1500, ge=0)
    max_cost_usd: float | None = None


class CostEstimateResponse(BaseModel):
    provider_id: str
    model: str
    chapter_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    within_budget: bool


# ── QA ───────────────────────────────────────────────────────────────────

class ParagraphPolishRequest(BaseModel):
    instructions: str = ""  # Optional style instructions


class QAResponse(BaseModel):
    chapter_id: int
    book_id: int
    quality_score: float = 0
    fidelity_score: float = 0
    style_score: float = 0
    glossary_score: float = 0
    audiobook_score: float = 0
    verdict: str = "UNKNOWN"
    issues: list[dict[str, Any]] = []
    raw_report: dict[str, Any] = {}
    created_at: str = ""


class QASummaryResponse(BaseModel):
    book_id: int
    total_chapters: int = 0
    qa_done: int = 0
    avg_quality_score: float = 0
    pass_count: int = 0
    fail_count: int = 0
    chapters: list[dict[str, Any]] = []


# ── Generic ──────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
