"""Self-learning engine for novel_pipeline.

Learns from user corrections to auto-improve glossary and prompt.
"""
from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path
from typing import List, Tuple


def add_correction(
    db_path: Path,
    book_id: int,
    chapter_number: int,
    source_chunk: str,
    pipe_out: str,
    user_fix: str,
    correction_type: str = "terminology",
) -> int:
    """Record a user correction."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """INSERT OR REPLACE INTO user_corrections
            (book_id, chapter_number, source_chunk, pipe_out, user_fix, correction_type)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (book_id, chapter_number, source_chunk, pipe_out, user_fix, correction_type),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def extract_term_changes(pipe_out: str, user_fix: str) -> List[Tuple[str, str]]:
    """Diff pipe output vs user fix to extract term-level changes.

    Returns list of (old_term, new_term) pairs.
    """
    changes = []
    sm = difflib.SequenceMatcher(None, pipe_out.split(), user_fix.split())
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "replace":
            old_phrase = " ".join(pipe_out.split()[i1:i2])
            new_phrase = " ".join(user_fix.split()[j1:j2])
            if old_phrase and new_phrase and old_phrase != new_phrase:
                changes.append((old_phrase, new_phrase))
        elif op == "insert":
            new_phrase = " ".join(user_fix.split()[j1:j2])
            if new_phrase:
                changes.append(("", new_phrase))
    return changes


def harvest_corrections(
    db_path: Path,
    book_id: int,
    days: int = 7,
    min_occurrences: int = 2,
) -> List[dict]:
    """Analyze recent corrections, extract candidate glossary terms.

    Returns list of dicts with keys:
        old_term, new_term, frequency, sample_source, correction_type
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """SELECT source_chunk, pipe_out, user_fix, correction_type
            FROM user_corrections
            WHERE book_id = ? AND created_at >= datetime('now', ?)""",
            (book_id, f"-{days} days"),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Aggregate term changes
    term_freq: dict[tuple[str, str], dict] = {}
    for source_chunk, pipe_out, user_fix, ctype in rows:
        changes = extract_term_changes(pipe_out, user_fix)
        for old_term, new_term in changes:
            key = (old_term, new_term)
            if key not in term_freq:
                term_freq[key] = {
                    "old_term": old_term,
                    "new_term": new_term,
                    "frequency": 0,
                    "sample_source": source_chunk[:200],
                    "correction_type": ctype,
                }
            term_freq[key]["frequency"] += 1

    # Filter by minimum occurrences
    candidates = [
        v for v in term_freq.values() if v["frequency"] >= min_occurrences
    ]
    candidates.sort(key=lambda x: x["frequency"], reverse=True)
    return candidates


def apply_glossary_candidates(
    db_path: Path,
    candidates: List[dict],
    book_id: int = 0,
    auto_approve: bool = False,
) -> int:
    """Write candidate terms to glossary_terms (pending or approved)."""
    from app.database.db import put_glossary_term

    count = 0
    for c in candidates:
        new_term = c["new_term"]
        if not new_term:
            continue
        put_glossary_term(
            db_path,
            book_id,
            c["old_term"] or new_term,
            new_term,
            category="term",
            mode="translate",
            pinyin="",
            notes_vi=c.get("notes_vi", ""),
            variants="",
            approved=1 if auto_approve else 0,
        )
        count += 1
    return count


def get_correction_stats(db_path: Path) -> dict:
    """Return stats about user corrections."""
    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute("SELECT COUNT(*) FROM user_corrections").fetchone()[0]
        recent = conn.execute(
            "SELECT COUNT(*) FROM user_corrections WHERE created_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
        by_type = conn.execute(
            "SELECT correction_type, COUNT(*) FROM user_corrections GROUP BY correction_type"
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_corrections": total,
        "last_7_days": recent,
        "by_type": dict(by_type),
    }


def run_self_improve(db_path: Path, book_id: int = 0, days: int = 7, min_freq: int = 2) -> dict:
    """Run the full self-improvement cycle.

    1. Harvest corrections
    2. Extract candidate terms
    3. Write to glossary (pending)
    4. Return summary

    Does NOT auto-approve. User must run `glossary review` + `glossary auto-approve`.
    """
    candidates = harvest_corrections(db_path, book_id=book_id, days=days, min_occurrences=min_freq)
    if not candidates:
        return {"status": "no_candidates", "candidates": [], "applied": 0}

    applied = apply_glossary_candidates(db_path, candidates, book_id=book_id, auto_approve=False)

    return {
        "status": "ok",
        "candidates_found": len(candidates),
        "applied": applied,
        "top_candidates": candidates[:10],
    }
