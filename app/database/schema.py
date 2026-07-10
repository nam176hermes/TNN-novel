"""SequelPro-compatible SQLite database migrations."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    book_key TEXT DEFAULT '',
    owner_user_id TEXT DEFAULT '',
    author TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',
    source_url TEXT DEFAULT '',
    cover_path TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    adapter_id TEXT DEFAULT '',
    raw_text_path TEXT,
    cleaned_text_path TEXT,
    translated_text_path TEXT,
    content_html_path TEXT,
    audio_path TEXT,
    source_hash TEXT DEFAULT '',
    status TEXT DEFAULT 'imported',
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    translated_at TIMESTAMP,
    audio_created_at TIMESTAMP,
    deleted_at TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_books_book_key ON books(book_key);
CREATE INDEX IF NOT EXISTS idx_books_owner_user_id ON books(owner_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chapters_active_number
    ON chapters(book_id, chapter_number)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chapters_active_source_hash
    ON chapters(book_id, source_hash)
    WHERE deleted_at IS NULL AND source_hash != '';

CREATE TABLE IF NOT EXISTS reader_progress (
    book_id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'scroll',
    percent INTEGER NOT NULL DEFAULT 0,
    paragraph_index INTEGER DEFAULT 0,
    char_offset INTEGER DEFAULT 0,
    absolute_char_offset INTEGER DEFAULT 0,
    page_index INTEGER DEFAULT 0,
    anchor_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reader_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('bookmark', 'highlight', 'note')),
    paragraph_index INTEGER NOT NULL DEFAULT 0,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    selected_text TEXT DEFAULT '',
    note TEXT DEFAULT '',
    color TEXT DEFAULT 'yellow',
    client_id TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_annotations_book
    ON reader_annotations(book_id, kind, deleted_at, chapter_id);
CREATE INDEX IF NOT EXISTS idx_reader_annotations_chapter
    ON reader_annotations(chapter_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_reader_annotations_client
    ON reader_annotations(book_id, client_id)
    WHERE client_id != '';

CREATE TABLE IF NOT EXISTS reader_ai_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    spoiler_mode TEXT NOT NULL DEFAULT 'no_spoiler',
    selected_text TEXT NOT NULL DEFAULT '',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(book_id, chapter_id, text_hash, spoiler_mode),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_ai_cache_lookup
    ON reader_ai_cache(book_id, chapter_id, text_hash, spoiler_mode);

CREATE TABLE IF NOT EXISTS reader_dictionary_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL DEFAULT 0,
    query TEXT NOT NULL DEFAULT '',
    query_norm TEXT NOT NULL,
    response_json TEXT NOT NULL DEFAULT '{}',
    source_count INTEGER NOT NULL DEFAULT 0,
    online_status TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(book_id, query_norm),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_dictionary_cache_lookup
    ON reader_dictionary_cache(book_id, query_norm);

CREATE TABLE IF NOT EXISTS reader_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('character', 'faction', 'location', 'item', 'realm', 'skill')),
    name TEXT NOT NULL,
    aliases_json TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    first_chapter_number INTEGER DEFAULT 0,
    importance INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(book_id, entity_type, name),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_entities_book_type
    ON reader_entities(book_id, entity_type, first_chapter_number);

CREATE TABLE IF NOT EXISTS reader_entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL DEFAULT 0,
    paragraph_index INTEGER NOT NULL DEFAULT 0,
    mention_text TEXT DEFAULT '',
    context TEXT DEFAULT '',
    spoiler_level INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES reader_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_entity_mentions_book_chapter
    ON reader_entity_mentions(book_id, chapter_number, entity_id);
CREATE INDEX IF NOT EXISTS idx_reader_entity_mentions_entity
    ON reader_entity_mentions(entity_id, chapter_number);

CREATE TABLE IF NOT EXISTS reader_timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL DEFAULT 0,
    event_order INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    spoiler_level INTEGER DEFAULT 0,
    entities_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reader_timeline_events_book_chapter
    ON reader_timeline_events(book_id, chapter_number, event_order);

CREATE TABLE IF NOT EXISTS glossary_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER DEFAULT 0,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT 'term',
    confidence REAL DEFAULT 1.0,
    approved INTEGER DEFAULT 1,
    mode TEXT DEFAULT '',
    pinyin TEXT DEFAULT '',
    notes_vi TEXT DEFAULT '',
    variants TEXT DEFAULT '',
    occurrence_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    locked INTEGER DEFAULT 0,
    genre TEXT DEFAULT '',
    term_type TEXT DEFAULT 'term',
    alternatives TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    first_seen_chapter_id INTEGER DEFAULT 0,
    first_seen_chapter_number INTEGER DEFAULT 0,
    review_status TEXT DEFAULT '',
    source_context TEXT DEFAULT '',
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT '',
    UNIQUE(book_id, source_term)
);

CREATE TABLE IF NOT EXISTS style_profiles (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    pronoun_rules TEXT DEFAULT '',
    han_viet_level TEXT DEFAULT 'balanced',
    preferred_terms TEXT DEFAULT '',
    banned_modern_terms TEXT DEFAULT '',
    prompt_rules TEXT DEFAULT '',
    is_default INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS translation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL,
    model TEXT,
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error TEXT,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS qa_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL DEFAULT 0,
    chapter_id INTEGER NOT NULL,
    quality_score REAL DEFAULT 0,
    fidelity_score REAL DEFAULT 0,
    style_score REAL DEFAULT 0,
    glossary_score REAL DEFAULT 0,
    audiobook_score REAL DEFAULT 0,
    verdict TEXT DEFAULT 'UNKNOWN',
    job_id TEXT DEFAULT '',
    overall_status TEXT DEFAULT 'NOT_RUN',
    missing_paragraph_warning INTEGER DEFAULT 0,
    chinese_leakage_count INTEGER DEFAULT 0,
    name_consistency_status TEXT DEFAULT 'NOT_RUN',
    term_consistency_status TEXT DEFAULT 'NOT_RUN',
    length_ratio REAL DEFAULT 0,
    repetition_warning INTEGER DEFAULT 0,
    style_warnings TEXT DEFAULT '[]',
    glossary_violations TEXT DEFAULT '[]',
    suggested_fixes TEXT DEFAULT '[]',
    report_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT '',
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chapter_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL UNIQUE,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS translation_cache (
    cache_key TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expiry_ts REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'env',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    disabled_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    user_id TEXT DEFAULT '',
    refresh_token_hash TEXT NOT NULL,
    refresh_family_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT DEFAULT '',
    last_seen_at TEXT DEFAULT '',
    client_host TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    request_id TEXT DEFAULT '',
    reuse_detected_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_username ON auth_sessions(username);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_revoked_at ON auth_sessions(revoked_at);

CREATE TABLE IF NOT EXISTS auth_login_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_limit_key TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    client_host TEXT DEFAULT '',
    failed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_login_failures_key_time
    ON auth_login_failures(rate_limit_key, failed_at);

CREATE TABLE IF NOT EXISTS tm_fuzzy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_hash TEXT NOT NULL UNIQUE,
    source_text TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    source_tokens TEXT NOT NULL,   -- space-separated tokens for matching
    score INTEGER NOT NULL,        -- similarity threshold used when stored
    source_lang TEXT DEFAULT 'zh',
    target_lang TEXT DEFAULT 'vi',
    book_id INTEGER DEFAULT 0,
    chapter_number INTEGER,
    usage_count INTEGER DEFAULT 0,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tm_fuzzy_source_hash ON tm_fuzzy(source_hash);
CREATE INDEX IF NOT EXISTS idx_tm_fuzzy_book ON tm_fuzzy(book_id, chapter_number);
CREATE INDEX IF NOT EXISTS idx_tm_fuzzy_usage ON tm_fuzzy(usage_count DESC);

CREATE TABLE IF NOT EXISTS translation_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    q TEXT NOT NULL,
    s TEXT NOT NULL,
    source_lang TEXT DEFAULT 'zh',
    target_lang TEXT DEFAULT 'vi',
    book_id INTEGER DEFAULT 0,
    chapter_number INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    source_chunk TEXT NOT NULL,
    pipe_out TEXT NOT NULL,
    user_fix TEXT NOT NULL,
    correction_type TEXT DEFAULT 'terminology',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_corrections_ts ON user_corrections(created_at);

CREATE TABLE IF NOT EXISTS model_providers (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_env TEXT DEFAULT '',
    temperature REAL DEFAULT 0.3,
    timeout_seconds INTEGER DEFAULT 180,
    supports_streaming INTEGER DEFAULT 0,
    supports_batch INTEGER DEFAULT 0,
    cost_input_per_1m REAL DEFAULT 0,
    cost_output_per_1m REAL DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provider_defaults (
    task_type TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES model_providers(id)
);

CREATE TABLE IF NOT EXISTS provider_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    owner_user_id TEXT DEFAULT '',
    model TEXT NOT NULL,
    task_type TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0,
    job_id TEXT DEFAULT '',
    chapter_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_provider_usage_owner_user_id ON provider_usage(owner_user_id);

CREATE TABLE IF NOT EXISTS job_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    chapter_id INTEGER,
    stage TEXT DEFAULT '',
    owner_user_id TEXT DEFAULT '',
    provider_id TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT DEFAULT '',
    elapsed_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_job_attempts_job_id ON job_attempts(job_id);
CREATE INDEX IF NOT EXISTS idx_job_attempts_chapter_id ON job_attempts(chapter_id);
CREATE INDEX IF NOT EXISTS idx_job_attempts_owner_user_id ON job_attempts(owner_user_id);

CREATE TABLE IF NOT EXISTS mobile_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    owner_user_id TEXT DEFAULT '',
    status TEXT NOT NULL,
    state TEXT DEFAULT 'QUEUED',
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    current_book_id INTEGER DEFAULT 0,
    current_chapter_id INTEGER DEFAULT 0,
    current_chunk_index INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 0,
    current_step TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    target_ids_json TEXT DEFAULT '[]',
    params_json TEXT DEFAULT '{}',
    message TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT DEFAULT '',
    completed_at TEXT DEFAULT '',
    failed_at TEXT DEFAULT '',
    finished_at TEXT,
    cancel_requested INTEGER DEFAULT 0,
    last_safe_error TEXT DEFAULT '',
    internal_error_ref TEXT DEFAULT '',
    lease_token TEXT DEFAULT '',
    lease_owner TEXT DEFAULT '',
    lease_expires_at TEXT DEFAULT '',
    heartbeat_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mobile_jobs_created_at ON mobile_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mobile_jobs_status ON mobile_jobs(status);
CREATE INDEX IF NOT EXISTS idx_mobile_jobs_state ON mobile_jobs(state);
CREATE INDEX IF NOT EXISTS idx_mobile_jobs_lease_expires_at ON mobile_jobs(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_mobile_jobs_owner_user_id ON mobile_jobs(owner_user_id);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    state TEXT DEFAULT '',
    step TEXT DEFAULT '',
    message TEXT DEFAULT '',
    details_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs(job_id, id DESC);

CREATE TABLE IF NOT EXISTS tts_jobs (
    id TEXT PRIMARY KEY,
    book_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    owner_user_id TEXT DEFAULT '',
    voice_config_hash TEXT NOT NULL DEFAULT '',
    text_hash TEXT NOT NULL DEFAULT '',
    output_mp3_path TEXT DEFAULT '',
    output_m4b_path TEXT DEFAULT '',
    report_json_path TEXT DEFAULT '',
    progress INTEGER NOT NULL DEFAULT 0,
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tts_jobs_book_chapter ON tts_jobs(book_id, chapter_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tts_jobs_status ON tts_jobs(status);
CREATE INDEX IF NOT EXISTS idx_tts_jobs_owner_user_id ON tts_jobs(owner_user_id);

CREATE TABLE IF NOT EXISTS tts_chunks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    normalized_text TEXT NOT NULL DEFAULT '',
    text_hash TEXT NOT NULL DEFAULT '',
    start_char INTEGER NOT NULL DEFAULT 0,
    end_char INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    wav_path TEXT DEFAULT '',
    mp3_path TEXT DEFAULT '',
    duration_seconds REAL DEFAULT 0,
    qa_status TEXT DEFAULT '',
    qa_report_json TEXT DEFAULT '{}',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, chunk_index),
    FOREIGN KEY (job_id) REFERENCES tts_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tts_chunks_job_status ON tts_chunks(job_id, status);
CREATE INDEX IF NOT EXISTS idx_tts_chunks_hash ON tts_chunks(text_hash);

CREATE TABLE IF NOT EXISTS operational_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    source TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    actor_user_id TEXT DEFAULT '',
    owner_user_id TEXT DEFAULT '',
    details_json TEXT DEFAULT '{}',
    job_id TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_operational_events_created_at ON operational_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operational_events_severity ON operational_events(severity);
CREATE INDEX IF NOT EXISTS idx_operational_events_actor ON operational_events(actor_user_id);

CREATE TABLE IF NOT EXISTS ebook_import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER DEFAULT 0,
    owner_user_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    filename TEXT DEFAULT '',
    source_format TEXT DEFAULT '',
    duplicate_strategy TEXT DEFAULT '',
    split_mode TEXT DEFAULT '',
    chapter_count INTEGER DEFAULT 0,
    imported_chapters INTEGER DEFAULT 0,
    skipped_chapters INTEGER DEFAULT 0,
    overwritten_chapters INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    warnings_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ebook_import_runs_created_at ON ebook_import_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ebook_import_runs_owner_user_id ON ebook_import_runs(owner_user_id);

CREATE TABLE IF NOT EXISTS source_catalog_entries (
    id TEXT PRIMARY KEY,
    external_id TEXT NOT NULL DEFAULT '',
    catalog_source TEXT NOT NULL DEFAULT 'yckceo',
    name TEXT NOT NULL DEFAULT '',
    url TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    author TEXT DEFAULT '',
    downloads INTEGER DEFAULT 0,
    version TEXT DEFAULT '',
    raw_tags TEXT DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    unknown_tags_json TEXT NOT NULL DEFAULT '[]',
    supported_status TEXT NOT NULL DEFAULT 'unsupported',
    supported_source_id TEXT DEFAULT '',
    invalid_reason TEXT DEFAULT '',
    updated_label TEXT DEFAULT '',
    last_check_status TEXT DEFAULT '',
    last_check_at TEXT DEFAULT '',
    last_check_error TEXT DEFAULT '',
    last_check_http_status INTEGER,
    last_check_final_url TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(catalog_source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_source_catalog_domain ON source_catalog_entries(domain);
CREATE INDEX IF NOT EXISTS idx_source_catalog_supported ON source_catalog_entries(supported_status);
CREATE INDEX IF NOT EXISTS idx_source_catalog_downloads ON source_catalog_entries(downloads DESC);
CREATE INDEX IF NOT EXISTS idx_source_catalog_updated ON source_catalog_entries(updated_at DESC);

CREATE TABLE IF NOT EXISTS source_catalog_health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_entry_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT DEFAULT '',
    http_status INTEGER,
    final_url TEXT DEFAULT '',
    checked_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_source_catalog_health_entry ON source_catalog_health_checks(catalog_entry_id);
CREATE INDEX IF NOT EXISTS idx_source_catalog_health_checked ON source_catalog_health_checks(checked_at DESC);

CREATE TABLE IF NOT EXISTS source_adapter_candidates (
    id TEXT PRIMARY KEY,
    catalog_entry_id TEXT NOT NULL,
    domain TEXT DEFAULT '',
    sample_url TEXT DEFAULT '',
    detected_title TEXT DEFAULT '',
    detected_chapter_list TEXT DEFAULT '[]',
    parser_confidence TEXT DEFAULT 'low',
    failure_reason TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT DEFAULT '',
    reviewed_by TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_entry ON source_adapter_candidates(catalog_entry_id);
CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_domain ON source_adapter_candidates(domain);
CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_status ON source_adapter_candidates(status);
CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_created ON source_adapter_candidates(created_at DESC);

CREATE TABLE IF NOT EXISTS managed_sources (
    id TEXT PRIMARY KEY,
    catalog_entry_id TEXT DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'zh-CN',
    parser_type TEXT NOT NULL DEFAULT 'policy_supported',
    parser_config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'NEEDS_REVIEW',
    trust_level TEXT NOT NULL DEFAULT 'MANUAL_ONLY',
    supported_source_id TEXT DEFAULT '',
    last_test_status TEXT DEFAULT '',
    last_tested_at TEXT DEFAULT '',
    last_successful_fetch_at TEXT DEFAULT '',
    last_error TEXT DEFAULT '',
    rate_limit_requests_per_minute INTEGER DEFAULT 6,
    rate_limit_delay_ms INTEGER DEFAULT 8000,
    max_concurrent_requests INTEGER DEFAULT 1,
    cooldown_after_error_seconds INTEGER DEFAULT 900,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(catalog_entry_id),
    UNIQUE(base_url)
);
CREATE INDEX IF NOT EXISTS idx_managed_sources_catalog_entry ON managed_sources(catalog_entry_id);
CREATE INDEX IF NOT EXISTS idx_managed_sources_domain ON managed_sources(domain);
CREATE INDEX IF NOT EXISTS idx_managed_sources_status ON managed_sources(status);
CREATE INDEX IF NOT EXISTS idx_managed_sources_trust ON managed_sources(trust_level);
CREATE INDEX IF NOT EXISTS idx_managed_sources_updated ON managed_sources(updated_at DESC);

CREATE TABLE IF NOT EXISTS managed_source_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT DEFAULT '',
    http_status INTEGER,
    final_url TEXT DEFAULT '',
    tested_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_managed_source_tests_source ON managed_source_tests(source_id);
CREATE INDEX IF NOT EXISTS idx_managed_source_tests_tested ON managed_source_tests(tested_at DESC);
"""
