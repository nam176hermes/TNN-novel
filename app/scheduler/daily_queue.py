from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings
from app.database.db import get_connection


def get_pending_chapters(db_path: Path, book_id: Optional[int] = None, limit: int = 15) -> list[dict]:
    """Get chapters ready for translation (status=cleaned, not yet translated)."""
    with get_connection(db_path) as conn:
        if book_id is not None:
            rows = conn.execute(
                """SELECT * FROM chapters
                   WHERE status = 'cleaned'
                   AND book_id = ?
                   ORDER BY chapter_number
                   LIMIT ?""",
                (book_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM chapters
                   WHERE status = 'cleaned'
                   ORDER BY book_id, chapter_number
                   LIMIT ?""",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_failed_chapters(db_path: Path, limit: int = 15) -> list[dict]:
    """Get chapters with failed translation status."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM chapters
               WHERE status = 'failed'
               ORDER BY translated_at
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_chapter_translating(db_path: Path, chapter_id: int, model: str) -> int:
    """Create a translation job record and mark chapter as translating."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO translation_jobs (chapter_id, model, status, started_at)
               VALUES (?, ?, 'running', CURRENT_TIMESTAMP)""",
            (chapter_id, model),
        )
        conn.execute(
            "UPDATE chapters SET status = 'translating' WHERE id = ?",
            (chapter_id,),
        )
        conn.commit()
        return cur.lastrowid


def mark_job_complete(db_path: Path, job_id: int, success: bool, error: str = "") -> None:
    """Mark translation job as complete or failed."""
    with get_connection(db_path) as conn:
        if success:
            conn.execute(
                """UPDATE translation_jobs
                   SET status = 'completed', finished_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (job_id,),
            )
        else:
            conn.execute(
                """UPDATE translation_jobs
                   SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error = ?
                   WHERE id = ?""",
                (error, job_id),
            )
        conn.commit()


def update_chapter_after_translate(
    db_path: Path,
    chapter_id: int,
    translated_path: Path,
    status: str = "translated",
) -> None:
    """Update chapter with translated path and status."""
    with get_connection(db_path) as conn:
        conn.execute(
            """UPDATE chapters
               SET translated_text_path = ?, status = ?, translated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (str(translated_path), status, chapter_id),
        )
        conn.commit()


def update_chapter_failed(db_path: Path, chapter_id: int, error: str) -> None:
    """Mark chapter as failed with error."""
    with get_connection(db_path) as conn:
        conn.execute(
            """UPDATE chapters
               SET status = 'failed', translated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (chapter_id,),
        )
        conn.commit()


def save_qa_report(db_path: Path, chapter_id: int, quality_score: float, report: dict) -> None:
    """Save QA report for a chapter."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO qa_reports (chapter_id, quality_score, report_json)
               VALUES (?, ?, ?)""",
            (chapter_id, quality_score, json.dumps(report, ensure_ascii=False)),
        )
        conn.commit()


def add_pending_glossary_term(
    db_path: Path,
    book_id: int,
    source: str,
    target: str,
    category: str = "term",
    confidence: float = 0.5,
) -> None:
    """Add a pending glossary term for user review."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO glossary_terms (book_id, source_term, target_term, category, confidence, approved)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (book_id, source, target, category, confidence),
        )
        conn.commit()


def get_pending_glossary(db_path: Path, book_id: int = 0) -> list[dict]:
    """Get pending glossary terms awaiting approval."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM glossary_terms
               WHERE approved = 0 AND book_id IN (0, ?)
               ORDER BY created_at DESC""",
            (book_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def approve_glossary_term(db_path: Path, term_id: int) -> None:
    """Approve a pending glossary term."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE glossary_terms SET approved = 1 WHERE id = ?",
            (term_id,),
        )
        conn.commit()


def reject_glossary_term(db_path: Path, term_id: int) -> None:
    """Reject/remove a pending glossary term."""
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM glossary_terms WHERE id = ?",
            (term_id,),
        )
        conn.commit()


def generate_daily_report(db_path: Path, book_id: Optional[int] = None) -> dict:
    """Generate a daily processing report."""
    with get_connection(db_path) as conn:
        if book_id is not None:
            # Chapters processed today
            translated_today = conn.execute(
                """SELECT COUNT(*) FROM chapters
                   WHERE status = 'translated' AND date(translated_at) = date('now')
                   AND book_id = ?""",
                (book_id,),
            ).fetchone()[0]
            failed_today = conn.execute(
                """SELECT COUNT(*) FROM chapters
                   WHERE status = 'failed' AND date(translated_at) = date('now')
                   AND book_id = ?""",
                (book_id,),
            ).fetchone()[0]
            # Average QA score
            qa_avg = conn.execute(
                """SELECT AVG(quality_score) FROM qa_reports qr
                   JOIN chapters c ON qr.chapter_id = c.id
                   WHERE c.book_id = ? AND date(qr.created_at) = date('now')""",
                (book_id,),
            ).fetchone()[0]
            new_terms = conn.execute(
                """SELECT COUNT(*) FROM glossary_terms
                   WHERE book_id = ? AND date(created_at) = date('now')""",
                (book_id,),
            ).fetchone()[0]
        else:
            translated_today = conn.execute(
                """SELECT COUNT(*) FROM chapters
                   WHERE status = 'translated' AND date(translated_at) = date('now')""",
            ).fetchone()[0]
            failed_today = conn.execute(
                """SELECT COUNT(*) FROM chapters
                   WHERE status = 'failed' AND date(translated_at) = date('now')""",
            ).fetchone()[0]
            qa_avg = conn.execute(
                """SELECT AVG(quality_score) FROM qa_reports
                   WHERE date(created_at) = date('now')""",
            ).fetchone()[0]
            new_terms = conn.execute(
                """SELECT COUNT(*) FROM glossary_terms
                   WHERE date(created_at) = date('now')""",
            ).fetchone()[0]

        # Pending review count
        pending_review = conn.execute(
            """SELECT COUNT(*) FROM qa_reports qr
               JOIN chapters c ON qr.chapter_id = c.id
               WHERE qr.quality_score < 7.0
               AND c.book_id = COALESCE(?, c.book_id)
               AND date(qr.created_at) = date('now')""",
            (book_id,),
        ).fetchone()[0]

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "translated_today": translated_today,
        "failed_today": failed_today,
        "avg_qa_score": round(qa_avg or 0, 2),
        "new_glossary_terms": new_terms,
        "needs_review": pending_review,
    }


def save_daily_report(db_path: Path, report: dict) -> None:
    """Save daily report to JSON file."""
    data_dir = settings.resolved_data_dir
    reports_dir = data_dir / "logs" / "daily_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"daily_{report['date']}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
