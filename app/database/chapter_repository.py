"""Chapter revisions and artifact pointers, updated in the caller's transaction."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from app.database.connection import get_connection


class ContentRevisionConflict(ValueError):
    def __init__(self):
        super().__init__("Chapter content revision has changed")


def file_digest(value: str | Path | None) -> str | None:
    if not value:
        return None
    try:
        with Path(value).open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def chapter_view(row) -> dict:
    chapter = dict(row)
    chapter["quality_status"] = chapter.get("quality_status") or "legacy_unverified"
    chapter["audio_version"] = hashlib.sha256(str(chapter["audio_path"]).encode()).hexdigest()[:16] if chapter.get("audio_path") else ""
    if not chapter.get("translated_text_path"):
        chapter["quality_status"] = "unreviewed"
    if not chapter.get("audio_path"):
        chapter["audio_status"] = "missing"
    elif chapter.get("audio_invalidated_at"):
        chapter["audio_status"] = "stale"
    elif not chapter.get("audio_translation_hash") or not chapter.get("translation_hash"):
        chapter["audio_status"] = "legacy_unverified"
    elif chapter["audio_translation_hash"] == chapter["translation_hash"]:
        chapter["audio_status"] = "ready"
    else:
        chapter["audio_status"] = "stale"
    return chapter


def update_chapter_with_connection(
    conn: sqlite3.Connection, chapter_id: int, *, title=None, translated_title=None,
    raw_text_path=None, cleaned_text_path=None, translated_text_path=None,
    content_html_path=None, clear_content_html_path=False, audio_path=None, status=None,
    expected_content_revision=None, expected_translation_hash=None, qa_report=None, publication_job_id=None,
) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM chapters WHERE id = ? AND deleted_at IS NULL", (chapter_id,)).fetchone()
    if row is None:
        raise ValueError("Chapter not found")
    revision = int(row["content_revision"] or 1)
    if expected_content_revision is not None and revision != expected_content_revision:
        raise ContentRevisionConflict()
    previous_hash = row["translation_hash"] or file_digest(row["translated_text_path"])
    if expected_translation_hash is not None and previous_hash != expected_translation_hash:
        raise ContentRevisionConflict()
    if audio_path is not None and expected_translation_hash is not None and file_digest(row["translated_text_path"]) != expected_translation_hash:
        raise ContentRevisionConflict()
    if publication_job_id:
        job = conn.execute("SELECT status, chapter_id FROM tts_jobs WHERE id = ?", (publication_job_id,)).fetchone()
        if not job or job["chapter_id"] != chapter_id or job["status"] == "cancelled":
            raise ValueError("TTS publication cancelled")
    fields = {}
    for name, value in (
        ("title", title), ("translated_title", translated_title), ("raw_text_path", raw_text_path),
        ("cleaned_text_path", cleaned_text_path), ("translated_text_path", translated_text_path),
        ("content_html_path", content_html_path), ("audio_path", audio_path), ("status", status),
    ):
        if value is not None:
            fields[name] = str(value)
    changed = False
    if translated_text_path is not None:
        digest = file_digest(translated_text_path)
        fields["translation_hash"] = digest
        changed = digest != previous_hash if digest else str(translated_text_path) != str(row["translated_text_path"])
    if raw_text_path is not None:
        old_digest = row["content_hash"] or row["source_hash"] or file_digest(row["raw_text_path"])
        digest = file_digest(raw_text_path)
        source_changed = digest != old_digest if digest else str(raw_text_path) != str(row["raw_text_path"])
        changed = changed or source_changed
        if source_changed and cleaned_text_path is None:
            fields["cleaned_text_path"] = None
        if digest:
            fields.update(content_hash=digest, source_hash=digest)
    if cleaned_text_path is not None:
        old_digest = file_digest(row["cleaned_text_path"] or row["raw_text_path"])
        digest = file_digest(cleaned_text_path)
        changed = changed or (digest != old_digest if digest else str(cleaned_text_path) != str(row["cleaned_text_path"]))
    if clear_content_html_path:
        fields["content_html_path"] = None
    if changed:
        fields["content_revision"] = revision + 1
        fields["quality_status"] = "stale" if conn.execute(
            "SELECT 1 FROM qa_reports WHERE chapter_id = ? LIMIT 1", (chapter_id,),
        ).fetchone() else "unreviewed"
        conn.execute("UPDATE qa_reports SET overall_status = 'STALE' WHERE chapter_id = ?", (chapter_id,))
    clauses = [f"{key} = ?" for key in fields]
    if changed:
        clauses.append("audio_invalidated_at = CURRENT_TIMESTAMP")
    if translated_text_path is not None:
        clauses.append("translated_at = CURRENT_TIMESTAMP")
    if audio_path is not None:
        clauses.extend(["audio_created_at = CURRENT_TIMESTAMP", "audio_invalidated_at = NULL", "audio_translation_hash = ?"])
    parameters = list(fields.values())
    if audio_path is not None:
        parameters.append(expected_translation_hash)
    if clauses:
        conn.execute(f"UPDATE chapters SET {', '.join(clauses)} WHERE id = ?", (*parameters, chapter_id))
    if publication_job_id:
        conn.execute("""UPDATE tts_jobs SET status = 'completed', progress = 100,
            output_mp3_path = ?, error_message = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (str(audio_path), publication_job_id))
    if qa_report is not None:
        import json
        from app.database.qa_repository import save_qa_report_with_connection
        qa_report.setdefault("provenance", {}).update(content_revision=revision + int(changed),
                                                      translation_hash=fields.get("translation_hash", previous_hash))
        save_qa_report_with_connection(
            conn, book_id=row["book_id"], chapter_id=chapter_id,
            report_json=json.dumps(qa_report, ensure_ascii=False),
            content_revision=revision + int(changed), job_id=qa_report.get("job_id", ""),
            quality_score=qa_report.get("quality_score", 0), fidelity_score=qa_report.get("fidelity_score", 0),
            style_score=qa_report.get("style_score", 0), glossary_score=qa_report.get("glossary_score", 0),
            audiobook_score=qa_report.get("audiobook_score", 0), verdict=qa_report.get("verdict", "UNKNOWN"),
        )


