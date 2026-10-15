from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app.database.connection import get_connection
from app.database.chapter_repository import ContentRevisionConflict
from app.translation.qa_report import merge_qa_report


def save_qa_report_with_connection(
    conn: sqlite3.Connection,
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
    content_revision: int | None = None,
    component: str | None = None,
    expected_translation_hash: str | None = None,
) -> int:
    """Save a QA report, replacing any existing report for this chapter."""
    def _json_text(value: str | list | None) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value or [], ensure_ascii=False)

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    chapter = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if chapter is None or chapter["book_id"] != book_id:
        raise ValueError("Chapter not found")
    if content_revision is not None and int(chapter["content_revision"]) != content_revision:
        raise ContentRevisionConflict()
    if expected_translation_hash is not None and chapter["translation_hash"] != expected_translation_hash:
        raise ContentRevisionConflict()
    try:
        incoming = json.loads(report_json)
    except (json.JSONDecodeError, TypeError):
        incoming = {}
    if component is not None:
        previous = conn.execute("SELECT report_json, content_revision FROM qa_reports WHERE chapter_id = ? ORDER BY id DESC LIMIT 1", (chapter_id,)).fetchone()
        envelope = {}
        if previous and previous["content_revision"] == content_revision:
            try:
                envelope = json.loads(previous["report_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
        if component == "rule_based":
            incoming = merge_qa_report(incoming, envelope.get("semantic"), envelope.get("coverage"), envelope.get("provenance"))
        elif component == "semantic":
            incoming = merge_qa_report(envelope.get("rule_based"), incoming, {"complete": incoming.get("qa_complete", True), "required": True})
    if isinstance(incoming, dict) and incoming.get("report_version") == 1:
        provenance = incoming.setdefault("provenance", {})
        provenance.update(content_revision=content_revision, translation_hash=chapter["translation_hash"])
        report_json = json.dumps(incoming, ensure_ascii=False)
        verdict = incoming["verdict"]
        overall_status = incoming["overall_status"]
        quality_score = incoming["quality_score"]
        fidelity_score = incoming["fidelity_score"]
        style_score = incoming["style_score"]
        glossary_score = incoming["glossary_score"]
        audiobook_score = incoming["audiobook_score"]
        if content_revision is not None:
            conn.execute("UPDATE chapters SET quality_status = ? WHERE id = ?", (incoming["quality_status"], chapter_id))
    # Delete existing report for this chapter
    conn.execute("DELETE FROM qa_reports WHERE chapter_id = ?", (chapter_id,))
    cur = conn.execute(
        """INSERT INTO qa_reports
           (book_id, chapter_id, quality_score, fidelity_score, style_score,
            glossary_score, audiobook_score, verdict, job_id, overall_status,
            missing_paragraph_warning, chinese_leakage_count, name_consistency_status,
            term_consistency_status, length_ratio, repetition_warning, style_warnings,
            glossary_violations, suggested_fixes, report_json, content_revision, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (book_id, chapter_id, quality_score, fidelity_score, style_score,
         glossary_score, audiobook_score, verdict, job_id, overall_status,
         1 if missing_paragraph_warning else 0, int(chinese_leakage_count or 0),
         name_consistency_status, term_consistency_status, float(length_ratio or 0),
         1 if repetition_warning else 0, _json_text(style_warnings),
         _json_text(glossary_violations), _json_text(suggested_fixes), report_json, content_revision),
    )
    return cur.lastrowid



def save_qa_report(db_path: Path, *args, connection=None, **options) -> int:
    if connection is not None:
        return save_qa_report_with_connection(connection, *args, **options)
    with get_connection(db_path) as conn:
        result = save_qa_report_with_connection(conn, *args, **options)
        conn.commit()
        return result
