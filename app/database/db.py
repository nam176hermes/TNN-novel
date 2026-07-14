from __future__ import annotations

import hashlib
import os
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.database import auth_repository as _auth_repository
from app.database import operations_repository as _operations_repository
from app.database import reader_repository as _reader_repository
from app.database.connection import get_connection
from app.database.schema import SCHEMA
from app.database.glossary_history import log_glossary_change
from app.mobile_api.job_states import normalize_job_state
from app.mobile_api.services.import_metadata import normalize_book_key
from app.translation.styleguide_config import get_locked_terms


_utcnow_text = _auth_repository._utcnow_text
auth_session_is_active = _auth_repository.auth_session_is_active
clear_auth_login_failures = _auth_repository.clear_auth_login_failures
count_auth_login_failures = _auth_repository.count_auth_login_failures
create_auth_session = _auth_repository.create_auth_session
get_auth_session = _auth_repository.get_auth_session
record_auth_login_failure = _auth_repository.record_auth_login_failure
revoke_auth_session = _auth_repository.revoke_auth_session
revoke_auth_sessions_for_username = _auth_repository.revoke_auth_sessions_for_username
rotate_auth_session_refresh = _auth_repository.rotate_auth_session_refresh
touch_auth_session = _auth_repository.touch_auth_session

list_operational_events = _operations_repository.list_operational_events
record_operational_event = _operations_repository.record_operational_event

get_reader_progress = _reader_repository.get_reader_progress
upsert_reader_progress = _reader_repository.upsert_reader_progress
list_reader_annotations = _reader_repository.list_reader_annotations
get_reader_annotation = _reader_repository.get_reader_annotation
get_reader_annotation_by_client_id = _reader_repository.get_reader_annotation_by_client_id
add_reader_annotation = _reader_repository.add_reader_annotation
update_reader_annotation = _reader_repository.update_reader_annotation
soft_delete_reader_annotation = _reader_repository.soft_delete_reader_annotation
get_reader_ai_cache = _reader_repository.get_reader_ai_cache
upsert_reader_ai_cache = _reader_repository.upsert_reader_ai_cache
get_reader_dictionary_cache = _reader_repository.get_reader_dictionary_cache
upsert_reader_dictionary_cache = _reader_repository.upsert_reader_dictionary_cache
add_reader_entity = _reader_repository.add_reader_entity
add_reader_entity_mention = _reader_repository.add_reader_entity_mention
add_reader_timeline_event = _reader_repository.add_reader_timeline_event
list_reader_xray_entities = _reader_repository.list_reader_xray_entities
list_reader_timeline_events = _reader_repository.list_reader_timeline_events


CURRENT_SCHEMA_VERSION = "2026-07-09-source-catalog-phase8"


def get_db_path(data_dir: Path) -> Path:
    return data_dir / "pipeline.db"


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
           version TEXT PRIMARY KEY,
           applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def _record_schema_migration(conn: sqlite3.Connection, version: str) -> None:
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (version,))


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_default(conn: sqlite3.Connection, table_name: str, column_name: str) -> str | None:
    for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall():
        if row["name"] == column_name:
            return row["dflt_value"]
    return None


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_sql: str) -> bool:
    column_name = column_sql.split()[0]
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
        return True
    return False


def _glossary_review_status(approved: int = 1, locked: int = 0, review_status: str = "") -> str:
    normalized = str(review_status or "").strip().upper()
    if normalized in {"NEEDS_REVIEW", "APPROVED", "REJECTED", "CONFLICT", "LOCKED"}:
        return normalized
    if int(locked or 0):
        return "LOCKED"
    if int(approved or 0) < 0:
        return "REJECTED"
    if int(approved or 0) == 1:
        return "APPROVED"
    return "NEEDS_REVIEW"


