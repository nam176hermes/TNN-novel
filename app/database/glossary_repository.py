"""Glossary reads, review state, history, prompt selection and coverage."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.database.connection import get_connection
from app.database.glossary_history import log_glossary_change
from app.translation.styleguide_config import get_locked_terms

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



def sort_glossary_terms(terms: list[dict]) -> list[dict]:
    """Sort glossary terms by priority (high first), then by source term length (longer first), then alphabetically.

    OmegaT-style sorting: priority entries first, then longer source terms (more specific), then alphabetical.
    """
    return sorted(terms, key=lambda t: (
        -t.get('priority', 0),           # high priority first
        -len(t.get('source_term', '')),  # longer source first (more specific)
        t.get('source_term', '').lower(),
    ))



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

