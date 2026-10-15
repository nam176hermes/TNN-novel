"""Book queries, metadata, merges and transactional import book resolution."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.database.connection import get_connection
from app.database.schema_utils import _table_exists
from app.database.user_repository import _resolve_owner_user_id_for_write, _seed_operator_user_from_env
from app.ingestion.import_metadata import normalize_book_key

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
                    SUM(CASE WHEN COALESCE(audio_path, '') != '' AND audio_invalidated_at IS NULL
                        AND (audio_translation_hash IS NULL OR translation_hash IS NULL OR audio_translation_hash = translation_hash)
                        THEN 1 ELSE 0 END) AS audio_chapters,
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
    source_url: str = "",
    canonical_source_url: str = "",
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
        if source_url and not str(book.get("source_url") or ""):
            updates.append("source_url = ?")
            params.append(source_url)
        if canonical_source_url and not str(book.get("canonical_source_url") or ""):
            updates.append("canonical_source_url = ?")
            params.append(canonical_source_url)
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
        INSERT INTO books (
            title, book_key, owner_user_id, author, source, source_url, canonical_source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            normalize_book_key(title),
            owner_user_id,
            author,
            source,
            source_url,
            canonical_source_url,
        ),
    )
    row = conn.execute("SELECT * FROM books WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)

