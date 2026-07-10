from __future__ import annotations

import gzip
import sqlite3
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.main as main_mod
from app.database.db import CURRENT_SCHEMA_VERSION, init_db
from app.translation.cache import _make_cache_key, get_cached_translation


def test_init_db_migrates_existing_translation_cache_without_expiry(tmp_path: Path) -> None:
    db_path = tmp_path / "old-cache.db"
    source = "测试文本"
    target = "Bản dịch cũ"
    model = "test-model"
    cache_key = _make_cache_key(source, "zh", "vi", model)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                source TEXT DEFAULT 'manual',
                source_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, source_term)
            );
            CREATE TABLE translation_cache (
                cache_key TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            "INSERT INTO translation_cache (cache_key, content, created_at) VALUES (?, ?, ?)",
            (cache_key, gzip.compress(target.encode("utf-8")), "2026-01-01 00:00:00"),
        )
        conn.commit()

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT expiry_ts, typeof(expiry_ts) FROM translation_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert row is not None
    assert row[1] in {"integer", "real"}
    assert float(row[0]) > time.time()
    assert migration == (CURRENT_SCHEMA_VERSION,)
    assert get_cached_translation(db_path, source, "zh", "vi", model) == target


def test_cli_init_records_current_schema_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main_mod.settings, "data_dir", tmp_path / "runtime-data")

    result = runner.invoke(main_mod.app, ["init"])

    assert result.exit_code == 0

    with sqlite3.connect(tmp_path / "runtime-data" / "pipeline.db") as conn:
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert migration == (CURRENT_SCHEMA_VERSION,)
    assert not Path("data/pipeline.db").exists()
