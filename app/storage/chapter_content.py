"""Immutable chapter artifacts: publish database pointers before retiring files."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
import tempfile
import uuid

from app.database.db import get_chapter_by_id, update_chapter_paths
from app.database.connection import get_connection

logger = logging.getLogger(__name__)


def write_versioned_text(directory: Path, prefix: str, text: str, *, suffix: str = ".txt") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{prefix}_{uuid.uuid4().hex}{suffix}"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def retire_artifact(value: str | Path | None, data_dir: Path, db_path: Path | None = None) -> None:
    if not value:
        return
    path = Path(value)
    if not path.resolve().is_relative_to(data_dir.resolve()):
        return
    try:
        if db_path is not None:
            with get_connection(db_path) as conn:
                for candidate in (str(path), str(path.resolve()), str(path.resolve().relative_to(data_dir.resolve()))):
                    if conn.execute("""SELECT 1 FROM chapters WHERE deleted_at IS NULL AND
                        ? IN (raw_text_path, cleaned_text_path, translated_text_path, content_html_path, audio_path)
                        LIMIT 1""", (candidate,)).fetchone():
                        return
        path.unlink(missing_ok=True)
    except (OSError, sqlite3.Error):
        logger.warning("Committed chapter content; retired artifact cleanup deferred")


def publish_translation(db_path: Path, data_dir: Path, chapter_id: int, text: str, **options) -> Path | None:
    if not text.strip():
        raise ValueError("Translation text is empty")
    chapter = get_chapter_by_id(db_path, chapter_id)
    if chapter is None:
        return None
    options.setdefault("expected_content_revision", chapter["content_revision"])
    previous = chapter.get("translated_text_path")
    if previous and Path(previous).is_file() and Path(previous).read_text(encoding="utf-8") == text:
        update_chapter_paths(db_path, chapter_id, **options)
        return Path(previous)
    path = write_versioned_text(data_dir / "translated", f"chapter_{chapter_id}", text)
    try:
        update_chapter_paths(
            db_path, chapter_id, translated_text_path=path,
            clear_content_html_path=True, status="translated", **options,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    retire_artifact(chapter.get("translated_text_path"), data_dir, db_path)
    retire_artifact(chapter.get("content_html_path"), data_dir, db_path)
    return path