def update_chapter_paths(db_path: Path, chapter_id: int, **options) -> None:
    with get_connection(db_path) as conn:
        update_chapter_with_connection(conn, chapter_id, **options)
        conn.commit()


def get_chapter(db_path: Path, book_id: int, chapter_number: int) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM chapters WHERE book_id = ? AND chapter_number = ? AND deleted_at IS NULL",
                           (book_id, chapter_number)).fetchone()
        return chapter_view(row) if row else None


def get_chapter_by_id(db_path: Path, chapter_id: int, include_deleted: bool = False) -> dict | None:
    with get_connection(db_path) as conn:
        sql = "SELECT * FROM chapters WHERE id = ?" + ("" if include_deleted else " AND deleted_at IS NULL")
        row = conn.execute(sql, (chapter_id,)).fetchone()
        return chapter_view(row) if row else None


def list_chapters(db_path: Path, book_id: int | None = None, include_deleted: bool = False) -> list[dict]:
    conditions, params = [], []
    if book_id is not None:
        conditions.append("book_id = ?")
        params.append(book_id)
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order = "chapter_number DESC" if book_id is not None else "id DESC"
    with get_connection(db_path) as conn:
        return [chapter_view(row) for row in conn.execute(f"SELECT * FROM chapters{where} ORDER BY {order}", params)]


_RAW_CHAPTER_WHERE = """c.deleted_at IS NULL
    AND COALESCE(c.translated_text_path, '') = ''
    AND COALESCE(c.status, '') NOT IN ('translated', 'qa_low', 'audio_done')"""


def list_raw_backlog(db_path: Path, *, book_id: int | None = None, limit: int = 50, offset: int = 0) -> dict:
    where = _RAW_CHAPTER_WHERE + (" AND c.book_id = ?" if book_id is not None else "")
    params = (book_id,) if book_id is not None else ()
    with get_connection(db_path) as conn:
        conn.execute("BEGIN")  # totals and rows describe the same read snapshot
        total = conn.execute(f"""SELECT COUNT(*) AS total_chapters, COUNT(DISTINCT c.book_id) AS total_books
            FROM chapters c JOIN books b ON b.id=c.book_id WHERE {where}""", params).fetchone()
        rows = conn.execute(f"""SELECT c.*, b.title AS book_title,
            COUNT(*) OVER (PARTITION BY c.book_id) AS raw_count,
            FIRST_VALUE(c.id) OVER (PARTITION BY c.book_id ORDER BY c.chapter_number, c.id) AS first_raw_id
            FROM chapters c JOIN books b ON b.id=c.book_id WHERE {where}
            ORDER BY c.book_id, c.chapter_number, c.id LIMIT ? OFFSET ?""", (*params, limit, offset)).fetchall()
    return {**dict(total), "chapters": [chapter_view(row) for row in rows],
            "book_counts": {row["book_id"]: row["raw_count"] for row in rows},
            "first_chapter_ids": {row["book_id"]: row["first_raw_id"] for row in rows}, "limit": limit, "offset": offset}


def list_raw_chapter_ids(db_path: Path, book_id: int) -> list[int]:
    with get_connection(db_path) as conn:
        return [row[0] for row in conn.execute(f"""SELECT c.id FROM chapters c JOIN books b ON b.id=c.book_id
            WHERE {_RAW_CHAPTER_WHERE} AND c.book_id=? ORDER BY c.chapter_number, c.id""", (book_id,))]
