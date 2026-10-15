"""Import identities, receipts and chapter writes in the caller-owned transaction."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.database.chapter_repository import update_chapter_with_connection
from app.database.connection import get_connection
from app.database.json_fields import decode_json_field as _decode_json_field
from app.database.user_repository import _resolve_owner_user_id_for_write
from app.security.url_policy import validate_fetch_url

@dataclass(frozen=True)
class ImportChapterUpsert:
    chapter_id: int
    operation: str
    content_hash: str
    content_revision: int
    raw_text_path: str



def canonicalize_import_url(url: str) -> str:
    """Canonicalize a persisted source identity through the P02 URL policy.

    Resolution is deliberately omitted here: URLs have already passed the fetch
    policy before import, while migrations must never perform network I/O.
    """
    value = str(url or "").strip()
    if not value:
        return ""
    return validate_fetch_url(value, resolver=None).canonical_url



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
    update_chapter_with_connection(
        conn, chapter_id, title=title, status=status,
        raw_text_path=raw_text_path, translated_text_path=translated_text_path,
    )



def _active_chapter_by_canonical_identity(
    conn: sqlite3.Connection,
    *,
    book_id: int,
    adapter_id: str,
    canonical_chapter_url: str,
) -> sqlite3.Row | None:
    if not adapter_id or not canonical_chapter_url:
        return None
    return conn.execute(
        """
        SELECT * FROM chapters
        WHERE book_id = ?
          AND adapter_id = ?
          AND canonical_chapter_url = ?
          AND deleted_at IS NULL
        LIMIT 1
        """,
        (book_id, adapter_id, canonical_chapter_url),
    ).fetchone()



def upsert_import_chapter_with_connection(
    conn: sqlite3.Connection,
    *,
    book_id: int,
    chapter_number: int,
    title: str,
    source_url: str,
    canonical_chapter_url: str,
    adapter_id: str,
    raw_text_path: Path,
    content_hash: str,
    source_updated_at: str,
) -> ImportChapterUpsert:
    """Store one sourced chapter using canonical URL identity.

    A canonical identity is only available for source-backed imports.  Manual
    pastes intentionally keep the existing chapter-number duplicate behavior.
    The caller owns the surrounding transaction and artifact cleanup.
    """
    existing = _active_chapter_by_canonical_identity(
        conn,
        book_id=book_id,
        adapter_id=adapter_id,
        canonical_chapter_url=canonical_chapter_url,
    )
    if existing is not None:
        existing_hash = str(existing["content_hash"] or existing["source_hash"] or "")
        if existing_hash == content_hash:
            conn.execute(
                "UPDATE chapters SET last_import_operation = 'skipped_duplicate' WHERE id = ?",
                (existing["id"],),
            )
            return ImportChapterUpsert(
                chapter_id=int(existing["id"]),
                operation="skipped_duplicate",
                content_hash=existing_hash,
                content_revision=max(1, int(existing["content_revision"] or 1)),
                raw_text_path=str(existing["raw_text_path"] or ""),
            )

        next_revision = max(1, int(existing["content_revision"] or 1)) + 1
        conn.execute(
            """
            UPDATE chapters
            SET chapter_number = ?, title = ?, source_url = ?,
                canonical_chapter_url = ?, adapter_id = ?, raw_text_path = ?,
                source_hash = ?, content_hash = ?, source_updated_at = ?,
                last_import_operation = 'updated', content_revision = ?,
                audio_invalidated_at = CURRENT_TIMESTAMP, quality_status = 'stale'
            WHERE id = ?
            """,
            (
                chapter_number,
                title,
                source_url,
                canonical_chapter_url,
                adapter_id,
                str(raw_text_path),
                content_hash,
                content_hash,
                source_updated_at,
                next_revision,
                existing["id"],
            ),
        )
        conn.execute("UPDATE qa_reports SET overall_status = 'STALE' WHERE chapter_id = ?", (existing["id"],))
        return ImportChapterUpsert(
            chapter_id=int(existing["id"]),
            operation="updated",
            content_hash=content_hash,
            content_revision=next_revision,
            raw_text_path=str(raw_text_path),
        )

    if not canonical_chapter_url:
        duplicate_number = conn.execute(
            """
            SELECT id FROM chapters
            WHERE book_id = ? AND chapter_number = ? AND deleted_at IS NULL
            LIMIT 1
            """,
            (book_id, chapter_number),
        ).fetchone()
        if duplicate_number is not None:
            raise ValueError(f"Duplicate chapter number {chapter_number} for book {book_id}")

    try:
        cursor = conn.execute(
            """
            INSERT INTO chapters (
                book_id, chapter_number, title, source_url, canonical_chapter_url,
                adapter_id, raw_text_path, source_hash, content_hash,
                source_updated_at, last_import_operation, content_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', 1)
            """,
            (
                book_id,
                chapter_number,
                title,
                source_url,
                canonical_chapter_url,
                adapter_id,
                str(raw_text_path),
                content_hash,
                content_hash,
                source_updated_at,
            ),
        )
    except sqlite3.IntegrityError:
        # A concurrent import can win after this transaction has started.
        # Re-read the identity and return its idempotent outcome instead of a 500.
        existing = _active_chapter_by_canonical_identity(
            conn,
            book_id=book_id,
            adapter_id=adapter_id,
            canonical_chapter_url=canonical_chapter_url,
        )
        if existing is None:
            raise
        existing_hash = str(existing["content_hash"] or existing["source_hash"] or "")
        if existing_hash == content_hash:
            return ImportChapterUpsert(
                chapter_id=int(existing["id"]),
                operation="skipped_duplicate",
                content_hash=existing_hash,
                content_revision=max(1, int(existing["content_revision"] or 1)),
                raw_text_path=str(existing["raw_text_path"] or ""),
            )
        next_revision = max(1, int(existing["content_revision"] or 1)) + 1
        conn.execute(
            """
            UPDATE chapters
            SET chapter_number = ?, title = ?, source_url = ?, raw_text_path = ?,
                source_hash = ?, content_hash = ?, source_updated_at = ?,
                last_import_operation = 'updated', content_revision = ?
            WHERE id = ?
            """,
            (
                chapter_number,
                title,
                source_url,
                str(raw_text_path),
                content_hash,
                content_hash,
                source_updated_at,
                next_revision,
                existing["id"],
            ),
        )
        return ImportChapterUpsert(
            chapter_id=int(existing["id"]),
            operation="updated",
            content_hash=content_hash,
            content_revision=next_revision,
            raw_text_path=str(raw_text_path),
        )

    return ImportChapterUpsert(
        chapter_id=int(cursor.lastrowid),
        operation="created",
        content_hash=content_hash,
        content_revision=1,
        raw_text_path=str(raw_text_path),
    )



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