def _ensure_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT DEFAULT '',
            source TEXT NOT NULL DEFAULT 'env',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disabled_at TEXT DEFAULT ''
        )
        """
    )
    _add_column_if_missing(conn, "users", "username TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "display_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "source TEXT DEFAULT 'env'")
    _add_column_if_missing(conn, "users", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "updated_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "disabled_at TEXT DEFAULT ''")


def _ensure_source_catalog_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(catalog_source, external_id)
        )
        """
    )
    _add_column_if_missing(conn, "source_catalog_entries", "id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "external_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "catalog_source TEXT DEFAULT 'yckceo'")
    _add_column_if_missing(conn, "source_catalog_entries", "name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "domain TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "author TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "downloads INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "source_catalog_entries", "version TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "raw_tags TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "tags_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "source_catalog_entries", "unknown_tags_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "source_catalog_entries", "supported_status TEXT DEFAULT 'unsupported'")
    _add_column_if_missing(conn, "source_catalog_entries", "supported_source_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "invalid_reason TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "updated_label TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "last_check_status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "last_check_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "last_check_error TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "last_check_http_status INTEGER")
    _add_column_if_missing(conn, "source_catalog_entries", "last_check_final_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_entries", "updated_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_domain ON source_catalog_entries(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_supported ON source_catalog_entries(supported_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_downloads ON source_catalog_entries(downloads DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_updated ON source_catalog_entries(updated_at DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_catalog_health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalog_entry_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT DEFAULT '',
            http_status INTEGER,
            final_url TEXT DEFAULT '',
            checked_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _add_column_if_missing(conn, "source_catalog_health_checks", "catalog_entry_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_health_checks", "status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_health_checks", "reason TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_health_checks", "http_status INTEGER")
    _add_column_if_missing(conn, "source_catalog_health_checks", "final_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_health_checks", "checked_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_catalog_health_checks", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_health_entry ON source_catalog_health_checks(catalog_entry_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_catalog_health_checked ON source_catalog_health_checks(checked_at DESC)")


def _ensure_source_adapter_candidates_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    _add_column_if_missing(conn, "source_adapter_candidates", "catalog_entry_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "domain TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "sample_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "detected_title TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "detected_chapter_list TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "source_adapter_candidates", "parser_confidence TEXT DEFAULT 'low'")
    _add_column_if_missing(conn, "source_adapter_candidates", "failure_reason TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "status TEXT DEFAULT 'draft'")
    _add_column_if_missing(conn, "source_adapter_candidates", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "updated_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "reviewed_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "source_adapter_candidates", "reviewed_by TEXT DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_entry "
        "ON source_adapter_candidates(catalog_entry_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_domain "
        "ON source_adapter_candidates(domain)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_status "
        "ON source_adapter_candidates(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_adapter_candidates_created "
        "ON source_adapter_candidates(created_at DESC)"
    )


def _ensure_managed_sources_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    _add_column_if_missing(conn, "managed_sources", "catalog_entry_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "base_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "domain TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "language TEXT DEFAULT 'zh-CN'")
    _add_column_if_missing(conn, "managed_sources", "parser_type TEXT DEFAULT 'policy_supported'")
    _add_column_if_missing(conn, "managed_sources", "parser_config_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "managed_sources", "status TEXT DEFAULT 'NEEDS_REVIEW'")
    _add_column_if_missing(conn, "managed_sources", "trust_level TEXT DEFAULT 'MANUAL_ONLY'")
    _add_column_if_missing(conn, "managed_sources", "supported_source_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "last_test_status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "last_tested_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "last_successful_fetch_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "last_error TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "rate_limit_requests_per_minute INTEGER DEFAULT 6")
    _add_column_if_missing(conn, "managed_sources", "rate_limit_delay_ms INTEGER DEFAULT 8000")
    _add_column_if_missing(conn, "managed_sources", "max_concurrent_requests INTEGER DEFAULT 1")
    _add_column_if_missing(conn, "managed_sources", "cooldown_after_error_seconds INTEGER DEFAULT 900")
    _add_column_if_missing(conn, "managed_sources", "notes TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_sources", "updated_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_sources_catalog_entry ON managed_sources(catalog_entry_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_sources_domain ON managed_sources(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_sources_status ON managed_sources(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_sources_trust ON managed_sources(trust_level)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_sources_updated ON managed_sources(updated_at DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS managed_source_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT DEFAULT '',
            http_status INTEGER,
            final_url TEXT DEFAULT '',
            tested_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _add_column_if_missing(conn, "managed_source_tests", "source_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_source_tests", "status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_source_tests", "reason TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_source_tests", "http_status INTEGER")
    _add_column_if_missing(conn, "managed_source_tests", "final_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_source_tests", "tested_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "managed_source_tests", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_source_tests_source ON managed_source_tests(source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_source_tests_tested ON managed_source_tests(tested_at DESC)")


def _normalize_operator_username(username: str | None = None) -> str:
    value = (username if username is not None else os.getenv("MOBILE_API_ADMIN_USERNAME", "admin")).strip()
    return value or "admin"


def _stable_operator_user_id(username: str) -> str:
    normalized = username.strip().lower()
    digest = hashlib.sha256(f"novel-pipeline:env-operator:{normalized}".encode("utf-8")).hexdigest()
    return f"usr_{digest[:32]}"


def _seed_operator_user(conn: sqlite3.Connection, username: str | None = None) -> dict[str, Any]:
    _ensure_users_table(conn)
    resolved_username = _normalize_operator_username(username)
    now = _utcnow_text()
    existing = conn.execute(
        """
        SELECT * FROM users
        WHERE source = 'env'
        ORDER BY created_at, id
        LIMIT 1
        """
    ).fetchone()

    if existing is not None:
        if existing["username"] != resolved_username or existing["disabled_at"]:
            conn.execute(
                """
                UPDATE users
                SET username = ?, updated_at = ?, disabled_at = ''
                WHERE id = ?
                """,
                (resolved_username, now, existing["id"]),
            )
            existing = conn.execute("SELECT * FROM users WHERE id = ?", (existing["id"],)).fetchone()
        return dict(existing)

    matching_username = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (resolved_username,),
    ).fetchone()
    if matching_username is not None:
        conn.execute(
            """
            UPDATE users
            SET source = 'env', updated_at = ?, disabled_at = ''
            WHERE id = ?
            """,
            (now, matching_username["id"]),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (matching_username["id"],)).fetchone()
        return dict(row)

    user_id = _stable_operator_user_id(resolved_username)
    conn.execute(
        """
        INSERT INTO users
        (id, username, display_name, source, created_at, updated_at, disabled_at)
        VALUES (?, ?, '', 'env', ?, ?, '')
        """,
        (user_id, resolved_username, now, now),
    )
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row)


def _seed_operator_user_from_env(conn: sqlite3.Connection) -> dict[str, Any]:
    return _seed_operator_user(conn, os.getenv("MOBILE_API_ADMIN_USERNAME", "admin"))


OWNER_METADATA_TABLES = (
    "books",
    "mobile_jobs",
    "ebook_import_runs",
    "provider_usage",
    "job_attempts",
)


def _ensure_owner_metadata_columns(conn: sqlite3.Connection) -> None:
    for table_name in OWNER_METADATA_TABLES:
        if _table_exists(conn, table_name):
            _add_column_if_missing(conn, table_name, "owner_user_id TEXT DEFAULT ''")
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_owner_user_id ON {table_name}(owner_user_id)"
            )


def _backfill_owner_user_ids(conn: sqlite3.Connection, owner_user_id: str) -> None:
    if not owner_user_id:
        return
    _ensure_owner_metadata_columns(conn)
    for table_name in OWNER_METADATA_TABLES:
        if _table_exists(conn, table_name):
            conn.execute(
                f"""
                UPDATE {table_name}
                SET owner_user_id = ?
                WHERE owner_user_id IS NULL OR owner_user_id = ''
                """,
                (owner_user_id,),
            )


def _ensure_tts_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        """
    )
    for column_sql in (
        "provider TEXT DEFAULT ''",
        "model TEXT DEFAULT ''",
        "owner_user_id TEXT DEFAULT ''",
        "voice_config_hash TEXT DEFAULT ''",
        "text_hash TEXT DEFAULT ''",
        "output_mp3_path TEXT DEFAULT ''",
        "output_m4b_path TEXT DEFAULT ''",
        "report_json_path TEXT DEFAULT ''",
        "progress INTEGER DEFAULT 0",
        "error_message TEXT DEFAULT ''",
        "created_at TEXT DEFAULT ''",
        "updated_at TEXT DEFAULT ''",
    ):
        _add_column_if_missing(conn, "tts_jobs", column_sql)
    for column_sql in (
        "text TEXT DEFAULT ''",
        "normalized_text TEXT DEFAULT ''",
        "text_hash TEXT DEFAULT ''",
        "start_char INTEGER DEFAULT 0",
        "end_char INTEGER DEFAULT 0",
        "wav_path TEXT DEFAULT ''",
        "mp3_path TEXT DEFAULT ''",
        "duration_seconds REAL DEFAULT 0",
        "qa_status TEXT DEFAULT ''",
        "qa_report_json TEXT DEFAULT '{}'",
        "error_message TEXT DEFAULT ''",
        "created_at TEXT DEFAULT ''",
        "updated_at TEXT DEFAULT ''",
    ):
        _add_column_if_missing(conn, "tts_chunks", column_sql)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tts_jobs_book_chapter ON tts_jobs(book_id, chapter_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tts_jobs_status ON tts_jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tts_jobs_owner_user_id ON tts_jobs(owner_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tts_chunks_job_status ON tts_chunks(job_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tts_chunks_hash ON tts_chunks(text_hash)")


def _rebuild_glossary_terms_table(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)").fetchall()}
    needs_rebuild = _column_default(conn, "glossary_terms", "occurrence_count") not in {"0", "0.0"}
    needs_rebuild = needs_rebuild or "priority" not in columns
    needs_rebuild = needs_rebuild or "locked" not in columns
    needs_rebuild = needs_rebuild or "genre" not in columns
    needs_rebuild = needs_rebuild or "term_type" not in columns
    if not needs_rebuild:
        return

    conn.execute("ALTER TABLE glossary_terms RENAME TO glossary_terms_legacy")
    conn.execute(
        """
        CREATE TABLE glossary_terms (
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
        )
        """
    )

    target_columns = [
        "id",
        "book_id",
        "source_term",
        "target_term",
        "category",
        "confidence",
        "approved",
        "mode",
        "pinyin",
        "notes_vi",
        "variants",
        "occurrence_count",
        "priority",
        "locked",
        "genre",
        "term_type",
        "alternatives",
        "gender",
        "first_seen_chapter_id",
        "first_seen_chapter_number",
        "review_status",
        "source_context",
        "last_seen",
        "created_at",
        "updated_at",
    ]
    copied_columns = [column for column in target_columns if column in columns]
    conn.execute(
        f"""
        INSERT INTO glossary_terms ({', '.join(copied_columns)})
        SELECT {', '.join(copied_columns)}
        FROM glossary_terms_legacy
        """
    )
    conn.execute("DROP TABLE glossary_terms_legacy")


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """Bring existing SQLite databases up to the current schema."""
    _ensure_users_table(conn)
    conn.executescript(
        """
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

        CREATE TABLE IF NOT EXISTS job_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            chapter_id INTEGER,
            owner_user_id TEXT DEFAULT '',
            provider_id TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT DEFAULT '',
            elapsed_ms INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

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

        CREATE TABLE IF NOT EXISTS auth_login_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_limit_key TEXT NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            client_host TEXT DEFAULT '',
            failed_at TEXT NOT NULL
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
        """
    )
    _add_column_if_missing(conn, "model_providers", "label TEXT DEFAULT ''")
    _add_column_if_missing(conn, "model_providers", "base_url TEXT DEFAULT ''")
    _add_column_if_missing(conn, "model_providers", "model TEXT DEFAULT ''")
    api_key_env_added = _add_column_if_missing(conn, "model_providers", "api_key_env TEXT DEFAULT ''")
    model_provider_columns_added = {
        "temperature": _add_column_if_missing(conn, "model_providers", "temperature REAL DEFAULT 0.3"),
        "supports_streaming": _add_column_if_missing(conn, "model_providers", "supports_streaming INTEGER DEFAULT 0"),
        "supports_batch": _add_column_if_missing(conn, "model_providers", "supports_batch INTEGER DEFAULT 0"),
        "cost_input_per_1m": _add_column_if_missing(conn, "model_providers", "cost_input_per_1m REAL DEFAULT 0"),
        "cost_output_per_1m": _add_column_if_missing(conn, "model_providers", "cost_output_per_1m REAL DEFAULT 0"),
    }
    _add_column_if_missing(conn, "model_providers", "timeout_seconds INTEGER DEFAULT 180")
    _add_column_if_missing(conn, "model_providers", "enabled INTEGER DEFAULT 1")
    notes_added = _add_column_if_missing(conn, "model_providers", "notes TEXT DEFAULT ''")
    _add_column_if_missing(conn, "model_providers", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "model_providers", "updated_at TEXT DEFAULT ''")
    default_provider_ids = tuple(provider["id"] for provider in DEFAULT_MODEL_PROVIDERS)
    default_provider_placeholders = ", ".join("?" for _ in default_provider_ids)
    for column_name, was_added in model_provider_columns_added.items():
        if was_added:
            conn.execute(
                f"UPDATE model_providers SET {column_name} = NULL WHERE id IN ({default_provider_placeholders})",
                default_provider_ids,
            )
    if api_key_env_added:
        conn.execute(
            f"UPDATE model_providers SET api_key_env = NULL WHERE id IN ({default_provider_placeholders})",
            default_provider_ids,
        )
    if notes_added:
        conn.execute(
            f"UPDATE model_providers SET notes = NULL WHERE id IN ({default_provider_placeholders})",
            default_provider_ids,
        )

    _add_column_if_missing(conn, "provider_defaults", "provider_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_defaults", "updated_at TEXT DEFAULT ''")

    _add_column_if_missing(conn, "provider_usage", "provider_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_usage", "owner_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_usage", "model TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_usage", "task_type TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_usage", "prompt_tokens INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "provider_usage", "completion_tokens INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "provider_usage", "total_tokens INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "provider_usage", "estimated_cost_usd REAL DEFAULT 0")
    _add_column_if_missing(conn, "provider_usage", "job_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "provider_usage", "chapter_id INTEGER")
    _add_column_if_missing(conn, "provider_usage", "created_at TEXT DEFAULT ''")

    _add_column_if_missing(conn, "job_attempts", "job_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "chapter_id INTEGER")
    _add_column_if_missing(conn, "job_attempts", "owner_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "stage TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "provider_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "model TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "error TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_attempts", "elapsed_ms INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "job_attempts", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_attempts_job_id ON job_attempts(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_attempts_chapter_id ON job_attempts(chapter_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_attempts_owner_user_id ON job_attempts(owner_user_id)")

    _add_column_if_missing(conn, "mobile_jobs", "job_type TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "owner_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "status TEXT DEFAULT 'pending'")
    _add_column_if_missing(conn, "mobile_jobs", "state TEXT DEFAULT 'QUEUED'")
    _add_column_if_missing(conn, "mobile_jobs", "progress INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "total INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "current_book_id INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "current_chapter_id INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "current_chunk_index INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "total_chunks INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "current_step TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "provider TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "model TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "retry_count INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "target_ids_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "mobile_jobs", "params_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "mobile_jobs", "message TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "error TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "updated_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "started_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "completed_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "failed_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "finished_at TEXT")
    _add_column_if_missing(conn, "mobile_jobs", "cancel_requested INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "mobile_jobs", "last_safe_error TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "internal_error_ref TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "lease_token TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "lease_owner TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "lease_expires_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "mobile_jobs", "heartbeat_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_jobs_created_at ON mobile_jobs(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_jobs_status ON mobile_jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_jobs_state ON mobile_jobs(state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_jobs_lease_expires_at ON mobile_jobs(lease_expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mobile_jobs_owner_user_id ON mobile_jobs(owner_user_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            state TEXT DEFAULT '',
            step TEXT DEFAULT '',
            message TEXT DEFAULT '',
            details_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _add_column_if_missing(conn, "job_logs", "job_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_logs", "event_type TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_logs", "state TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_logs", "step TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_logs", "message TEXT DEFAULT ''")
    _add_column_if_missing(conn, "job_logs", "details_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "job_logs", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs(job_id, id DESC)")

    _ensure_tts_tables(conn)

    conn.execute(
        """
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
        )
        """
    )
    _add_column_if_missing(conn, "operational_events", "event_type TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "severity TEXT DEFAULT 'info'")
    _add_column_if_missing(conn, "operational_events", "source TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "message TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "actor_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "owner_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "details_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "operational_events", "job_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "operational_events", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_events_created_at ON operational_events(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_events_severity ON operational_events(severity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_events_actor ON operational_events(actor_user_id)")

    conn.execute(
        """
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
        )
        """
    )
    _add_column_if_missing(conn, "auth_sessions", "session_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "username TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "refresh_token_hash TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "refresh_family_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "expires_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "revoked_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "last_seen_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "client_host TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "user_agent TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "request_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_sessions", "reuse_detected_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_username ON auth_sessions(username)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_revoked_at ON auth_sessions(revoked_at)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_login_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_limit_key TEXT NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            client_host TEXT DEFAULT '',
            failed_at TEXT NOT NULL
        )
        """
    )
    _add_column_if_missing(conn, "auth_login_failures", "rate_limit_key TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_login_failures", "username TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_login_failures", "client_host TEXT DEFAULT ''")
    _add_column_if_missing(conn, "auth_login_failures", "failed_at TEXT DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_login_failures_key_time "
        "ON auth_login_failures(rate_limit_key, failed_at)"
    )

    _add_column_if_missing(conn, "ebook_import_runs", "book_id INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "owner_user_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "title TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "filename TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "source_format TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "duplicate_strategy TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "split_mode TEXT DEFAULT ''")
    _add_column_if_missing(conn, "ebook_import_runs", "chapter_count INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "imported_chapters INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "skipped_chapters INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "overwritten_chapters INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "warning_count INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "ebook_import_runs", "warnings_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "ebook_import_runs", "created_at TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ebook_import_runs_created_at ON ebook_import_runs(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ebook_import_runs_owner_user_id ON ebook_import_runs(owner_user_id)")

    _ensure_source_catalog_table(conn)
    _ensure_source_adapter_candidates_table(conn)
    _ensure_managed_sources_table(conn)

    _add_column_if_missing(conn, "reader_progress", "chapter_id INTEGER")
    _add_column_if_missing(conn, "reader_progress", "mode TEXT NOT NULL DEFAULT 'scroll'")
    _add_column_if_missing(conn, "reader_progress", "percent INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_progress", "paragraph_index INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_progress", "char_offset INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_progress", "absolute_char_offset INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_progress", "page_index INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_progress", "anchor_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "reader_progress", "updated_at TEXT DEFAULT ''")

    _add_column_if_missing(conn, "reader_annotations", "book_id INTEGER")
    _add_column_if_missing(conn, "reader_annotations", "chapter_id INTEGER")
    _add_column_if_missing(conn, "reader_annotations", "kind TEXT DEFAULT 'highlight'")
    _add_column_if_missing(conn, "reader_annotations", "paragraph_index INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_annotations", "char_start INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_annotations", "char_end INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_annotations", "selected_text TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_annotations", "note TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_annotations", "color TEXT DEFAULT 'yellow'")
    _add_column_if_missing(conn, "reader_annotations", "client_id TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_annotations", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_annotations", "updated_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_annotations", "deleted_at TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_annotations_book
        ON reader_annotations(book_id, kind, deleted_at, chapter_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_annotations_chapter
        ON reader_annotations(chapter_id, deleted_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_annotations_client
        ON reader_annotations(book_id, client_id)
        WHERE client_id != ''
        """
    )
    _add_column_if_missing(conn, "reader_ai_cache", "book_id INTEGER")
    _add_column_if_missing(conn, "reader_ai_cache", "chapter_id INTEGER")
    _add_column_if_missing(conn, "reader_ai_cache", "text_hash TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_ai_cache", "spoiler_mode TEXT NOT NULL DEFAULT 'no_spoiler'")
    _add_column_if_missing(conn, "reader_ai_cache", "selected_text TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "reader_ai_cache", "response_json TEXT NOT NULL DEFAULT '{}'")
    _add_column_if_missing(conn, "reader_ai_cache", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_ai_cache", "updated_at TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_ai_cache_lookup
        ON reader_ai_cache(book_id, chapter_id, text_hash, spoiler_mode)
        """
    )
    _add_column_if_missing(conn, "reader_dictionary_cache", "book_id INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_dictionary_cache", "query TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "reader_dictionary_cache", "query_norm TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "reader_dictionary_cache", "response_json TEXT NOT NULL DEFAULT '{}'")
    _add_column_if_missing(conn, "reader_dictionary_cache", "source_count INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_dictionary_cache", "online_status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_dictionary_cache", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_dictionary_cache", "updated_at TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_dictionary_cache_lookup
        ON reader_dictionary_cache(book_id, query_norm)
        """
    )
    _add_column_if_missing(conn, "reader_entities", "book_id INTEGER")
    _add_column_if_missing(conn, "reader_entities", "entity_type TEXT DEFAULT 'character'")
    _add_column_if_missing(conn, "reader_entities", "name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_entities", "aliases_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "reader_entities", "description TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_entities", "first_chapter_number INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_entities", "importance INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_entities", "metadata_json TEXT DEFAULT '{}'")
    _add_column_if_missing(conn, "reader_entities", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_entities", "updated_at TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_entities_book_type
        ON reader_entities(book_id, entity_type, first_chapter_number)
        """
    )

    _add_column_if_missing(conn, "reader_entity_mentions", "book_id INTEGER")
    _add_column_if_missing(conn, "reader_entity_mentions", "entity_id INTEGER")
    _add_column_if_missing(conn, "reader_entity_mentions", "chapter_id INTEGER")
    _add_column_if_missing(conn, "reader_entity_mentions", "chapter_number INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_entity_mentions", "paragraph_index INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_entity_mentions", "mention_text TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_entity_mentions", "context TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_entity_mentions", "spoiler_level INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_entity_mentions", "created_at TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_entity_mentions_book_chapter
        ON reader_entity_mentions(book_id, chapter_number, entity_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_entity_mentions_entity
        ON reader_entity_mentions(entity_id, chapter_number)
        """
    )

    _add_column_if_missing(conn, "reader_timeline_events", "book_id INTEGER")
    _add_column_if_missing(conn, "reader_timeline_events", "chapter_id INTEGER")
    _add_column_if_missing(conn, "reader_timeline_events", "chapter_number INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_timeline_events", "event_order INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "reader_timeline_events", "title TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_timeline_events", "summary TEXT DEFAULT ''")
    _add_column_if_missing(conn, "reader_timeline_events", "spoiler_level INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "reader_timeline_events", "entities_json TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "reader_timeline_events", "created_at TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reader_timeline_events_book_chapter
        ON reader_timeline_events(book_id, chapter_number, event_order)
        """
    )

    if _table_exists(conn, "books"):
        _add_column_if_missing(conn, "books", "book_key TEXT DEFAULT ''")
        _add_column_if_missing(conn, "books", "owner_user_id TEXT DEFAULT ''")
        _add_column_if_missing(conn, "books", "cover_path TEXT DEFAULT ''")
        rows = conn.execute(
            "SELECT id, title FROM books WHERE book_key IS NULL OR book_key = ''"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE books SET book_key = ? WHERE id = ?",
                (normalize_book_key(row["title"] or ""), row["id"]),
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_book_key ON books(book_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_owner_user_id ON books(owner_user_id)")

    if _table_exists(conn, "chapters"):
        _add_column_if_missing(conn, "chapters", "adapter_id TEXT DEFAULT ''")
        _add_column_if_missing(conn, "chapters", "source_hash TEXT DEFAULT ''")
        _add_column_if_missing(conn, "chapters", "content_html_path TEXT")
        _add_column_if_missing(conn, "chapters", "deleted_at TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chapters_active_number_lookup
            ON chapters(book_id, chapter_number)
            WHERE deleted_at IS NULL
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chapters_active_source_hash
            ON chapters(book_id, source_hash)
            WHERE deleted_at IS NULL AND source_hash != ''
            """
        )

    if _table_exists(conn, "glossary_terms"):
        # Check if occurrence_count exists
        try:
            conn.execute("SELECT occurrence_count FROM glossary_terms LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE glossary_terms ADD COLUMN occurrence_count INTEGER DEFAULT 0")
        # Check if last_seen exists
        try:
            conn.execute("SELECT last_seen FROM glossary_terms LIMIT 1")
        except sqlite3.OperationalError:
            # SQLite ALTER TABLE rejects non-constant defaults
            conn.execute("ALTER TABLE glossary_terms ADD COLUMN last_seen TEXT DEFAULT ''")
            # Backfill existing rows with current timestamp
            now = __import__("datetime").datetime.now().isoformat()
            conn.execute("UPDATE glossary_terms SET last_seen = ?", (now,))
        # Check if priority exists
        try:
            conn.execute("SELECT priority FROM glossary_terms LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE glossary_terms ADD COLUMN priority INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "glossary_terms", "locked INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "glossary_terms", "genre TEXT DEFAULT ''")
        term_type_added = _add_column_if_missing(conn, "glossary_terms", "term_type TEXT DEFAULT 'term'")
        _add_column_if_missing(conn, "glossary_terms", "alternatives TEXT DEFAULT ''")
        _add_column_if_missing(conn, "glossary_terms", "gender TEXT DEFAULT ''")
        _add_column_if_missing(conn, "glossary_terms", "first_seen_chapter_id INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "glossary_terms", "first_seen_chapter_number INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "glossary_terms", "review_status TEXT DEFAULT ''")
        _add_column_if_missing(conn, "glossary_terms", "source_context TEXT DEFAULT ''")
        _add_column_if_missing(conn, "glossary_terms", "updated_at TEXT DEFAULT ''")
        if term_type_added:
            conn.execute(
                """
                UPDATE glossary_terms
                SET term_type = COALESCE(NULLIF(category, ''), 'term')
                WHERE term_type IS NULL OR term_type = '' OR term_type = 'term'
                """
            )
        conn.execute(
            """
            UPDATE glossary_terms
            SET review_status = CASE
                WHEN locked = 1 THEN 'LOCKED'
                WHEN approved < 0 THEN 'REJECTED'
                WHEN approved = 1 THEN 'APPROVED'
                ELSE 'NEEDS_REVIEW'
            END
            WHERE review_status IS NULL OR review_status = ''
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_terms_book_review ON glossary_terms(book_id, review_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_terms_book_type ON glossary_terms(book_id, term_type)")
        _rebuild_glossary_terms_table(conn)

    if _table_exists(conn, "translation_cache"):
        try:
            conn.execute("SELECT expiry_ts FROM translation_cache LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE translation_cache ADD COLUMN expiry_ts REAL NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE translation_cache SET expiry_ts = ? WHERE expiry_ts IS NULL OR expiry_ts <= 0",
            (time.time() + 7 * 86400,),
        )

    if _table_exists(conn, "tm_fuzzy"):
        _add_column_if_missing(conn, "tm_fuzzy", "source_lang TEXT DEFAULT 'zh'")
        _add_column_if_missing(conn, "tm_fuzzy", "target_lang TEXT DEFAULT 'vi'")
        _add_column_if_missing(conn, "tm_fuzzy", "book_id INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "tm_fuzzy", "chapter_number INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tm_fuzzy_book ON tm_fuzzy(book_id, chapter_number)")

    if _table_exists(conn, "qa_reports"):
        _add_column_if_missing(conn, "qa_reports", "book_id INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "quality_score REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "fidelity_score REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "style_score REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "glossary_score REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "audiobook_score REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "verdict TEXT DEFAULT 'UNKNOWN'")
        _add_column_if_missing(conn, "qa_reports", "job_id TEXT DEFAULT ''")
        _add_column_if_missing(conn, "qa_reports", "overall_status TEXT DEFAULT 'NOT_RUN'")
        _add_column_if_missing(conn, "qa_reports", "missing_paragraph_warning INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "chinese_leakage_count INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "name_consistency_status TEXT DEFAULT 'NOT_RUN'")
        _add_column_if_missing(conn, "qa_reports", "term_consistency_status TEXT DEFAULT 'NOT_RUN'")
        _add_column_if_missing(conn, "qa_reports", "length_ratio REAL DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "repetition_warning INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "qa_reports", "style_warnings TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "qa_reports", "glossary_violations TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "qa_reports", "suggested_fixes TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "qa_reports", "report_json TEXT")
        _add_column_if_missing(conn, "qa_reports", "created_at TEXT DEFAULT ''")
        _add_column_if_missing(conn, "qa_reports", "updated_at TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_reports_book_status ON qa_reports(book_id, overall_status)")
        if _table_exists(conn, "chapters"):
            conn.execute(
                """
                UPDATE qa_reports
                SET book_id = COALESCE((
                    SELECT chapters.book_id FROM chapters
                    WHERE chapters.id = qa_reports.chapter_id
                ), 0)
                WHERE book_id IS NULL OR book_id = 0
                """
            )

    _consolidate_duplicate_book_keys(conn)


def init_db(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        # WAL is persistent database configuration; migrations and backfills
        # belong to explicit startup/CLI initialization, not request opens.
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_schema_migrations(conn)
        _migrate_legacy_schema(conn)
        conn.executescript(SCHEMA)
        seed_default_model_providers(conn)
        seed_default_style_profiles(conn)
        operator_user = _seed_operator_user_from_env(conn)
        _backfill_owner_user_ids(conn, str(operator_user.get("id") or ""))
        _record_schema_migration(conn, CURRENT_SCHEMA_VERSION)
        conn.commit()


def get_or_seed_operator_user(db_path: Path, username: str | None = None) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        user = _seed_operator_user(conn, username)
        conn.commit()
        return user


def get_operator_user_id(db_path: Path, username: str | None = None) -> str:
    return str(get_or_seed_operator_user(db_path, username)["id"])


def find_user_by_username(db_path: Path, username: str) -> dict[str, Any] | None:
    resolved_username = username.strip()
    if not resolved_username:
        return None
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (resolved_username,),
        ).fetchone()
    return dict(row) if row else None


def _resolve_owner_user_id_for_write(db_path: Path, owner_user_id: str = "") -> str:
    resolved = str(owner_user_id or "").strip()
    if resolved:
        return resolved
    return get_operator_user_id(db_path)


# ── Model Providers ────────────────────────────────────────────────────────

DEFAULT_MODEL_PROVIDERS = [
    {
        "id": "gemini",
        "label": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash-lite",
        "api_key_env": "GEMINI_API_KEY",
        "temperature": 0.3,
        "timeout_seconds": 180,
        "supports_streaming": 1,
        "supports_batch": 0,
        "cost_input_per_1m": 0.10,
        "cost_output_per_1m": 0.40,
        "enabled": 1,
        "notes": "Default translation and polish provider.",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "temperature": 0.3,
        "timeout_seconds": 180,
        "supports_streaming": 1,
        "supports_batch": 0,
        "cost_input_per_1m": 0.14,
        "cost_output_per_1m": 0.28,
        "enabled": 1,
        "notes": "Default QA provider.",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/free",
        "api_key_env": "OPENROUTER_API_KEY",
        "temperature": 0.3,
        "timeout_seconds": 180,
        "supports_streaming": 1,
        "supports_batch": 0,
        "cost_input_per_1m": 0,
        "cost_output_per_1m": 0,
        "enabled": 1,
        "notes": "Free router, model may vary.",
    },
    {
        "id": "ollama",
        "label": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:14b",
        "api_key_env": "",
        "temperature": 0.3,
        "timeout_seconds": 180,
        "supports_streaming": 1,
        "supports_batch": 0,
        "cost_input_per_1m": 0,
        "cost_output_per_1m": 0,
        "enabled": 1,
        "notes": "Local free provider.",
    },
]

DEFAULT_PROVIDER_DEFAULTS = {
    "translate": "gemini",
    "qa": "deepseek",
    "polish": "gemini",
    "retranslate": "gemini",
}


DEFAULT_STYLE_PROFILES = [
    {
        "id": "tien_hiep",
        "label": "Tiên hiệp",
        "pronoun_rules": (
            "Ưu tiên ta/ngươi/hắn/y, đạo hữu, tiền bối, vãn bối, sư huynh, sư tỷ, "
            "sư đệ, sư muội. Khi đã gọi Lục ca/sư huynh/đạo hữu thì không dùng tôi/bạn."
        ),
        "han_viet_level": "high",
        "preferred_terms": (
            "tu luyện, tu vi, cảnh giới, linh căn, linh khí, linh lực, đan điền, "
            "tông môn, đạo tâm, tâm ma, pháp bảo, linh thạch, Trúc Cơ, Kim Đan, Nguyên Anh"
        ),
        "banned_modern_terms": "level up, buff, team, ok, drama, crush, bạn, tôi, anh ấy",
        "prompt_rules": (
            "Văn phong cổ trang, bình ổn, rõ nghĩa. Giữ thuật ngữ tu luyện Hán-Việt, "
            "không hiện đại hóa xưng hô hoặc môn phái. Thành ngữ, tục ngữ, thơ và điển cố "
            "phải dịch theo văn Việt cổ phong, ưu tiên tự nhiên hơn bám chữ."
        ),
        "is_default": 1,
    },
    {
        "id": "huyen_huyen",
        "label": "Huyền huyễn",
        "pronoun_rules": (
            "Ưu tiên hắn, nàng, y, bổn tọa, bản tôn, các hạ, tiền bối. "
            "Xưng hô phải thể hiện huyết mạch, gia tộc, cấp bậc và uy áp."
        ),
        "han_viet_level": "high",
        "preferred_terms": (
            "huyết mạch, thần thông, pháp tắc, đại lục, cổ tộc, yêu thú, chiến kỹ, "
            "bí cảnh, truyền thừa, thần hồn, khí tức, uy áp"
        ),
        "banned_modern_terms": "level up, buff, team, server, boss, damage, farm, tôi, bạn",
        "prompt_rules": (
            "Giữ khí thế rộng lớn và uy áp. Có thể dùng Hán-Việt mạnh hơn tiên hiệp "
            "khi nói về huyết mạch, pháp tắc, thần thông, cổ tộc. Thành ngữ, tục ngữ, "
            "thơ và điển cố phải giữ khí văn, không diễn thành văn hiện đại."
        ),
        "is_default": 0,
    },
    {
        "id": "kiem_hiep",
        "label": "Kiếm hiệp",
        "pronoun_rules": (
            "Ưu tiên tại hạ, các hạ, huynh đài, cô nương, đại hiệp, tiền bối, "
            "lão phu, tiểu tử. Tránh tôi/bạn trong giang hồ."
        ),
        "han_viet_level": "balanced",
        "preferred_terms": (
            "giang hồ, môn phái, bang phái, chưởng môn, kiếm khí, nội lực, khinh công, "
            "chiêu thức, tiêu cục, khách điếm, tửu lâu, nha môn"
        ),
        "banned_modern_terms": "team, ok, drama, crush, nhiệm vụ online, tôi, bạn",
        "prompt_rules": (
            "Văn phong giang hồ rõ ràng, gọn, có khí chất võ hiệp. Không biến khách điếm "
            "thành khách sạn hoặc tửu lâu thành nhà hàng. Câu thơ, đối liên, tục ngữ "
            "phải giữ chất giang hồ cổ phong và nhịp đọc tự nhiên."
        ),
        "is_default": 0,
    },
    {
        "id": "he_thong",
        "label": "Hệ thống",
        "pronoun_rules": (
            "Narration vẫn dùng cổ trang nếu bối cảnh cổ trang. Thông báo hệ thống có thể "
            "trung tính, ngắn gọn, nhưng không dùng slang hiện đại."
        ),
        "han_viet_level": "balanced",
        "preferred_terms": (
            "Thông báo hệ thống, nhiệm vụ, phần thưởng, thuộc tính, kỹ năng, điểm kinh nghiệm, "
            "cửa hàng, giao diện, bảng trạng thái"
        ),
        "banned_modern_terms": "level up, buff, nerf, team, farm, build đồ, meta, ok, drama",
        "prompt_rules": (
            "Giữ format thông báo hệ thống nếu source có. Việt hóa thuật ngữ game-like, "
            "không để tiếng Anh trừ khi source cố ý dùng tiếng Anh. Nếu bối cảnh cổ trang "
            "có thơ/thành ngữ, giữ văn phong cổ thay vì giọng giao diện hiện đại."
        ),
        "is_default": 0,
    },
]


def seed_default_model_providers(conn: sqlite3.Connection) -> None:
    core_missing_sql = """
        label IS NULL OR label = ''
        OR base_url IS NULL OR base_url = ''
        OR model IS NULL OR model = ''
    """
    for provider in DEFAULT_MODEL_PROVIDERS:
        conn.execute(
            """
            INSERT OR IGNORE INTO model_providers
            (id, label, base_url, model, api_key_env, temperature, timeout_seconds,
             supports_streaming, supports_batch, cost_input_per_1m, cost_output_per_1m,
             enabled, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider["id"],
                provider["label"],
                provider["base_url"],
                provider["model"],
                provider["api_key_env"],
                provider["temperature"],
                provider["timeout_seconds"],
                provider["supports_streaming"],
                provider["supports_batch"],
                provider["cost_input_per_1m"],
                provider["cost_output_per_1m"],
                provider["enabled"],
                provider["notes"],
            ),
        )
        conn.execute(
            f"""
            UPDATE model_providers SET
                label = CASE
                    WHEN label IS NULL OR label = '' THEN ?
                    ELSE label
                END,
                base_url = CASE
                    WHEN base_url IS NULL OR base_url = '' THEN ?
                    ELSE base_url
                END,
                model = CASE
                    WHEN model IS NULL OR model = '' THEN ?
                    ELSE model
                END,
                api_key_env = CASE
                    WHEN api_key_env IS NULL OR (api_key_env = '' AND ({core_missing_sql})) THEN ?
                    ELSE api_key_env
                END,
                temperature = CASE
                    WHEN temperature IS NULL THEN ?
                    ELSE temperature
                END,
                timeout_seconds = CASE
                    WHEN timeout_seconds IS NULL THEN ?
                    ELSE timeout_seconds
                END,
                supports_streaming = CASE
                    WHEN supports_streaming IS NULL THEN ?
                    ELSE supports_streaming
                END,
                supports_batch = CASE
                    WHEN supports_batch IS NULL THEN ?
                    ELSE supports_batch
                END,
                cost_input_per_1m = CASE
                    WHEN cost_input_per_1m IS NULL THEN ?
                    ELSE cost_input_per_1m
                END,
                cost_output_per_1m = CASE
                    WHEN cost_output_per_1m IS NULL THEN ?
                    ELSE cost_output_per_1m
                END,
                enabled = CASE
                    WHEN enabled IS NULL THEN ?
                    ELSE enabled
                END,
                notes = CASE
                    WHEN notes IS NULL OR (notes = '' AND ({core_missing_sql})) THEN ?
                    ELSE notes
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
                AND (
                    {core_missing_sql}
                    OR api_key_env IS NULL
                    OR temperature IS NULL
                    OR timeout_seconds IS NULL
                    OR supports_streaming IS NULL
                    OR supports_batch IS NULL
                    OR cost_input_per_1m IS NULL
                    OR cost_output_per_1m IS NULL
                    OR enabled IS NULL
                    OR notes IS NULL
                )
            """,
            (
                provider["label"],
                provider["base_url"],
                provider["model"],
                provider["api_key_env"],
                provider["temperature"],
                provider["timeout_seconds"],
                provider["supports_streaming"],
                provider["supports_batch"],
                provider["cost_input_per_1m"],
                provider["cost_output_per_1m"],
                provider["enabled"],
                provider["notes"],
                provider["id"],
            ),
        )

    for task_type, provider_id in DEFAULT_PROVIDER_DEFAULTS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO provider_defaults (task_type, provider_id)
            VALUES (?, ?)
            """,
            (task_type, provider_id),
        )
        conn.execute(
            """
            UPDATE provider_defaults
            SET provider_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_type = ? AND (provider_id IS NULL OR provider_id = '')
            """,
            (provider_id, task_type),
        )


def put_model_provider(
    db_path: Path,
    *,
    provider_id: str,
    label: str,
    base_url: str,
    model: str,
    api_key_env: str = "",
    cost_input_per_1m: float = 0,
    cost_output_per_1m: float = 0,
    enabled: int = 1,
    temperature: float = 0.3,
    timeout_seconds: int = 180,
    notes: str = "",
) -> str:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO model_providers
            (id, label, base_url, model, api_key_env, temperature, timeout_seconds,
             cost_input_per_1m, cost_output_per_1m, enabled, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                base_url = excluded.base_url,
                model = excluded.model,
                api_key_env = excluded.api_key_env,
                temperature = excluded.temperature,
                timeout_seconds = excluded.timeout_seconds,
                cost_input_per_1m = excluded.cost_input_per_1m,
                cost_output_per_1m = excluded.cost_output_per_1m,
                enabled = excluded.enabled,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                provider_id,
                label,
                base_url,
                model,
                api_key_env,
                temperature,
                timeout_seconds,
                cost_input_per_1m,
                cost_output_per_1m,
                enabled,
                notes,
            ),
        )
        conn.commit()
        return provider_id


def list_model_providers(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        seed_default_model_providers(conn)
        rows = conn.execute("SELECT * FROM model_providers ORDER BY label ASC").fetchall()
        providers = []
        for row in rows:
            provider = dict(row)
            api_key_env = provider.get("api_key_env") or ""
            provider["api_key_set"] = bool(api_key_env and os.environ.get(api_key_env, "").strip())
            providers.append(provider)
        return providers


def get_provider_defaults(db_path: Path) -> dict[str, str]:
    with get_connection(db_path) as conn:
        seed_default_model_providers(conn)
        rows = conn.execute("SELECT task_type, provider_id FROM provider_defaults").fetchall()
        return {row["task_type"]: row["provider_id"] for row in rows}


# ── Style Profiles ──────────────────────────────────────────────────────────

def seed_default_style_profiles(conn: sqlite3.Connection) -> None:
    for profile in DEFAULT_STYLE_PROFILES:
        conn.execute(
            """
            INSERT OR IGNORE INTO style_profiles
            (id, label, pronoun_rules, han_viet_level, preferred_terms,
             banned_modern_terms, prompt_rules, is_default)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile["id"],
                profile["label"],
                profile["pronoun_rules"],
                profile["han_viet_level"],
                profile["preferred_terms"],
                profile["banned_modern_terms"],
                profile["prompt_rules"],
                profile["is_default"],
            ),
        )
        conn.execute(
            """
            UPDATE style_profiles
            SET label = CASE WHEN label IS NULL OR label = '' THEN ? ELSE label END,
                pronoun_rules = CASE WHEN pronoun_rules IS NULL OR pronoun_rules = '' THEN ? ELSE pronoun_rules END,
                han_viet_level = CASE WHEN han_viet_level IS NULL OR han_viet_level = '' THEN ? ELSE han_viet_level END,
                preferred_terms = CASE WHEN preferred_terms IS NULL OR preferred_terms = '' THEN ? ELSE preferred_terms END,
                banned_modern_terms = CASE WHEN banned_modern_terms IS NULL OR banned_modern_terms = '' THEN ? ELSE banned_modern_terms END,
                prompt_rules = CASE WHEN prompt_rules IS NULL OR prompt_rules = '' THEN ? ELSE prompt_rules END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                profile["label"],
                profile["pronoun_rules"],
                profile["han_viet_level"],
                profile["preferred_terms"],
                profile["banned_modern_terms"],
                profile["prompt_rules"],
                profile["id"],
            ),
        )

    default_count = conn.execute(
        "SELECT COUNT(*) FROM style_profiles WHERE is_default = 1"
    ).fetchone()[0]
    if default_count != 1:
        conn.execute("UPDATE style_profiles SET is_default = 0")
        conn.execute("UPDATE style_profiles SET is_default = 1 WHERE id = ?", ("tien_hiep",))


def _style_profile_order_sql() -> str:
    return """
        CASE id
            WHEN 'tien_hiep' THEN 1
            WHEN 'huyen_huyen' THEN 2
            WHEN 'kiem_hiep' THEN 3
            WHEN 'he_thong' THEN 4
            ELSE 99
        END
    """


def list_style_profiles(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM style_profiles ORDER BY {_style_profile_order_sql()}, label ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_style_profile(db_path: Path, profile_id: str) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM style_profiles WHERE id = ?", (profile_id,)).fetchone()
        return dict(row) if row else None


def get_default_style_profile(db_path: Path) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM style_profiles WHERE is_default = 1 LIMIT 1").fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            f"SELECT * FROM style_profiles ORDER BY {_style_profile_order_sql()}, label ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def set_default_style_profile(db_path: Path, profile_id: str) -> bool:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT 1 FROM style_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE style_profiles SET is_default = 0")
        conn.execute(
            "UPDATE style_profiles SET is_default = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (profile_id,),
        )
        conn.commit()
        return True


def record_provider_usage(
    db_path: Path,
    *,
    provider_id: str,
    model: str,
    task_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: float,
    job_id: str = "",
    chapter_id: int | None = None,
    owner_user_id: str = "",
) -> int:
    total_tokens = prompt_tokens + completion_tokens
    resolved_owner_user_id = _resolve_owner_user_id_for_write(db_path, owner_user_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO provider_usage
            (provider_id, owner_user_id, model, task_type, prompt_tokens, completion_tokens,
             total_tokens, estimated_cost_usd, job_id, chapter_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider_id,
                resolved_owner_user_id,
                model,
                task_type,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                estimated_cost_usd,
                job_id,
                chapter_id,
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_usage_summary(db_path: Path) -> dict:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_estimated_cost_usd
            FROM provider_usage
            """
        ).fetchone()
        return dict(row)


def record_job_attempt(
    db_path: Path,
    job_id: str,
    chapter_id: int | None,
    provider_id: str,
    model: str,
    status: str,
    stage: str = "",
    error: str = "",
    elapsed_ms: int = 0,
    owner_user_id: str = "",
) -> int:
    resolved_owner_user_id = _resolve_owner_user_id_for_write(db_path, owner_user_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_attempts
            (job_id, chapter_id, owner_user_id, stage, provider_id, model, status, error, elapsed_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, chapter_id, resolved_owner_user_id, stage, provider_id, model, status, error, elapsed_ms),
        )
        conn.commit()
        return cur.lastrowid


def get_job_attempts(
    db_path: Path,
    job_id: str | None = None,
    chapter_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    clauses = []
    params: list[object] = []
    if job_id is not None:
        clauses.append("job_id = ?")
        params.append(job_id)
    if chapter_id is not None:
        clauses.append("chapter_id = ?")
        params.append(chapter_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(0, limit))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM job_attempts
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


# ── Mobile Jobs ──────────────────────────────────────────────────────────────

_JOB_LOG_SENSITIVE_MARKERS = (
    "\n",
    "traceback",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "bearer ",
    "token",
    "/tmp/",
    "/home/",
    "\\users\\",
    "sk-",
)
MAX_JOB_LOG_MESSAGE_LENGTH = 500
MAX_JOB_LOG_DETAIL_VALUE_LENGTH = 500
MAX_JOB_LOG_LIMIT = 100


def _job_value_has_sensitive_marker(value: object) -> bool:
    return any(marker in str(value).lower() for marker in _JOB_LOG_SENSITIVE_MARKERS)


def _sanitize_job_log_message(message: str) -> str:
    if _job_value_has_sensitive_marker(message):
        return "Job event recorded. Check server logs."
    return str(message).replace("\n", " ").strip()[:MAX_JOB_LOG_MESSAGE_LENGTH]


def _sanitize_job_log_detail_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\n", " ").strip()[:MAX_JOB_LOG_DETAIL_VALUE_LENGTH]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered[:MAX_JOB_LOG_DETAIL_VALUE_LENGTH]


def _sanitize_job_log_details(details: dict[str, Any] | None) -> dict[str, Any]:
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        key_text = str(key)
        lowered_key = key_text.lower()
        if any(marker in lowered_key for marker in ("secret", "key", "token", "password", "authorization")):
            safe_details[key_text] = "[redacted]"
        elif _job_value_has_sensitive_marker(value):
            safe_details[key_text] = "[redacted]"
        else:
            safe_details[key_text] = _sanitize_job_log_detail_value(value)
    return safe_details


def sanitize_job_error(message: str) -> str:
    if not message:
        return ""
    if _job_value_has_sensitive_marker(message):
        return "Job failed. Check server logs."
    return str(message).replace("\n", " ").strip()[:500]


def _decode_json_field(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _mobile_job_from_row(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["target_ids"] = _decode_json_field(job.pop("target_ids_json", None), [])
    job["params"] = _decode_json_field(job.pop("params_json", None), {})
    job["state"] = normalize_job_state(
        str(job.get("status") or ""),
        current_step=str(job.get("current_step") or ""),
        existing_state=str(job.get("state") or ""),
    )
    job["cancel_requested"] = bool(int(job.get("cancel_requested") or 0))
    return job


def save_mobile_job(db_path: Path, job: dict) -> None:
    target_ids_json = json.dumps(job.get("target_ids", []), ensure_ascii=False)
    params_json = json.dumps(job.get("params", {}), ensure_ascii=False)
    status = str(job.get("status") or "queued")
    current_step = str(job.get("current_step") or "")
    state = normalize_job_state(status, current_step=current_step, existing_state=str(job.get("state") or ""))
    retry_count = int(job.get("retry_count") or (job.get("params") or {}).get("retry_count") or 0)
    with get_connection(db_path) as conn:
        owner_user_id = str(job.get("owner_user_id") or "").strip()
        if not owner_user_id:
            row = conn.execute(
                "SELECT owner_user_id FROM mobile_jobs WHERE job_id = ?",
                (job["job_id"],),
            ).fetchone()
            owner_user_id = str(row["owner_user_id"] or "") if row else ""
        if not owner_user_id:
            owner_user_id = str(_seed_operator_user_from_env(conn).get("id") or "")
        conn.execute(
            """
            INSERT INTO mobile_jobs
            (
                job_id, job_type, owner_user_id, status, state, progress, total,
                current_book_id, current_chapter_id, current_chunk_index, total_chunks,
                current_step, provider, model, retry_count, target_ids_json, params_json,
                message, error, created_at, updated_at, started_at, completed_at, failed_at,
                finished_at, cancel_requested, last_safe_error, internal_error_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_type = excluded.job_type,
                owner_user_id = excluded.owner_user_id,
                status = excluded.status,
                state = excluded.state,
                progress = excluded.progress,
                total = excluded.total,
                current_book_id = excluded.current_book_id,
                current_chapter_id = excluded.current_chapter_id,
                current_chunk_index = excluded.current_chunk_index,
                total_chunks = excluded.total_chunks,
                current_step = excluded.current_step,
                provider = excluded.provider,
                model = excluded.model,
                retry_count = excluded.retry_count,
                target_ids_json = excluded.target_ids_json,
                params_json = excluded.params_json,
                message = excluded.message,
                error = excluded.error,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                failed_at = excluded.failed_at,
                finished_at = excluded.finished_at,
                cancel_requested = excluded.cancel_requested,
                last_safe_error = excluded.last_safe_error,
                internal_error_ref = excluded.internal_error_ref
            """,
            (
                job["job_id"],
                job["job_type"],
                owner_user_id,
                status,
                state,
                int(job.get("progress", 0)),
                int(job.get("total", 0)),
                int(job.get("current_book_id") or 0),
                int(job.get("current_chapter_id") or 0),
                int(job.get("current_chunk_index") or 0),
                int(job.get("total_chunks") or 0),
                current_step,
                str(job.get("provider") or ""),
                str(job.get("model") or ""),
                retry_count,
                target_ids_json,
                params_json,
                job.get("message", ""),
                job.get("error", ""),
                job.get("created_at", ""),
                job.get("updated_at", ""),
                job.get("started_at", ""),
                job.get("completed_at", ""),
                job.get("failed_at", ""),
                job.get("finished_at"),
                1 if job.get("cancel_requested") else 0,
                str(job.get("last_safe_error") or ""),
                str(job.get("internal_error_ref") or ""),
            ),
        )
        conn.commit()


def get_mobile_job(db_path: Path, job_id: str) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM mobile_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _mobile_job_from_row(row) if row else None


def list_mobile_jobs(db_path: Path, limit: int = 50) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM mobile_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, limit),),
        ).fetchall()
        return [_mobile_job_from_row(row) for row in rows]


def claim_mobile_job(
    db_path: Path,
    *,
    job_id: str,
    worker_id: str,
    lease_token: str,
    lease_seconds: int = 120,
) -> bool:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'running',
                state = 'CLAIMED',
                current_step = 'CLAIMED',
                lease_token = ?,
                lease_owner = ?,
                lease_expires_at = ?,
                heartbeat_at = ?,
                updated_at = ?,
                started_at = CASE WHEN COALESCE(started_at, '') = '' THEN ? ELSE started_at END
            WHERE job_id = ?
              AND status IN ('queued', 'retrying', 'pending')
              AND COALESCE(lease_token, '') = ''
            """,
            (lease_token, worker_id, expires_at, now_text, now_text, now_text, job_id),
        )
        conn.commit()
        return cur.rowcount == 1


def heartbeat_mobile_job_lease(
    db_path: Path,
    *,
    job_id: str,
    lease_token: str,
    lease_seconds: int = 120,
) -> bool:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = ?
              AND lease_token = ?
              AND status = 'running'
            """,
            (now_text, expires_at, now_text, job_id, lease_token),
        )
        conn.commit()
        return cur.rowcount == 1


def release_mobile_job_lease(db_path: Path, *, job_id: str, lease_token: str) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET lease_token = '',
                lease_owner = '',
                lease_expires_at = '',
                heartbeat_at = ''
            WHERE job_id = ?
              AND lease_token = ?
            """,
            (job_id, lease_token),
        )
        conn.commit()
        return cur.rowcount == 1


def mark_interrupted_mobile_jobs(
    db_path: Path,
    *,
    stale_after_seconds: int = 300,
    include_queued: bool = True,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=max(1, stale_after_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'interrupted',
                state = 'STALE_INTERRUPTED',
                message = 'Job interrupted before completion. Please retry the job.',
                error = 'Job interrupted before completion',
                last_safe_error = 'Job interrupted before completion',
                updated_at = ?,
                finished_at = ?,
                lease_token = '',
                lease_owner = '',
                lease_expires_at = '',
                heartbeat_at = ''
            WHERE (
                    ? = 1
                    AND status IN ('pending', 'queued', 'retrying')
                    AND COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), '') <= ?
               )
               OR (
                    status = 'running'
                    AND (
                        (
                            COALESCE(lease_token, '') = ''
                            AND COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), '') <= ?
                        )
                        OR (
                            COALESCE(lease_token, '') != ''
                            AND (
                                COALESCE(lease_expires_at, '') = ''
                                OR lease_expires_at <= ?
                                OR COALESCE(heartbeat_at, '') = ''
                                OR heartbeat_at <= ?
                            )
                        )
                    )
               )
            """,
            (now, now, 1 if include_queued else 0, stale_before, stale_before, now, stale_before),
        )
        conn.commit()
        return cur.rowcount


def count_mobile_jobs_by_status(db_path: Path) -> dict[str, int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM mobile_jobs
            GROUP BY status
            """
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}


def request_cancel_mobile_job(db_path: Path, *, job_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT status FROM mobile_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return False
        status = str(row["status"] or "").lower()
        if status in {"completed", "failed", "cancelled", "canceled", "interrupted"}:
            return True
        if status in {"pending", "queued", "retrying"}:
            cur = conn.execute(
                """
                UPDATE mobile_jobs
                SET cancel_requested = 1,
                    status = 'cancelled',
                    state = 'CANCELED',
                    message = 'Job cancelled before claim',
                    updated_at = ?,
                    finished_at = ?
                WHERE job_id = ?
                """,
                (now, now, job_id),
            )
        else:
            cur = conn.execute(
                """
                UPDATE mobile_jobs
                SET cancel_requested = 1,
                    message = 'Cancel requested',
                    updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )
        conn.commit()
        return cur.rowcount > 0


def record_job_log(
    db_path: Path,
    *,
    job_id: str,
    event_type: str,
    state: str = "",
    step: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> int:
    safe_message = _sanitize_job_log_message(message)
    safe_details = _sanitize_job_log_details(details)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_logs
            (job_id, event_type, state, step, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event_type,
                state,
                step,
                safe_message,
                json.dumps(safe_details, ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_job_logs(db_path: Path, job_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    safe_limit = min(MAX_JOB_LOG_LIMIT, max(0, int(limit)))
    safe_offset = max(0, int(offset))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM job_logs
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            OFFSET ?
            """,
            (job_id, safe_limit, safe_offset),
        ).fetchall()
    logs: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["details"] = _decode_json_field(item.pop("details_json", None), {})
        logs.append(item)
    return logs


# ── Source Catalog ─────────────────────────────────────────────────────────────

def upsert_source_catalog_entries(db_path: Path, entries: list[dict[str, Any]]) -> dict[str, int]:
    now = _utcnow_text()
    inserted = 0
    updated = 0
    skipped = 0
    with get_connection(db_path) as conn:
        for entry in entries:
            entry_id = str(entry.get("id") or "").strip()
            external_id = str(entry.get("external_id") or "").strip()
            if not entry_id or not external_id:
                skipped += 1
                continue
            catalog_source = str(entry.get("catalog_source") or "yckceo").strip() or "yckceo"
            existing = conn.execute(
                "SELECT id, created_at FROM source_catalog_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            created_at = str(entry.get("created_at") or (existing["created_at"] if existing else now) or now)
            updated_at = str(entry.get("updated_at") or now)
            conn.execute(
                """
                INSERT INTO source_catalog_entries (
                    id, external_id, catalog_source, name, url, domain, author,
                    downloads, version, raw_tags, tags_json, unknown_tags_json,
                    supported_status, supported_source_id, invalid_reason,
                    updated_label, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    external_id = excluded.external_id,
                    catalog_source = excluded.catalog_source,
                    name = excluded.name,
                    url = excluded.url,
                    domain = excluded.domain,
                    author = excluded.author,
                    downloads = excluded.downloads,
                    version = excluded.version,
                    raw_tags = excluded.raw_tags,
                    tags_json = excluded.tags_json,
                    unknown_tags_json = excluded.unknown_tags_json,
                    supported_status = excluded.supported_status,
                    supported_source_id = excluded.supported_source_id,
                    invalid_reason = excluded.invalid_reason,
                    updated_label = excluded.updated_label,
                    updated_at = excluded.updated_at
                """,
                (
                    entry_id,
                    external_id,
                    catalog_source,
                    str(entry.get("name") or ""),
                    str(entry.get("url") or ""),
                    str(entry.get("domain") or ""),
                    str(entry.get("author") or ""),
                    int(entry.get("downloads") or 0),
                    str(entry.get("version") or ""),
                    str(entry.get("raw_tags") or ""),
                    str(entry.get("tags_json") or "[]"),
                    str(entry.get("unknown_tags_json") or "[]"),
                    str(entry.get("supported_status") or "unsupported"),
                    str(entry.get("supported_source_id") or ""),
                    str(entry.get("invalid_reason") or ""),
                    str(entry.get("updated_label") or ""),
                    created_at,
                    updated_at,
                ),
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1
        conn.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _source_catalog_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["tags"] = _decode_json_field(item.pop("tags_json", None), [])
    item["unknown_tags"] = _decode_json_field(item.pop("unknown_tags_json", None), [])
    item["supported"] = item.get("supported_status") == "supported"
    item["managed_source_id"] = item.get("managed_source_id") or ""
    item["managed_status"] = item.get("managed_status") or ""
    item["managed_trust_level"] = item.get("managed_trust_level") or ""
    item["managed_last_test_status"] = item.get("managed_last_test_status") or ""
    item["managed_last_tested_at"] = item.get("managed_last_tested_at") or ""
    item["managed_last_successful_fetch_at"] = item.get("managed_last_successful_fetch_at") or ""
    item["managed_last_error"] = item.get("managed_last_error") or ""
    item["managed_rate_limit_requests_per_minute"] = int(item.get("managed_rate_limit_requests_per_minute") or 0)
    item["managed_rate_limit_delay_ms"] = int(item.get("managed_rate_limit_delay_ms") or 0)
    item["managed_max_concurrent_requests"] = int(item.get("managed_max_concurrent_requests") or 0)
    item["managed_cooldown_after_error_seconds"] = int(item.get("managed_cooldown_after_error_seconds") or 0)
    item["managed_notes"] = item.get("managed_notes") or ""
    item["managed_parser_type"] = item.get("managed_parser_type") or ""
    item["managed_language"] = item.get("managed_language") or ""
    item["can_use_in_jobs"] = item.get("managed_status") == "VERIFIED"
    return item


def get_source_catalog_entry(db_path: Path, entry_id: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                c.*,
                m.id AS managed_source_id,
                m.status AS managed_status,
                m.trust_level AS managed_trust_level,
                m.last_test_status AS managed_last_test_status,
                m.last_tested_at AS managed_last_tested_at,
                m.last_successful_fetch_at AS managed_last_successful_fetch_at,
                m.last_error AS managed_last_error,
                m.rate_limit_requests_per_minute AS managed_rate_limit_requests_per_minute,
                m.rate_limit_delay_ms AS managed_rate_limit_delay_ms,
                m.max_concurrent_requests AS managed_max_concurrent_requests,
                m.cooldown_after_error_seconds AS managed_cooldown_after_error_seconds,
                m.notes AS managed_notes,
                m.parser_type AS managed_parser_type,
                m.language AS managed_language
            FROM source_catalog_entries c
            LEFT JOIN managed_sources m ON m.catalog_entry_id = c.id
            WHERE c.id = ?
            """,
            (str(entry_id or "").strip(),),
        ).fetchone()
    return _source_catalog_row_to_dict(row) if row else None


def list_source_catalog_entries(
    db_path: Path,
    *,
    query: str = "",
    tag: str = "",
    domain: str = "",
    supported: bool | None = None,
    managed_status: str = "",
    managed_trust_level: str = "",
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    safe_page = max(1, int(page or 1))
    safe_per_page = min(200, max(1, int(per_page or 50)))
    where: list[str] = []
    params: list[Any] = []

    search = query.strip().casefold()
    if search:
        like = f"%{search}%"
        where.append(
            "("
            "lower(c.name) LIKE ? OR lower(c.url) LIKE ? OR lower(c.domain) LIKE ? OR "
            "lower(c.author) LIKE ? OR lower(c.external_id) LIKE ? OR lower(c.raw_tags) LIKE ?"
            ")"
        )
        params.extend([like, like, like, like, like, like])

    safe_tag = tag.strip().casefold()
    if safe_tag:
        where.append("c.tags_json LIKE ?")
        params.append(f'%"{safe_tag}"%')

    safe_domain = domain.strip().casefold().lstrip(".")
    if safe_domain:
        where.append("c.domain = ?")
        params.append(safe_domain)

    if supported is True:
        where.append("c.supported_status = 'supported'")
    elif supported is False:
        where.append("c.supported_status != 'supported'")

    normalized_managed_status = managed_status.strip().upper()
    if normalized_managed_status:
        if normalized_managed_status == "UNMANAGED":
            where.append("(m.id IS NULL OR m.id = '')")
        else:
            where.append("m.status = ?")
            params.append(normalized_managed_status)

    normalized_managed_trust = managed_trust_level.strip().upper()
    if normalized_managed_trust:
        where.append("m.trust_level = ?")
        params.append(normalized_managed_trust)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    offset = (safe_page - 1) * safe_per_page
    with get_connection(db_path) as conn:
        total = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM source_catalog_entries c
                LEFT JOIN managed_sources m ON m.catalog_entry_id = c.id
                {where_sql}
                """,
                params,
            ).fetchone()[0]
        )
        rows = conn.execute(
            f"""
            SELECT
                c.*,
                m.id AS managed_source_id,
                m.status AS managed_status,
                m.trust_level AS managed_trust_level,
                m.last_test_status AS managed_last_test_status,
                m.last_tested_at AS managed_last_tested_at,
                m.last_successful_fetch_at AS managed_last_successful_fetch_at,
                m.last_error AS managed_last_error,
                m.rate_limit_requests_per_minute AS managed_rate_limit_requests_per_minute,
                m.rate_limit_delay_ms AS managed_rate_limit_delay_ms,
                m.max_concurrent_requests AS managed_max_concurrent_requests,
                m.cooldown_after_error_seconds AS managed_cooldown_after_error_seconds,
                m.notes AS managed_notes,
                m.parser_type AS managed_parser_type,
                m.language AS managed_language
            FROM source_catalog_entries c
            LEFT JOIN managed_sources m ON m.catalog_entry_id = c.id
            {where_sql}
            ORDER BY
                CASE
                    WHEN m.status = 'VERIFIED' THEN 0
                    WHEN m.status = 'NEEDS_REVIEW' THEN 1
                    WHEN m.status = 'IMPORTED' THEN 2
                    WHEN m.status = 'BROKEN' THEN 3
                    WHEN m.status = 'BLOCKED' THEN 4
                    WHEN c.supported_status = 'supported' THEN 5
                    WHEN c.supported_status = 'unsupported' THEN 6
                    ELSE 7
                END,
                c.downloads DESC,
                c.name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_per_page, offset],
        ).fetchall()
    return {
        "items": [_source_catalog_row_to_dict(row) for row in rows],
        "total": total,
        "page": safe_page,
        "per_page": safe_per_page,
    }


def record_source_catalog_health_check(db_path: Path, result: dict[str, Any]) -> int:
    catalog_entry_id = str(result.get("catalog_entry_id") or "").strip()
    status = str(result.get("status") or "").strip()
    reason = str(result.get("reason") or "").strip()
    final_url = str(result.get("final_url") or "").strip()
    checked_at = str(result.get("checked_at") or _utcnow_text())
    http_status = result.get("http_status")
    safe_http_status = int(http_status) if http_status is not None else None
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO source_catalog_health_checks
                (catalog_entry_id, status, reason, http_status, final_url, checked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (catalog_entry_id, status, reason, safe_http_status, final_url, checked_at),
        )
        conn.execute(
            """
            UPDATE source_catalog_entries
            SET
                last_check_status = ?,
                last_check_at = ?,
                last_check_error = ?,
                last_check_http_status = ?,
                last_check_final_url = ?
            WHERE id = ?
            """,
            (
                status,
                checked_at,
                "" if status in {"reachable", "preview_ok"} else reason,
                safe_http_status,
                final_url,
                catalog_entry_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


# ── Managed Sources ──────────────────────────────────────────────────────────

def _managed_source_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["parser_config"] = _decode_json_field(item.pop("parser_config_json", None), {})
    item["can_use_in_jobs"] = item.get("status") == "VERIFIED"
    return item


def get_managed_source(db_path: Path, source_id: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM managed_sources WHERE id = ?",
            (str(source_id or "").strip(),),
        ).fetchone()
    return _managed_source_row_to_dict(row) if row else None


def get_managed_source_for_catalog_entry(db_path: Path, catalog_entry_id: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM managed_sources WHERE catalog_entry_id = ?",
            (str(catalog_entry_id or "").strip(),),
        ).fetchone()
    return _managed_source_row_to_dict(row) if row else None


def find_managed_source_for_url(db_path: Path, base_url: str, domain: str, supported_source_id: str = "") -> dict[str, Any] | None:
    normalized_url = str(base_url or "").strip()
    normalized_domain = str(domain or "").strip().casefold()
    normalized_source_id = str(supported_source_id or "").strip()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM managed_sources
            WHERE base_url = ?
               OR (domain = ? AND domain != '' AND (? = '' OR supported_source_id = ? OR supported_source_id = ''))
            ORDER BY
                CASE status
                    WHEN 'VERIFIED' THEN 0
                    WHEN 'NEEDS_REVIEW' THEN 1
                    WHEN 'IMPORTED' THEN 2
                    WHEN 'BROKEN' THEN 3
                    WHEN 'BLOCKED' THEN 4
                    ELSE 5
                END,
                updated_at DESC
            LIMIT 1
            """,
            (normalized_url, normalized_domain, normalized_source_id, normalized_source_id),
        ).fetchone()
    return _managed_source_row_to_dict(row) if row else None


def list_managed_sources(
    db_path: Path,
    *,
    query: str = "",
    status: str = "",
    trust_level: str = "",
    language: str = "",
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    safe_page = max(1, int(page or 1))
    safe_per_page = min(200, max(1, int(per_page or 50)))
    where: list[str] = []
    params: list[Any] = []

    search = query.strip().casefold()
    if search:
        like = f"%{search}%"
        where.append(
            "("
            "lower(name) LIKE ? OR lower(base_url) LIKE ? OR lower(domain) LIKE ? OR lower(notes) LIKE ?"
            ")"
        )
        params.extend([like, like, like, like])

    normalized_status = status.strip().upper()
    if normalized_status:
        where.append("status = ?")
        params.append(normalized_status)

    normalized_trust = trust_level.strip().upper()
    if normalized_trust:
        where.append("trust_level = ?")
        params.append(normalized_trust)

    normalized_language = language.strip()
    if normalized_language:
        where.append("language = ?")
        params.append(normalized_language)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    offset = (safe_page - 1) * safe_per_page
    with get_connection(db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM managed_sources {where_sql}", params).fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT *
            FROM managed_sources
            {where_sql}
            ORDER BY
                CASE status
                    WHEN 'VERIFIED' THEN 0
                    WHEN 'NEEDS_REVIEW' THEN 1
                    WHEN 'IMPORTED' THEN 2
                    WHEN 'BROKEN' THEN 3
                    WHEN 'BLOCKED' THEN 4
                    ELSE 5
                END,
                updated_at DESC,
                name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_per_page, offset],
        ).fetchall()
    return {
        "items": [_managed_source_row_to_dict(row) for row in rows],
        "total": total,
        "page": safe_page,
        "per_page": safe_per_page,
    }


def import_managed_sources_from_catalog(db_path: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    now = _utcnow_text()
    inserted = 0
    skipped = 0
    duplicates = 0
    invalid = 0
    items: list[dict[str, Any]] = []

    with get_connection(db_path) as conn:
        for source in sources:
            catalog_entry_id = str(source.get("catalog_entry_id") or source.get("id") or "").strip()
            base_url = str(source.get("base_url") or source.get("url") or "").strip()
            domain = str(source.get("domain") or "").strip().casefold()
            if not catalog_entry_id or not base_url or not domain:
                invalid += 1
                continue

            existing = conn.execute(
                """
                SELECT * FROM managed_sources
                WHERE catalog_entry_id = ? OR base_url = ?
                LIMIT 1
                """,
                (catalog_entry_id, base_url),
            ).fetchone()
            if existing is not None:
                duplicates += 1
                items.append(_managed_source_row_to_dict(existing))
                continue

            source_id = f"src_{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO managed_sources (
                    id, catalog_entry_id, name, base_url, domain, language,
                    parser_type, parser_config_json, status, trust_level,
                    supported_source_id, rate_limit_requests_per_minute,
                    rate_limit_delay_ms, max_concurrent_requests,
                    cooldown_after_error_seconds, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    catalog_entry_id,
                    str(source.get("name") or ""),
                    base_url,
                    domain,
                    str(source.get("language") or "zh-CN"),
                    str(source.get("parser_type") or "policy_supported"),
                    json.dumps(source.get("parser_config") or {}, ensure_ascii=False),
                    str(source.get("status") or "NEEDS_REVIEW"),
                    str(source.get("trust_level") or "MANUAL_ONLY"),
                    str(source.get("supported_source_id") or ""),
                    int(source.get("rate_limit_requests_per_minute") or 6),
                    int(source.get("rate_limit_delay_ms") or 8000),
                    int(source.get("max_concurrent_requests") or 1),
                    int(source.get("cooldown_after_error_seconds") or 900),
                    str(source.get("notes") or ""),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM managed_sources WHERE id = ?", (source_id,)).fetchone()
            if row is None:
                skipped += 1
                continue
            inserted += 1
            items.append(_managed_source_row_to_dict(row))
        conn.commit()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "duplicates": duplicates,
        "invalid": invalid,
        "items": items,
    }


def update_managed_source(
    db_path: Path,
    source_id: str,
    *,
    status: str | None = None,
    trust_level: str | None = None,
    parser_type: str | None = None,
    parser_config: dict[str, Any] | None = None,
    notes: str | None = None,
    rate_limit_requests_per_minute: int | None = None,
    rate_limit_delay_ms: int | None = None,
    max_concurrent_requests: int | None = None,
    cooldown_after_error_seconds: int | None = None,
    last_test_status: str | None = None,
    last_tested_at: str | None = None,
    last_successful_fetch_at: str | None = None,
    last_error: str | None = None,
) -> dict[str, Any] | None:
    current = get_managed_source(db_path, source_id)
    if current is None:
        return None

    fields: dict[str, Any] = {"updated_at": _utcnow_text()}
    if status is not None:
        fields["status"] = status
    if trust_level is not None:
        fields["trust_level"] = trust_level
    if parser_type is not None:
        fields["parser_type"] = parser_type
    if parser_config is not None:
        fields["parser_config_json"] = json.dumps(parser_config, ensure_ascii=False)
    if notes is not None:
        fields["notes"] = notes
    if rate_limit_requests_per_minute is not None:
        fields["rate_limit_requests_per_minute"] = int(rate_limit_requests_per_minute)
    if rate_limit_delay_ms is not None:
        fields["rate_limit_delay_ms"] = int(rate_limit_delay_ms)
    if max_concurrent_requests is not None:
        fields["max_concurrent_requests"] = int(max_concurrent_requests)
    if cooldown_after_error_seconds is not None:
        fields["cooldown_after_error_seconds"] = int(cooldown_after_error_seconds)
    if last_test_status is not None:
        fields["last_test_status"] = last_test_status
    if last_tested_at is not None:
        fields["last_tested_at"] = last_tested_at
    if last_successful_fetch_at is not None:
        fields["last_successful_fetch_at"] = last_successful_fetch_at
    if last_error is not None:
        fields["last_error"] = last_error

    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = [*fields.values(), str(source_id or "").strip()]
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE managed_sources SET {assignments} WHERE id = ?", params)
        conn.commit()
        row = conn.execute("SELECT * FROM managed_sources WHERE id = ?", (str(source_id or "").strip(),)).fetchone()
    return _managed_source_row_to_dict(row) if row else None


def record_managed_source_test(db_path: Path, result: dict[str, Any]) -> int:
    source_id = str(result.get("source_id") or "").strip()
    status = str(result.get("status") or "").strip()
    reason = str(result.get("reason") or "").strip()
    final_url = str(result.get("final_url") or "").strip()
    tested_at = str(result.get("tested_at") or _utcnow_text())
    http_status = result.get("http_status")
    safe_http_status = int(http_status) if http_status is not None else None
    success_at = tested_at if status == "success" else None
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO managed_source_tests
                (source_id, status, reason, http_status, final_url, tested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_id, status, reason, safe_http_status, final_url, tested_at),
        )
        conn.execute(
            """
            UPDATE managed_sources
            SET
                last_test_status = ?,
                last_tested_at = ?,
                last_successful_fetch_at = COALESCE(?, last_successful_fetch_at),
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                tested_at,
                success_at,
                "" if status == "success" else reason,
                _utcnow_text(),
                source_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_managed_source_tests(db_path: Path, source_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM managed_source_tests
            WHERE source_id = ?
            ORDER BY tested_at DESC, id DESC
            LIMIT ?
            """,
            (str(source_id or "").strip(), max(1, int(limit or 20))),
        ).fetchall()
    return [dict(row) for row in rows]


# ── Source Adapter Candidates ────────────────────────────────────────────────

def _source_adapter_candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["detected_chapter_list"] = _decode_json_field(item.get("detected_chapter_list"), [])
    return item


def insert_source_adapter_candidate(db_path: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow_text()
    candidate_id = str(candidate.get("id") or f"cand_{uuid.uuid4().hex}").strip()
    catalog_entry_id = str(candidate.get("catalog_entry_id") or "").strip()
    chapter_list = candidate.get("detected_chapter_list") or []
    if not isinstance(chapter_list, list):
        chapter_list = []
    created_at = str(candidate.get("created_at") or now)
    updated_at = str(candidate.get("updated_at") or now)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_adapter_candidates (
                id, catalog_entry_id, domain, sample_url, detected_title,
                detected_chapter_list, parser_confidence, failure_reason,
                status, created_at, updated_at, reviewed_at, reviewed_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                catalog_entry_id,
                str(candidate.get("domain") or ""),
                str(candidate.get("sample_url") or ""),
                str(candidate.get("detected_title") or ""),
                json.dumps(chapter_list, ensure_ascii=False),
                str(candidate.get("parser_confidence") or "low"),
                str(candidate.get("failure_reason") or ""),
                str(candidate.get("status") or "draft"),
                created_at,
                updated_at,
                str(candidate.get("reviewed_at") or ""),
                str(candidate.get("reviewed_by") or ""),
            ),
        )
        row = conn.execute("SELECT * FROM source_adapter_candidates WHERE id = ?", (candidate_id,)).fetchone()
        conn.commit()
    if row is None:
        return {}
    return _source_adapter_candidate_row_to_dict(row)


def get_source_adapter_candidate(db_path: Path, candidate_id: str) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM source_adapter_candidates WHERE id = ?",
            (str(candidate_id or "").strip(),),
        ).fetchone()
    return _source_adapter_candidate_row_to_dict(row) if row else None


def list_source_adapter_candidates(
    db_path: Path,
    *,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    safe_page = max(1, int(page or 1))
    safe_per_page = min(200, max(1, int(per_page or 50)))
    offset = (safe_page - 1) * safe_per_page
    with get_connection(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM source_adapter_candidates").fetchone()[0])
        rows = conn.execute(
            """
            SELECT *
            FROM source_adapter_candidates
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (safe_per_page, offset),
        ).fetchall()
    return {
        "items": [_source_adapter_candidate_row_to_dict(row) for row in rows],
        "total": total,
        "page": safe_page,
        "per_page": safe_per_page,
        "page_size": safe_per_page,
    }


# ── Books ──────────────────────────────────────────────────────────────────

def add_book(
    db_path: Path,
    title: str,
    author: str = "",
    source: str = "manual",
    source_url: str = "",
    cover_path: str = "",
    owner_user_id: str = "",
) -> int:
    book_key = normalize_book_key(title)
    resolved_owner_user_id = _resolve_owner_user_id_for_write(db_path, owner_user_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO books (title, book_key, owner_user_id, author, source, source_url, cover_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, book_key, resolved_owner_user_id, author, source, source_url, cover_path),
        )
        conn.commit()
        return cur.lastrowid


def get_book_by_title(db_path: Path, title: str) -> Optional[dict]:
    book_key = normalize_book_key(title)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE title = ?", (title,)).fetchone()
        if not row and book_key:
            row = conn.execute(
                "SELECT * FROM books WHERE book_key = ? ORDER BY id ASC LIMIT 1",
                (book_key,),
            ).fetchone()
        return dict(row) if row else None


def get_book_by_id(db_path: Path, book_id: int) -> Optional[dict]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None


def list_books(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM books ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def list_books_with_active_chapters(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT books.*
            FROM books
            WHERE EXISTS (
                SELECT 1
                FROM chapters
                WHERE chapters.book_id = books.id
                  AND chapters.deleted_at IS NULL
            )
            ORDER BY books.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_translated_book_summaries(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            WITH active_chapters AS (
                SELECT
                    chapters.*,
                    CASE
                        WHEN COALESCE(chapters.translated_text_path, '') != ''
                          OR COALESCE(chapters.content_html_path, '') != ''
                          OR chapters.status IN ('translated', 'qa_low', 'audio_done')
                        THEN 1 ELSE 0
                    END AS has_translation
                FROM chapters
                WHERE chapters.deleted_at IS NULL
            ),
            chapter_counts AS (
                SELECT
                    book_id,
                    COUNT(*) AS total_chapters,
                    SUM(has_translation) AS translated_chapters,
                    SUM(CASE WHEN COALESCE(audio_path, '') != '' THEN 1 ELSE 0 END) AS audio_chapters,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_chapters,
                    SUM(CASE WHEN status = 'qa_low' THEN 1 ELSE 0 END) AS qa_low_chapters
                FROM active_chapters
                GROUP BY book_id
            ),
            translated_ranked AS (
                SELECT
                    book_id,
                    id,
                    chapter_number,
                    title,
                    translated_at,
                    audio_created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY book_id ORDER BY chapter_number ASC, id ASC
                    ) AS first_rank,
                    ROW_NUMBER() OVER (
                        PARTITION BY book_id ORDER BY chapter_number DESC, id DESC
                    ) AS latest_rank
                FROM active_chapters
                WHERE has_translation = 1
            ),
            translated_bounds AS (
                SELECT
                    book_id,
                    MAX(CASE WHEN first_rank = 1 THEN id END) AS first_translated_chapter_id,
                    MAX(CASE WHEN latest_rank = 1 THEN id END) AS latest_translated_chapter_id,
                    MAX(CASE WHEN latest_rank = 1 THEN chapter_number END) AS latest_chapter_number,
                    MAX(CASE WHEN latest_rank = 1 THEN title END) AS latest_chapter_title,
                    MAX(CASE WHEN latest_rank = 1 THEN translated_at END) AS latest_translated_at,
                    MAX(CASE WHEN latest_rank = 1 THEN audio_created_at END) AS latest_audio_created_at
                FROM translated_ranked
                GROUP BY book_id
            )
            SELECT
                books.id,
                books.title,
                books.author,
                books.source,
                books.source_url,
                books.cover_path,
                chapter_counts.total_chapters,
                chapter_counts.translated_chapters,
                chapter_counts.audio_chapters,
                chapter_counts.failed_chapters,
                chapter_counts.qa_low_chapters,
                translated_bounds.first_translated_chapter_id,
                translated_bounds.latest_translated_chapter_id,
                translated_bounds.latest_chapter_number,
                translated_bounds.latest_chapter_title,
                COALESCE(
                    NULLIF(translated_bounds.latest_translated_at, ''),
                    NULLIF(translated_bounds.latest_audio_created_at, ''),
                    books.created_at,
                    ''
                ) AS last_activity
            FROM books
            JOIN chapter_counts ON chapter_counts.book_id = books.id
            JOIN translated_bounds ON translated_bounds.book_id = books.id
            WHERE chapter_counts.translated_chapters > 0
            ORDER BY last_activity DESC, books.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _is_empty_value(value: object) -> bool:
    return value is None or value == ""


def _best_chapter_status(target: sqlite3.Row, source: sqlite3.Row) -> str:
    if target["audio_path"]:
        return target["status"] or "audio_done"
    if source["audio_path"]:
        return source["status"] or "audio_done"
    if target["translated_text_path"]:
        return target["status"] or "translated"
    if source["translated_text_path"]:
        return source["status"] or "translated"
    if target["cleaned_text_path"]:
        return target["status"] or "cleaned"
    if source["cleaned_text_path"]:
        return source["status"] or "cleaned"
    return target["status"] or source["status"] or "imported"


def _merge_chapter_into_existing(conn: sqlite3.Connection, source: sqlite3.Row, target: sqlite3.Row) -> None:
    merged_fields = {
        "title": target["title"] if not _is_empty_value(target["title"]) else source["title"],
        "source_url": target["source_url"] if not _is_empty_value(target["source_url"]) else source["source_url"],
        "adapter_id": target["adapter_id"] if not _is_empty_value(target["adapter_id"]) else source["adapter_id"],
        "raw_text_path": target["raw_text_path"] if not _is_empty_value(target["raw_text_path"]) else source["raw_text_path"],
        "cleaned_text_path": (
            target["cleaned_text_path"] if not _is_empty_value(target["cleaned_text_path"]) else source["cleaned_text_path"]
        ),
        "translated_text_path": (
            target["translated_text_path"]
            if not _is_empty_value(target["translated_text_path"])
            else source["translated_text_path"]
        ),
        "content_html_path": (
            target["content_html_path"]
            if not _is_empty_value(target["content_html_path"])
            else source["content_html_path"]
        ),
        "audio_path": target["audio_path"] if not _is_empty_value(target["audio_path"]) else source["audio_path"],
        "source_hash": target["source_hash"] if not _is_empty_value(target["source_hash"]) else source["source_hash"],
        "status": _best_chapter_status(target, source),
        "translated_at": target["translated_at"] or source["translated_at"],
        "audio_created_at": target["audio_created_at"] or source["audio_created_at"],
    }
    conn.execute(
        """
        UPDATE chapters
        SET title = ?,
            source_url = ?,
            adapter_id = ?,
            raw_text_path = ?,
            cleaned_text_path = ?,
            translated_text_path = ?,
            content_html_path = ?,
            audio_path = ?,
            source_hash = ?,
            status = ?,
            translated_at = ?,
            audio_created_at = ?
        WHERE id = ?
        """,
        (
            merged_fields["title"],
            merged_fields["source_url"],
            merged_fields["adapter_id"],
            merged_fields["raw_text_path"],
            merged_fields["cleaned_text_path"],
            merged_fields["translated_text_path"],
            merged_fields["content_html_path"],
            merged_fields["audio_path"],
            merged_fields["source_hash"],
            merged_fields["status"],
            merged_fields["translated_at"],
            merged_fields["audio_created_at"],
            target["id"],
        ),
    )

    deleted_at = datetime.now(timezone.utc).isoformat()
    if _table_exists(conn, "reader_annotations"):
        conn.execute(
            """
            UPDATE reader_annotations
            SET book_id = ?, chapter_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chapter_id = ?
            """,
            (target["book_id"], target["id"], source["id"]),
        )
    if _table_exists(conn, "reader_progress"):
        conn.execute(
            """
            UPDATE OR REPLACE reader_progress
            SET book_id = ?, chapter_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chapter_id = ?
            """,
            (target["book_id"], target["id"], source["id"]),
        )
    conn.execute(
        """
        UPDATE chapters
        SET chapter_number = -ABS(id),
            status = 'deleted',
            deleted_at = ?
        WHERE id = ?
        """,
        (deleted_at, source["id"]),
    )


def _merge_book_into_existing(
    conn: sqlite3.Connection,
    source_book_id: int,
    target_book_id: int,
    *,
    title: str,
    author: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
    cover_path: str | None = None,
) -> None:
    target = conn.execute("SELECT * FROM books WHERE id = ?", (target_book_id,)).fetchone()
    source_book = conn.execute("SELECT * FROM books WHERE id = ?", (source_book_id,)).fetchone()
    if not target or not source_book:
        return

    target_updates = {
        "title": title,
        "book_key": normalize_book_key(title),
        "author": target["author"] if not _is_empty_value(target["author"]) else (author or source_book["author"]),
        "source": target["source"] if not _is_empty_value(target["source"]) else (source or source_book["source"]),
        "source_url": (
            target["source_url"] if not _is_empty_value(target["source_url"]) else (source_url or source_book["source_url"])
        ),
        "cover_path": (
            target["cover_path"] if not _is_empty_value(target["cover_path"]) else (cover_path or source_book["cover_path"])
        ),
    }
    conn.execute(
        """
        UPDATE books
        SET title = ?,
            book_key = ?,
            author = ?,
            source = ?,
            source_url = ?,
            cover_path = ?
        WHERE id = ?
        """,
        (
            target_updates["title"],
            target_updates["book_key"],
            target_updates["author"],
            target_updates["source"],
            target_updates["source_url"],
            target_updates["cover_path"],
            target_book_id,
        ),
    )

    source_chapters = conn.execute(
        """
        SELECT * FROM chapters
        WHERE book_id = ? AND deleted_at IS NULL
        ORDER BY chapter_number ASC, id ASC
        """,
        (source_book_id,),
    ).fetchall()
    for source_chapter in source_chapters:
        target_chapter = conn.execute(
            """
            SELECT * FROM chapters
            WHERE book_id = ? AND chapter_number = ? AND deleted_at IS NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (target_book_id, source_chapter["chapter_number"]),
        ).fetchone()
        if target_chapter:
            _merge_chapter_into_existing(conn, source_chapter, target_chapter)
        else:
            conn.execute("UPDATE chapters SET book_id = ? WHERE id = ?", (target_book_id, source_chapter["id"]))

    if _table_exists(conn, "glossary_terms"):
        conn.execute(
            """
            UPDATE OR IGNORE glossary_terms
            SET book_id = ?
            WHERE book_id = ?
            """,
            (target_book_id, source_book_id),
        )
        conn.execute("DELETE FROM glossary_terms WHERE book_id = ?", (source_book_id,))
    if _table_exists(conn, "user_corrections"):
        conn.execute("UPDATE user_corrections SET book_id = ? WHERE book_id = ?", (target_book_id, source_book_id))
    if _table_exists(conn, "reader_annotations"):
        conn.execute("UPDATE reader_annotations SET book_id = ? WHERE book_id = ?", (target_book_id, source_book_id))
    if _table_exists(conn, "reader_progress"):
        target_progress = conn.execute("SELECT 1 FROM reader_progress WHERE book_id = ?", (target_book_id,)).fetchone()
        if target_progress:
            conn.execute("DELETE FROM reader_progress WHERE book_id = ?", (source_book_id,))
        else:
            conn.execute("UPDATE reader_progress SET book_id = ? WHERE book_id = ?", (target_book_id, source_book_id))
    conn.execute("DELETE FROM books WHERE id = ?", (source_book_id,))


def _consolidate_duplicate_book_keys(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, "books") and _table_exists(conn, "chapters")):
        return

    groups = conn.execute(
        """
        SELECT book_key
        FROM books
        WHERE book_key IS NOT NULL AND book_key != ''
        GROUP BY book_key
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for group in groups:
        books = conn.execute(
            """
            SELECT * FROM books
            WHERE book_key = ?
            ORDER BY id ASC
            """,
            (group["book_key"],),
        ).fetchall()
        if len(books) < 2:
            continue

        target = books[0]
        for source_book in books[1:]:
            _merge_book_into_existing(
                conn,
                int(source_book["id"]),
                int(target["id"]),
                title=target["title"] or source_book["title"],
            )


def update_book(
    db_path: Path,
    book_id: int,
    *,
    title: str | None = None,
    author: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
    cover_path: str | None = None,
) -> bool:
    next_book_key = normalize_book_key(title) if title is not None else None

    updates = {
        "title": title,
        "book_key": next_book_key,
        "author": author,
        "source": source,
        "source_url": source_url,
        "cover_path": cover_path,
    }
    fields = [f"{column} = ?" for column, value in updates.items() if value is not None]
    params = [value for value in updates.values() if value is not None]
    if not fields:
        return get_book_by_id(db_path, book_id) is not None

    with get_connection(db_path) as conn:
        if title is not None and next_book_key:
            target = conn.execute(
                """
                SELECT id FROM books
                WHERE book_key = ? AND id != ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (next_book_key, book_id),
            ).fetchone()
            if target:
                _merge_book_into_existing(
                    conn,
                    book_id,
                    int(target["id"]),
                    title=title,
                    author=author,
                    source=source,
                    source_url=source_url,
                    cover_path=cover_path,
                )
                conn.commit()
                return True

        params.append(book_id)
        cur = conn.execute(f"UPDATE books SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        return cur.rowcount > 0


def delete_book(db_path: Path, book_id: int) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
        return cur.rowcount > 0


# ── Ebook Import Runs ─────────────────────────────────────────────────────

def record_ebook_import_run(
    db_path: Path,
    *,
    book_id: int,
    title: str,
    filename: str,
    source_format: str,
    duplicate_strategy: str,
    split_mode: str,
    chapter_count: int,
    imported_chapters: int,
    skipped_chapters: int,
    overwritten_chapters: int = 0,
    warnings: list[dict] | None = None,
    owner_user_id: str = "",
) -> int:
    warnings_json = json.dumps(warnings or [], ensure_ascii=False)
    resolved_owner_user_id = _resolve_owner_user_id_for_write(db_path, owner_user_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ebook_import_runs (
                book_id, owner_user_id, title, filename, source_format, duplicate_strategy,
                split_mode, chapter_count, imported_chapters, skipped_chapters,
                overwritten_chapters, warning_count, warnings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                resolved_owner_user_id,
                title,
                filename,
                source_format,
                duplicate_strategy,
                split_mode,
                chapter_count,
                imported_chapters,
                skipped_chapters,
                overwritten_chapters,
                len(warnings or []),
                warnings_json,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_ebook_import_runs(db_path: Path, limit: int = 20) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM ebook_import_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    runs: list[dict] = []
    for row in rows:
        item = dict(row)
        item["warnings"] = _decode_json_field(item.pop("warnings_json", "[]"), [])
        runs.append(item)
    return runs


# ── Chapters ───────────────────────────────────────────────────────────────

def find_import_book_with_connection(
    conn: sqlite3.Connection,
    *,
    title: str,
    target_book_id: int | None = None,
) -> Optional[dict]:
    if target_book_id is not None:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (target_book_id,)).fetchone()
        return dict(row) if row else None

    book_key = normalize_book_key(title)
    row = conn.execute("SELECT * FROM books WHERE title = ?", (title,)).fetchone()
    if not row and book_key:
        row = conn.execute(
            "SELECT * FROM books WHERE book_key = ? ORDER BY id ASC LIMIT 1",
            (book_key,),
        ).fetchone()
    return dict(row) if row else None


def resolve_import_book_with_connection(
    conn: sqlite3.Connection,
    *,
    title: str,
    author: str = "",
    source: str = "wizard",
    target_book_id: int | None = None,
) -> dict:
    book = find_import_book_with_connection(
        conn,
        title=title,
        target_book_id=target_book_id,
    )
    if target_book_id is not None and not book:
        raise ValueError(f"Book {target_book_id} not found")

    if book:
        updates: list[str] = []
        params: list[Any] = []
        if author and not str(book.get("author") or ""):
            updates.append("author = ?")
            params.append(author)
        current_source = str(book.get("source") or "")
        if source and (not current_source or current_source == "manual"):
            updates.append("source = ?")
            params.append(source)
        if updates:
            params.append(int(book["id"]))
            conn.execute(f"UPDATE books SET {', '.join(updates)} WHERE id = ?", params)
            row = conn.execute("SELECT * FROM books WHERE id = ?", (int(book["id"]),)).fetchone()
            book = dict(row)
        return book

    operator_user = _seed_operator_user_from_env(conn)
    owner_user_id = str(operator_user.get("id") or "")
    cursor = conn.execute(
        """
        INSERT INTO books (title, book_key, owner_user_id, author, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (title, normalize_book_key(title), owner_user_id, author, source),
    )
    row = conn.execute("SELECT * FROM books WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def list_active_import_chapters_with_connection(
    conn: sqlite3.Connection,
    book_id: int,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM chapters
        WHERE book_id = ? AND deleted_at IS NULL
        ORDER BY chapter_number ASC, id ASC
        """,
        (book_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_import_chapter_with_connection(
    conn: sqlite3.Connection,
    *,
    book_id: int,
    chapter_number: int,
    title: str,
    raw_text_path: Path | None,
    translated_text_path: Path | None,
    source_hash: str,
    status: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO chapters (
            book_id, chapter_number, title, raw_text_path, translated_text_path,
            source_hash, status, translated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE NULL END)
        """,
        (
            book_id,
            chapter_number,
            title,
            str(raw_text_path) if raw_text_path else None,
            str(translated_text_path) if translated_text_path else None,
            source_hash,
            status,
            str(translated_text_path) if translated_text_path else None,
        ),
    )
    return int(cursor.lastrowid)


def update_import_chapter_with_connection(
    conn: sqlite3.Connection,
    *,
    chapter_id: int,
    title: str,
    raw_text_path: Path | None,
    translated_text_path: Path | None,
    status: str,
) -> None:
    fields = ["title = ?", "status = ?"]
    params: list[Any] = [title, status]
    if raw_text_path is not None:
        fields.append("raw_text_path = ?")
        params.append(str(raw_text_path))
    if translated_text_path is not None:
        fields.extend(["translated_text_path = ?", "translated_at = CURRENT_TIMESTAMP"])
        params.append(str(translated_text_path))
    params.append(chapter_id)
    conn.execute(f"UPDATE chapters SET {', '.join(fields)} WHERE id = ?", params)


def add_chapter(
    db_path: Path,
    book_id: int,
    chapter_number: int,
    title: str,
    source_url: str = "",
    raw_text_path: Optional[Path] = None,
    source_hash: str = "",
    adapter_id: str = "",
) -> int:
    with get_connection(db_path) as conn:
        duplicate_number = conn.execute(
            """
            SELECT id FROM chapters
            WHERE book_id = ? AND chapter_number = ? AND deleted_at IS NULL
            LIMIT 1
            """,
            (book_id, chapter_number),
        ).fetchone()
        if duplicate_number:
            raise ValueError(f"Duplicate chapter number {chapter_number} for book {book_id}")
        if source_hash:
            duplicate_source = conn.execute(
                """
                SELECT id FROM chapters
                WHERE book_id = ? AND source_hash = ? AND deleted_at IS NULL
                LIMIT 1
                """,
                (book_id, source_hash),
            ).fetchone()
            if duplicate_source:
                raise ValueError(f"Duplicate chapter source for book {book_id}")
        cur = conn.execute(
            """INSERT INTO chapters (book_id, chapter_number, title, source_url, adapter_id, raw_text_path, source_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                book_id,
                chapter_number,
                title,
                source_url,
                adapter_id,
                str(raw_text_path) if raw_text_path else None,
                source_hash,
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_chapter_paths(
    db_path: Path,
    chapter_id: int,
    *,
    title: Optional[str] = None,
    raw_text_path: Optional[Path] = None,
    cleaned_text_path: Optional[Path] = None,
    translated_text_path: Optional[Path] = None,
    content_html_path: Optional[Path] = None,
    clear_content_html_path: bool = False,
    audio_path: Optional[Path] = None,
    status: Optional[str] = None,
) -> None:
    fields = []
    params: list = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if raw_text_path is not None:
        fields.append("raw_text_path = ?")
        params.append(str(raw_text_path))
    if cleaned_text_path is not None:
        fields.append("cleaned_text_path = ?")
        params.append(str(cleaned_text_path))
    if translated_text_path is not None:
        fields.append("translated_text_path = ?")
        params.append(str(translated_text_path))
    if content_html_path is not None:
        fields.append("content_html_path = ?")
        params.append(str(content_html_path))
    if clear_content_html_path:
        fields.append("content_html_path = NULL")
    if audio_path is not None:
        fields.append("audio_path = ?")
        params.append(str(audio_path))
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if translated_text_path is not None:
        fields.append("translated_at = CURRENT_TIMESTAMP")
    if audio_path is not None:
        fields.append("audio_created_at = CURRENT_TIMESTAMP")
    if not fields:
        return
    params.append(chapter_id)
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE chapters SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()


def get_chapter(db_path: Path, book_id: int, chapter_number: int) -> Optional[dict]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM chapters
            WHERE book_id = ? AND chapter_number = ? AND deleted_at IS NULL
            """,
            (book_id, chapter_number),
        ).fetchone()
        return dict(row) if row else None


def get_chapter_by_id(db_path: Path, chapter_id: int, include_deleted: bool = False) -> Optional[dict]:
    with get_connection(db_path) as conn:
        sql = "SELECT * FROM chapters WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row = conn.execute(sql, (chapter_id,)).fetchone()
        return dict(row) if row else None


def list_chapters(db_path: Path, book_id: Optional[int] = None, include_deleted: bool = False) -> list[dict]:
    deleted_clause = "" if include_deleted else "deleted_at IS NULL"
    with get_connection(db_path) as conn:
        if book_id is not None:
            where = "book_id = ?"
            if deleted_clause:
                where += f" AND {deleted_clause}"
            rows = conn.execute(
                f"SELECT * FROM chapters WHERE {where} ORDER BY chapter_number DESC",
                (book_id,),
            ).fetchall()
        else:
            where = f"WHERE {deleted_clause}" if deleted_clause else ""
            rows = conn.execute(f"SELECT * FROM chapters {where} ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def _delete_mobile_jobs_for_chapter(conn: sqlite3.Connection, chapter_id: int) -> None:
    rows = conn.execute("SELECT job_id, target_ids_json FROM mobile_jobs").fetchall()
    for row in rows:
        target_ids = _decode_json_field(row["target_ids_json"], [])
        if chapter_id in target_ids or str(chapter_id) in target_ids:
            conn.execute("DELETE FROM mobile_jobs WHERE job_id = ?", (row["job_id"],))


def _delete_chapter_auxiliary_rows(conn: sqlite3.Connection, chapter_id: int) -> None:
    conn.execute("DELETE FROM qa_reports WHERE chapter_id = ?", (chapter_id,))
    conn.execute("DELETE FROM translation_jobs WHERE chapter_id = ?", (chapter_id,))
    conn.execute("DELETE FROM chapter_summaries WHERE chapter_id = ?", (chapter_id,))
    conn.execute("DELETE FROM provider_usage WHERE chapter_id = ?", (chapter_id,))
    conn.execute("DELETE FROM job_attempts WHERE chapter_id = ?", (chapter_id,))
    _delete_mobile_jobs_for_chapter(conn, chapter_id)


def delete_chapter_translation_data(db_path: Path, chapter_id: int) -> bool:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM chapters WHERE id = ? AND deleted_at IS NULL",
            (chapter_id,),
        ).fetchone()
        if not row:
            return False
        _delete_chapter_auxiliary_rows(conn, chapter_id)
        if _table_exists(conn, "reader_progress"):
            conn.execute("DELETE FROM reader_progress WHERE chapter_id = ?", (chapter_id,))
        if _table_exists(conn, "reader_annotations"):
            conn.execute("DELETE FROM reader_annotations WHERE chapter_id = ?", (chapter_id,))
        conn.execute(
            """
            UPDATE chapters
            SET translated_text_path = NULL,
                content_html_path = NULL,
                audio_path = NULL,
                translated_at = NULL,
                audio_created_at = NULL,
                status = 'cleaned'
            WHERE id = ?
            """,
            (chapter_id,),
        )
        conn.commit()
        return True


def soft_delete_chapter(db_path: Path, chapter_id: int) -> bool:
    deleted_at = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM chapters WHERE id = ? AND deleted_at IS NULL",
            (chapter_id,),
        ).fetchone()
        if not row:
            return False
        _delete_chapter_auxiliary_rows(conn, chapter_id)
        conn.execute(
            """
            UPDATE chapters
            SET raw_text_path = NULL,
                cleaned_text_path = NULL,
                translated_text_path = NULL,
                content_html_path = NULL,
                audio_path = NULL,
                translated_at = NULL,
                audio_created_at = NULL,
                chapter_number = -ABS(id),
                status = 'deleted',
                deleted_at = ?
            WHERE id = ?
            """,
            (deleted_at, chapter_id),
        )
        conn.commit()
        return True


def sort_glossary_terms(terms: list[dict]) -> list[dict]:
    """Sort glossary terms by priority (high first), then by source term length (longer first), then alphabetically.

    OmegaT-style sorting: priority entries first, then longer source terms (more specific), then alphabetical.
    """
    return sorted(terms, key=lambda t: (
        -t.get('priority', 0),           # high priority first
        -len(t.get('source_term', '')),  # longer source first (more specific)
        t.get('source_term', '').lower(),
    ))


# ── Glossary ───────────────────────────────────────────────────────────────

def _split_glossary_variants(variants: str | None) -> list[str]:
    if not variants:
        return []
    normalized = variants
    for separator in ("|", "/", ",", "，", ";", "；", "\n", "\r"):
        normalized = normalized.replace(separator, "|")
    seen: set[str] = set()
    result: list[str] = []
    for variant in (part.strip() for part in normalized.split("|")):
        if variant and variant not in seen:
            seen.add(variant)
            result.append(variant)
    return result


def _styleguide_locked_term_row(term: dict, index: int = 0) -> dict:
    term_type = str(term.get("term_type") or "term").strip() or "term"
    return {
        "id": -100000 - index,
        "book_id": 0,
        "source_term": str(term.get("source") or "").strip(),
        "target_term": str(term.get("target") or "").strip(),
        "category": term_type,
        "approved": 1,
        "mode": str(term.get("mode") or "translate").strip() or "translate",
        "pinyin": str(term.get("pinyin") or "").strip(),
        "notes_vi": str(term.get("note") or "").strip(),
        "variants": str(term.get("variants") or "").strip(),
        "occurrence_count": 0,
        "priority": int(term.get("priority") or 0),
        "locked": 1,
        "genre": str(term.get("genre") or "").strip(),
        "term_type": term_type,
    }


def _styleguide_locked_term_rows(genre: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for index, term in enumerate(get_locked_terms()):
        row = _styleguide_locked_term_row(term, index)
        if not row["source_term"] or not row["target_term"]:
            continue
        if genre and row["genre"] and row["genre"] != genre:
            continue
        rows.append(row)
    return rows


def load_glossary(db_path: Path, book_id: int = 0) -> dict[str, str]:
    """Load approved translate-mode glossary terms for forced substitution.

    Only returns terms with mode='translate'. Terms with mode='context' or
    mode='transliterate' are handled separately (prompt context / name map).
    """
    glossary: dict[str, str] = {}
    for term in _styleguide_locked_term_rows():
        if term["mode"] != "translate":
            continue
        glossary[term["source_term"]] = term["target_term"]
        for variant in _split_glossary_variants(term.get("variants")):
            glossary.setdefault(variant, term["target_term"])
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT source_term, target_term, variants FROM glossary_terms
               WHERE book_id IN (0, ?) AND approved = 1 AND mode = 'translate'
               ORDER BY book_id ASC, priority DESC, LENGTH(source_term) DESC""",
            (book_id,),
        ).fetchall()
        for src, tgt, variants in rows:
            glossary[src] = tgt
            for variant in _split_glossary_variants(variants):
                glossary.setdefault(variant, tgt)
    return glossary


def put_glossary_term(
    db_path: Path,
    book_id: int,
    source: str,
    target: str,
    category: str = "term",
    mode: str = "translate",
    pinyin: str = "",
    notes_vi: str = "",
    variants: str = "",
    approved: int = 1,
    priority: int = 0,
    locked: int = 0,
    genre: str = "",
    term_type: str = "term",
    alternatives: str = "",
    gender: str = "",
    first_seen_chapter_id: int = 0,
    first_seen_chapter_number: int = 0,
    review_status: str = "",
    source_context: str = "",
) -> None:
    """Insert or update a glossary term, tracking occurrence count.

    On insert: sets occurrence_count = 1, last_seen = CURRENT_TIMESTAMP,
    approved = provided value (default 1).
    On conflict (existing term): increments occurrence_count,
    updates last_seen, updates other fields (target, category, mode, pinyin,
    notes_vi, variants) but keeps the existing approved status.
    """
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source:
        return
    normalized_review_status = _glossary_review_status(approved=approved, locked=locked, review_status=review_status)
    with get_connection(db_path) as conn:
        # Get current values for history logging
        cur = conn.execute(
            "SELECT target_term, mode FROM glossary_terms WHERE book_id = ? AND source_term = ?",
            (book_id, source),
        )
        row = cur.fetchone()
        old_target = row[0] if row else ""
        old_mode = row[1] if row else ""

        conn.execute(
            """
            INSERT INTO glossary_terms
            (book_id, source_term, target_term, category, approved, mode, pinyin,
             notes_vi, variants, occurrence_count, priority, locked, genre, term_type,
             alternatives, gender, first_seen_chapter_id, first_seen_chapter_number,
             review_status, source_context, last_seen, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id, source_term) DO UPDATE SET
                target_term = CASE
                    WHEN NULLIF(excluded.target_term, '') IS NULL THEN glossary_terms.target_term
                    WHEN glossary_terms.locked = 1 AND excluded.approved <= 0 THEN glossary_terms.target_term
                    WHEN glossary_terms.approved = 1 AND excluded.approved <= 0 THEN glossary_terms.target_term
                    WHEN glossary_terms.approved < 0 AND excluded.approved <= 0 THEN glossary_terms.target_term
                    ELSE excluded.target_term
                END,
                category = excluded.category,
                mode = excluded.mode,
                pinyin = excluded.pinyin,
                notes_vi = excluded.notes_vi,
                variants = excluded.variants,
                priority = excluded.priority,
                locked = CASE WHEN glossary_terms.locked = 1 THEN glossary_terms.locked ELSE excluded.locked END,
                genre = excluded.genre,
                term_type = excluded.term_type,
                alternatives = COALESCE(NULLIF(excluded.alternatives, ''), glossary_terms.alternatives),
                gender = COALESCE(NULLIF(excluded.gender, ''), glossary_terms.gender),
                first_seen_chapter_id = CASE
                    WHEN glossary_terms.first_seen_chapter_id IS NULL OR glossary_terms.first_seen_chapter_id = 0
                    THEN excluded.first_seen_chapter_id
                    ELSE glossary_terms.first_seen_chapter_id
                END,
                first_seen_chapter_number = CASE
                    WHEN glossary_terms.first_seen_chapter_number IS NULL OR glossary_terms.first_seen_chapter_number = 0
                    THEN excluded.first_seen_chapter_number
                    ELSE glossary_terms.first_seen_chapter_number
                END,
                review_status = CASE
                    WHEN glossary_terms.review_status IN ('APPROVED', 'LOCKED', 'REJECTED', 'CONFLICT')
                    THEN glossary_terms.review_status
                    ELSE excluded.review_status
                END,
                source_context = COALESCE(NULLIF(excluded.source_context, ''), glossary_terms.source_context),
                occurrence_count = glossary_terms.occurrence_count + 1,
                last_seen = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                source,
                target,
                category,
                approved,
                mode,
                pinyin,
                notes_vi,
                variants,
                priority,
                locked,
                genre,
                term_type,
                alternatives,
                gender,
                first_seen_chapter_id,
                first_seen_chapter_number,
                normalized_review_status,
                source_context,
            ),
        )

        # Log the change for history
        if old_target or old_mode:
            # Update
            log_glossary_change(
                conn, book_id, source, "update",
                target, old_target, old_mode, mode
            )
        else:
            # Insert
            log_glossary_change(
                conn, book_id, source, "add",
                target, "", "", mode
            )

        conn.commit()


def update_glossary_term(
    db_path: Path,
    term_id: int,
    *,
    target_term: str | None = None,
    category: str | None = None,
    mode: str | None = None,
    pinyin: str | None = None,
    notes_vi: str | None = None,
    variants: str | None = None,
    approved: int | None = None,
    priority: int | None = None,
    locked: int | None = None,
    genre: str | None = None,
    term_type: str | None = None,
    alternatives: str | None = None,
    gender: str | None = None,
    review_status: str | None = None,
    source_context: str | None = None,
) -> bool:
    """Update glossary metadata without changing occurrence_count."""
    if mode is not None and mode not in {"", "translate", "context", "transliterate"}:
        raise ValueError(f"Invalid mode: {mode}")

    updates = {
        "target_term": target_term,
        "category": category,
        "mode": mode,
        "pinyin": pinyin,
        "notes_vi": notes_vi,
        "variants": variants,
        "approved": approved,
        "priority": priority,
        "locked": locked,
        "genre": genre,
        "term_type": term_type,
        "alternatives": alternatives,
        "gender": gender,
        "review_status": review_status,
        "source_context": source_context,
    }
    fields = [f"{column} = ?" for column, value in updates.items() if value is not None]
    params = [value for value in updates.values() if value is not None]

    with get_connection(db_path) as conn:
        current = conn.execute(
            "SELECT * FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        if not current:
            return False
        if not fields:
            return True
        fields.append("updated_at = CURRENT_TIMESTAMP")

        params.append(term_id)
        cur = conn.execute(f"UPDATE glossary_terms SET {', '.join(fields)} WHERE id = ?", params)
        new_target = target_term if target_term is not None else current["target_term"]
        new_mode = mode if mode is not None else current["mode"]
        log_glossary_change(
            conn,
            current["book_id"],
            current["source_term"],
            "update",
            new_target,
            current["target_term"],
            current["mode"],
            new_mode,
        )
        conn.commit()
        return cur.rowcount > 0


def list_glossary(db_path: Path, book_id: Optional[int] = None) -> list[dict]:
    with get_connection(db_path) as conn:
        if book_id is not None:
            rows = conn.execute(
                "SELECT * FROM glossary_terms WHERE book_id IN (0, ?) ORDER BY created_at DESC",
                (book_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM glossary_terms ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def load_locked_glossary_terms(
    db_path: Path,
    book_id: int = 0,
    genre: str | None = None,
) -> list[dict]:
    """Load approved locked glossary terms for prompt enforcement."""
    with get_connection(db_path) as conn:
        params: list[object] = [book_id]
        genre_clause = ""
        if genre:
            genre_clause = "AND (genre = '' OR genre = ?)"
            params.append(genre)
        rows = conn.execute(
            f"""
            SELECT * FROM glossary_terms
            WHERE book_id IN (0, ?)
              AND approved = 1
              AND locked = 1
              {genre_clause}
            ORDER BY book_id DESC, priority DESC, LENGTH(source_term) DESC
            """,
            params,
        ).fetchall()
        db_terms = [dict(row) for row in rows]
    seen_sources = {str(term.get("source_term") or "") for term in db_terms}
    combined = db_terms + [
        term for term in _styleguide_locked_term_rows(genre=genre)
        if term["source_term"] not in seen_sources
    ]
    combined.sort(
        key=lambda term: (
            int(term.get("book_id") or 0),
            int(term.get("priority") or 0),
            len(str(term.get("source_term") or "")),
        ),
        reverse=True,
    )
    return combined


def select_prompt_glossary_terms(
    db_path: Path,
    book_id: int,
    source_text: str,
    *,
    max_terms: int = 40,
    max_chars: int = 2200,
) -> list[dict]:
    """Select a bounded, deterministic glossary subset for prompt injection.

    Rejected/pending terms are excluded. Book-specific rows naturally override
    global rows because they sort before global rows for the same source term.
    """
    source_text = source_text or ""
    selected: list[dict] = []
    used_chars = 0
    seen_sources: set[str] = set()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM glossary_terms
            WHERE book_id IN (0, ?)
              AND approved = 1
              AND COALESCE(review_status, '') != 'REJECTED'
              AND source_term != ''
              AND target_term != ''
            ORDER BY
              locked DESC,
              book_id DESC,
              priority DESC,
              confidence DESC,
              occurrence_count DESC,
              LENGTH(source_term) DESC,
              source_term ASC
            """,
            (book_id,),
        ).fetchall()
    for row in rows:
        term = dict(row)
        source = str(term.get("source_term") or "")
        target = str(term.get("target_term") or "")
        if source in seen_sources:
            continue
        if source and source not in source_text and not int(term.get("locked") or 0):
            continue
        line_len = len(source) + len(target) + 8
        if selected and used_chars + line_len > max_chars:
            continue
        selected.append(term)
        seen_sources.add(source)
        used_chars += line_len
        if len(selected) >= max_terms:
            break
    return selected


def set_glossary_term_locked(db_path: Path, term_id: int, locked: bool) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE glossary_terms
            SET locked = ?,
                review_status = CASE
                    WHEN ? = 1 THEN 'LOCKED'
                    WHEN approved = 1 THEN 'APPROVED'
                    WHEN approved < 0 THEN 'REJECTED'
                    ELSE 'NEEDS_REVIEW'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if locked else 0, 1 if locked else 0, term_id),
        )
        conn.commit()
        return cur.rowcount > 0


def load_glossary_by_mode(db_path: Path, book_id: int = 0, mode: str = "translate") -> dict[str, str]:
    """Load glossary filtered by mode (translate/context/transliterate)."""
    glossary: dict[str, str] = {}
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT source_term, target_term, variants FROM glossary_terms
            WHERE book_id IN (0, ?) AND approved = 1 AND mode = ?
            ORDER BY book_id ASC, priority DESC, LENGTH(source_term) DESC
            """,
            (book_id, mode),
        ).fetchall()
        for src, tgt, variants in rows:
            glossary[src] = tgt
            for variant in _split_glossary_variants(variants):
                glossary.setdefault(variant, tgt)
    return glossary


def load_glossary_names(db_path: Path, book_id: int = 0) -> dict[str, str]:
    """Load transliteration / name map for use in the translation prompt.

    Includes all name-related categories:
    - ho_ten_pho_bien: common Vietnamese names
    - pntt_ten_rieng: book-specific character names (e.g. Phàm Nhân Tu Tiên)
    - Any term with mode='transliterate'
    """
    glossary: dict[str, str] = {}
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT source_term, target_term, variants FROM glossary_terms
            WHERE book_id IN (0, ?) AND approved = 1
              AND (category IN ('ho_ten_pho_bien', 'pntt_ten_rieng')
                   OR mode = 'transliterate')
            ORDER BY book_id ASC, priority DESC, LENGTH(source_term) DESC
            """,
            (book_id,),
        ).fetchall()
        for src, tgt, variants in rows:
            glossary[src] = tgt
            for variant in _split_glossary_variants(variants):
                glossary.setdefault(variant, tgt)
    return glossary


# ── Summaries ──────────────────────────────────────────────────────────────

def save_summary(db_path: Path, chapter_id: int, summary: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chapter_summaries (chapter_id, summary) VALUES (?, ?)",
            (chapter_id, summary),
        )
        conn.commit()


def get_last_summary(db_path: Path, book_id: int) -> Optional[str]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT cs.summary FROM chapter_summaries cs
               JOIN chapters c ON cs.chapter_id = c.id
               WHERE c.book_id = ?
               ORDER BY c.chapter_number DESC LIMIT 1""",
            (book_id,),
        ).fetchone()
        return row[0] if row else None


# ── Glossary Audit / Review ──────────────────────────────────────────────────


def glossary_stats(db_path: Path, book_id: Optional[int] = None) -> dict:
    """Return summary stats about the glossary library.

    Returns dict with: total, translate, transliterate, context, no_mode,
    approved, pending_approval, categories, has_pinyin, has_notes, has_variants.
    """
    with get_connection(db_path) as conn:
        where = "WHERE book_id IN (0, ?)" if book_id is not None else "WHERE 1=1"
        params = (book_id,) if book_id is not None else ()

        # Single query with GROUP BY to get all counts at once
        rows = conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN mode = 'translate' THEN 1 ELSE 0 END) as translate,
                SUM(CASE WHEN mode = 'transliterate' THEN 1 ELSE 0 END) as transliterate,
                SUM(CASE WHEN mode = 'context' THEN 1 ELSE 0 END) as context,
                SUM(CASE WHEN mode IS NULL OR mode = '' THEN 1 ELSE 0 END) as no_mode,
                SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as pending_approval,
                COUNT(DISTINCT category) as categories,
                SUM(CASE WHEN pinyin != '' THEN 1 ELSE 0 END) as has_pinyin,
                SUM(CASE WHEN notes_vi != '' THEN 1 ELSE 0 END) as has_notes,
                SUM(CASE WHEN variants != '' THEN 1 ELSE 0 END) as has_variants,
                COUNT(DISTINCT source_term) as unique_source
            FROM glossary_terms {where}
            """,
            params
        ).fetchone()

    return dict(
        total=rows["total"],
        translate=rows["translate"],
        transliterate=rows["transliterate"],
        context=rows["context"],
        no_mode=rows["no_mode"],
        approved=rows["approved"],
        pending_approval=rows["pending_approval"],
        categories=rows["categories"],
        has_pinyin=rows["has_pinyin"],
        has_notes=rows["has_notes"],
        has_variants=rows["has_variants"],
        unique_source=rows["unique_source"],
    )


def get_glossary_pending(db_path: Path, book_id: Optional[int] = None, limit: int = 20) -> list[dict]:
    """Get pending (unapproved) glossary terms for review."""
    with get_connection(db_path) as conn:
        if book_id is not None:
            rows = conn.execute(
                """SELECT id, book_id, source_term, target_term, category, mode,
                          pinyin, notes_vi, variants, created_at
                   FROM glossary_terms
                   WHERE book_id IN (0, ?) AND approved = 0
                   ORDER BY created_at ASC LIMIT ?""",
                (book_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, book_id, source_term, target_term, category, mode,
                          pinyin, notes_vi, variants, created_at
                   FROM glossary_terms WHERE approved = 0
                   ORDER BY created_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def approve_glossary_term(db_path: Path, term_id: int) -> bool:
    """Approve a pending glossary term. Returns True if row existed."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE glossary_terms
            SET approved = 1,
                review_status = CASE WHEN locked = 1 THEN 'LOCKED' ELSE 'APPROVED' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND approved = 0
            """,
            (term_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def reject_glossary_term(db_path: Path, term_id: int) -> bool:
    """Mark a non-locked term rejected while retaining review history."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE glossary_terms
            SET approved = -1,
                review_status = 'REJECTED',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND locked = 0
            """,
            (term_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_glossary_term(db_path: Path, term_id: int) -> bool:
    """Hard-delete a glossary term for explicit delete actions."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM glossary_terms WHERE id = ?", (term_id,))
        conn.commit()
        return cur.rowcount > 0


def set_glossary_term_mode(db_path: Path, term_id: int, mode: str) -> bool:
    """Update the mode of a glossary term. Returns True if row existed."""
    valid_modes = {"translate", "context", "transliterate"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE glossary_terms SET mode = ? WHERE id = ?",
            (mode, term_id),
        )
        conn.commit()
        return cur.rowcount > 0


def glossary_coverage(db_path: Path, book_id: int, source_text: str) -> dict:
    """Analyze how well the glossary covers a given text.

    Returns:
        hits: list of (source_term, target_term) for each matched term
        misses: list of source terms NOT matched but worth checking
        covered_chars: count of source chars covered by matched terms
        total_chars: total chars in source text
        coverage_pct: percentage of text covered by glossary terms
    """
    glossary = load_glossary(db_path, book_id)
    names = load_glossary_names(db_path, book_id)
    all_terms = {**glossary, **names}

    hits = []
    matched_spans: list[tuple[int, int]] = []
    for src, tgt in sorted(all_terms.items(), key=lambda x: -len(x[0])):
        start = source_text.find(src)
        if start != -1:
            hits.append((src, tgt))
        while start != -1:
            matched_spans.append((start, start + len(src)))
            start = source_text.find(src, start + 1)

    covered_chars = 0
    current_end = -1
    for start, end in sorted(matched_spans):
        if end <= current_end:
            continue
        covered_chars += end - max(start, current_end)
        current_end = end

    return dict(
        hits=hits,
        matched_count=len(hits),
        covered_chars=covered_chars,
        total_chars=len(source_text),
        coverage_pct=round(covered_chars / len(source_text) * 100, 1) if source_text else 0,
    )


def auto_approve_glossary(db_path: Path, min_occurrences: int = 3, book_id: Optional[int] = None) -> int:
    """Auto-approve pending terms that have been seen multiple times.

    A term seen 3+ times across translations is likely correct.
    Returns count of auto-approved terms.
    """
    with get_connection(db_path) as conn:
        if book_id is not None:
            cur = conn.execute(
                """UPDATE glossary_terms SET approved = 1, mode = COALESCE(NULLIF(mode,''), 'translate')
                   WHERE approved = 0 AND occurrence_count >= ? AND book_id IN (0, ?)""",
                (min_occurrences, book_id),
            )
        else:
            cur = conn.execute(
                """UPDATE glossary_terms SET approved = 1, mode = COALESCE(NULLIF(mode,''), 'translate')
                   WHERE approved = 0 AND occurrence_count >= ?""",
                (min_occurrences,),
            )
        conn.commit()
        return cur.rowcount


def get_glossary_conflicts(db_path: Path, book_id: Optional[int] = None) -> list[dict]:
    """Find source/target conflicts for glossary review.

    Returns source conflicts and target reuse conflicts. Rejected rows are ignored.
    """
    with get_connection(db_path) as conn:
        where = "WHERE book_id IN (0, ?) AND approved >= 0" if book_id is not None else "WHERE approved >= 0"
        params = (book_id,) if book_id is not None else ()
        # Find source_terms with multiple distinct targets
        rows = conn.execute(
            f"""SELECT source_term, COUNT(DISTINCT target_term) as tgt_count
                FROM glossary_terms {where}
                GROUP BY source_term
                HAVING tgt_count > 1
                ORDER BY tgt_count DESC""",
            params,
        ).fetchall()
        conflicts = []
        for row in rows:
            src = row[0]
            detail_rows = conn.execute(
                """SELECT book_id, target_term, approved, mode FROM glossary_terms
                   WHERE source_term = ?
                   ORDER BY book_id""",
                (src,),
            ).fetchall()
            targets = [dict(book_id=r[0], target_term=r[1], approved=r[2], mode=r[3]) for r in detail_rows]
            conflicts.append(dict(type="source_conflict", source_term=src, targets=targets))
        target_rows = conn.execute(
            f"""SELECT target_term, COUNT(DISTINCT source_term) as source_count
                FROM glossary_terms {where}
                  AND target_term != ''
                  AND COALESCE(term_type, category, '') IN
                      ('character', 'sect', 'realm', 'skill', 'artifact', 'location', 'title',
                       'cultivation', 'organization', 'place', 'CHARACTER', 'SECT', 'REALM',
                       'SKILL', 'ARTIFACT', 'LOCATION', 'TITLE', 'CULTIVATION', 'ORGANIZATION', 'PLACE')
                GROUP BY target_term
                HAVING source_count > 1
                ORDER BY source_count DESC""",
            params,
        ).fetchall()
        for row in target_rows:
            target = row[0]
            source_rows = conn.execute(
                """SELECT book_id, source_term, approved, mode, term_type, locked
                   FROM glossary_terms
                   WHERE target_term = ? AND approved >= 0
                   ORDER BY locked DESC, book_id DESC, source_term""",
                (target,),
            ).fetchall()
            conflicts.append(
                dict(
                    type="target_reuse",
                    target_term=target,
                    sources=[dict(r) for r in source_rows],
                )
            )
        return conflicts


# --- Fuzzy Translation Memory ---

def _dice_coefficient(a_set: set[str], b_set: set[str]) -> int:
    """Return similarity percentage 0-100 using Dice coefficient."""
    if not a_set and not b_set:
        return 0
    intersection = len(a_set & b_set)
    return int(2.0 * intersection / (len(a_set) + len(b_set)) * 100)


def _tokenize_chinese(text: str) -> set[str]:
    """Tokenize Chinese text into a set of terms for fuzzy matching.
    Tries to use jieba if available, otherwise falls back to character bigrams.
    """
    try:
        import jieba
        # jieba.lcut returns list of words
        return set(jieba.lcut(text))
    except Exception:
        # Fallback: character bigrams (better than single chars for Chinese)
        if len(text) < 2:
            return set(text)
        return {text[i:i+2] for i in range(len(text)-1)}


def add_fuzzy_tm_entry(
    db_path: Path,
    source_text: str,
    translation_text: str,
    score: int = 85,
    *,
    book_id: int = 0,
    chapter_number: int | None = None,
    source_lang: str = "zh",
    target_lang: str = "vi",
) -> int:
    """Add or update an entry in the fuzzy translation memory.
    If the source_text already exists (by hash), replace if the new score is higher.
    """
    import hashlib
    source_hash = hashlib.sha256(source_text.encode('utf-8')).hexdigest()
    tokens = ' '.join(sorted(_tokenize_chinese(source_text)))  # sort for consistent storage
    with get_connection(db_path) as conn:
        # Try to insert; if conflict on source_hash, keep the higher score entry
        try:
            conn.execute(
                """
                INSERT INTO tm_fuzzy
                    (source_hash, source_text, translation_text, source_tokens, score,
                     source_lang, target_lang, book_id, chapter_number, usage_count, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(source_hash) DO UPDATE SET
                    source_text = excluded.source_text,
                    translation_text = excluded.translation_text,
                    source_tokens = excluded.source_tokens,
                    score = MAX(excluded.score, tm_fuzzy.score),
                    source_lang = excluded.source_lang,
                    target_lang = excluded.target_lang,
                    book_id = excluded.book_id,
                    chapter_number = excluded.chapter_number,
                    usage_count = tm_fuzzy.usage_count + 1,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (
                    source_hash,
                    source_text,
                    translation_text,
                    tokens,
                    score,
                    source_lang,
                    target_lang,
                    book_id,
                    chapter_number,
                ),
            )
            row = conn.execute("SELECT id FROM tm_fuzzy WHERE source_hash = ?", (source_hash,)).fetchone()
        except sqlite3.OperationalError:
            # Old DB without tm_fuzzy; skip gracefully.
            return 0
        conn.commit()
        return int(row["id"]) if row else 0


def search_fuzzy_tm(
    db_path: Path,
    source_text: str,
    threshold: int = 80,
    limit: int = 10,
    *,
    source_lang: str = "zh",
    target_lang: str = "vi",
    book_id: int | None = None,
) -> list[dict]:
    """Search fuzzy translation memory and return ranked match metadata."""
    if not source_text.strip() or limit <= 0:
        return []

    query_set = _tokenize_chinese(source_text)
    params: list[object] = [source_lang, target_lang]
    book_filter = ""
    if book_id is not None:
        book_filter = "AND book_id IN (0, ?)"
        params.append(book_id)

    with get_connection(db_path) as conn:
        try:
            rows = conn.execute(
                f"""
                SELECT id, source_text, translation_text, source_tokens, score,
                       source_lang, target_lang, book_id, chapter_number,
                       usage_count, last_seen, created_at
                FROM tm_fuzzy
                WHERE source_lang = ? AND target_lang = ? {book_filter}
                ORDER BY usage_count DESC, last_seen DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    matches: list[dict] = []
    for row in rows:
        candidate_text = row["source_text"]
        if not candidate_text:
            continue
        candidate_set = set((row["source_tokens"] or "").split()) or _tokenize_chinese(candidate_text)
        match_score = 100 if candidate_text == source_text else _dice_coefficient(query_set, candidate_set)
        if match_score < threshold:
            continue
        matches.append(
            {
                "id": row["id"],
                "source_text": candidate_text,
                "translation_text": row["translation_text"],
                "match_score": match_score,
                "stored_score": row["score"],
                "source_lang": row["source_lang"],
                "target_lang": row["target_lang"],
                "book_id": row["book_id"],
                "chapter_number": row["chapter_number"],
                "usage_count": row["usage_count"],
                "last_seen": row["last_seen"],
                "created_at": row["created_at"],
            }
        )

    matches.sort(
        key=lambda item: (
            item["match_score"],
            item["stored_score"],
            item["usage_count"],
            item["last_seen"] or "",
        ),
        reverse=True,
    )
    return matches[:limit]


def get_fuzzy_tm_match(
    db_path: Path,
    source_text: str,
    threshold: int = 80,
) -> Optional[str]:
    """Return a fuzzy matching translation if similarity >= threshold, else None.
    Uses Dice coefficient on token sets.
    """
    matches = search_fuzzy_tm(db_path, source_text, threshold=threshold, limit=1)
    return matches[0]["translation_text"] if matches else None


def fuzzy_tm_usage_increment(db_path: Path, source_text: str) -> None:
    """Increment usage_count for a fuzzy TM entry (called when used)."""
    import hashlib
    source_hash = hashlib.sha256(source_text.encode('utf-8')).hexdigest()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE tm_fuzzy
            SET usage_count = usage_count + 1, last_seen = CURRENT_TIMESTAMP
            WHERE source_hash = ?
            """,
            (source_hash,),
        )
        conn.commit()


def clear_fuzzy_tm(db_path: Path) -> int:
    """Clear all fuzzy TM entries. Returns count deleted."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM tm_fuzzy")
        conn.commit()
        return cur.rowcount


def get_low_coverage_chapters(db_path: Path, book_id: int, threshold: float = 30.0) -> list[dict]:
    """Find chapters with glossary coverage below threshold.

    Scans raw text of all imported chapters for the book.
    Returns list of dicts: chapter_number, title, coverage_pct, matched_count, total_chars.
    """
    chapters = list_chapters(db_path, book_id)
    results = []
    for ch in chapters:
        raw_path = ch.get("raw_text_path")
        if not raw_path or not Path(raw_path).exists():
            continue
        try:
            source_text = Path(raw_path).read_text(encoding="utf-8")
        except Exception:
            continue
        cov = glossary_coverage(db_path, book_id, source_text)
        if cov["coverage_pct"] < threshold:
            results.append(dict(
                chapter_number=ch["chapter_number"],
                title=ch["title"],
                coverage_pct=cov["coverage_pct"],
                matched_count=cov["matched_count"],
                total_chars=cov["total_chars"],
            ))
    return results


# ── QA Reports ──────────────────────────────────────────────────────────────

def save_qa_report(
    db_path: Path,
    book_id: int,
    chapter_id: int,
    quality_score: float,
    fidelity_score: float,
    style_score: float,
    glossary_score: float,
    audiobook_score: float,
    verdict: str,
    report_json: str,
    job_id: str = "",
    overall_status: str = "NOT_RUN",
    missing_paragraph_warning: bool = False,
    chinese_leakage_count: int = 0,
    name_consistency_status: str = "NOT_RUN",
    term_consistency_status: str = "NOT_RUN",
    length_ratio: float = 0,
    repetition_warning: bool = False,
    style_warnings: str | list | None = None,
    glossary_violations: str | list | None = None,
    suggested_fixes: str | list | None = None,
) -> int:
    """Save a QA report, replacing any existing report for this chapter."""
    def _json_text(value: str | list | None) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value or [], ensure_ascii=False)

    with get_connection(db_path) as conn:
        # Delete existing report for this chapter
        conn.execute("DELETE FROM qa_reports WHERE chapter_id = ?", (chapter_id,))
        cur = conn.execute(
            """INSERT INTO qa_reports
               (book_id, chapter_id, quality_score, fidelity_score, style_score,
                glossary_score, audiobook_score, verdict, job_id, overall_status,
                missing_paragraph_warning, chinese_leakage_count, name_consistency_status,
                term_consistency_status, length_ratio, repetition_warning, style_warnings,
                glossary_violations, suggested_fixes, report_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (book_id, chapter_id, quality_score, fidelity_score, style_score,
             glossary_score, audiobook_score, verdict, job_id, overall_status,
             1 if missing_paragraph_warning else 0, int(chinese_leakage_count or 0),
             name_consistency_status, term_consistency_status, float(length_ratio or 0),
             1 if repetition_warning else 0, _json_text(style_warnings),
             _json_text(glossary_violations), _json_text(suggested_fixes), report_json),
        )
        conn.commit()
        return cur.lastrowid


def get_qa_report(db_path: Path, book_id: int, chapter_id: int) -> Optional[dict]:
    """Retrieve the latest QA report for a chapter."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM qa_reports
               WHERE chapter_id = ? AND (book_id = 0 OR book_id = ?)
               ORDER BY created_at DESC LIMIT 1""",
            (chapter_id, book_id),
        ).fetchone()
        return dict(row) if row else None


def list_qa_reports(db_path: Path, book_id: int) -> list[dict]:
    """List all QA reports for chapters in a book."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT qr.* FROM qa_reports qr
               JOIN chapters c ON qr.chapter_id = c.id
               WHERE c.book_id = ?
               ORDER BY c.chapter_number ASC""",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Translation Suggestions (for glossary auto-improve) ───────────────────────


def add_translation_suggestion(
    db_path: Path,
    q: str,
    s: str,
    source_lang: str = "zh",
    target_lang: str = "vi",
    book_id: Optional[int] = None,
    chapter_number: Optional[int] = None,
) -> None:
    """Store a user-submitted translation suggestion."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO translation_suggestions
               (q, s, source_lang, target_lang, book_id, chapter_number)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (q, s, source_lang, target_lang, book_id, chapter_number),
        )
        conn.commit()


def get_translation_suggestions(
    db_path: Path, limit: int = 50, book_id: Optional[int] = None
) -> list[dict]:
    """List pending translation suggestions for review."""
    with get_connection(db_path) as conn:
        if book_id is not None:
            rows = conn.execute(
                """SELECT id, q, s, source_lang, target_lang, book_id, chapter_number, created_at
                   FROM translation_suggestions WHERE book_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (book_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, q, s, source_lang, target_lang, book_id, chapter_number, created_at
                   FROM translation_suggestions ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def delete_translation_suggestion(db_path: Path, suggestion_id: int) -> bool:
    """Delete a suggestion. Returns True if deleted."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM translation_suggestions WHERE id = ?", (suggestion_id,)
        )
        conn.commit()
        return cur.rowcount > 0
