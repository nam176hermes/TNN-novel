from __future__ import annotations

from pathlib import Path

from app.database.db import (
    add_book,
    add_chapter,
    get_connection,
    init_db,
    update_chapter_paths,
    update_glossary_term,
)
from app.scheduler.daily_queue import (
    add_pending_glossary_term,
    approve_glossary_term,
    generate_daily_report,
    get_pending_chapters,
    get_pending_glossary,
    reject_glossary_term,
)


def test_get_pending_chapters_book_zero_does_not_return_all_books(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, status="cleaned")

    assert get_pending_chapters(temp_db_path, book_id=0) == []


def test_generate_daily_report_book_zero_does_not_count_all_books(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(
        temp_db_path,
        chapter_id,
        translated_text_path=Path("/tmp/translated.txt"),
        status="translated",
    )

    report = generate_daily_report(temp_db_path, book_id=0)

    assert report["translated_today"] == 0
    assert report["needs_review"] == 0


def test_dashboard_glossary_helpers_use_canonical_state_history_and_archive(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    add_pending_glossary_term(temp_db_path, book_id, "待审", "chờ", confidence=0.75)
    add_pending_glossary_term(temp_db_path, book_id, "拒绝", "bỏ")

    pending = get_pending_glossary(temp_db_path, book_id)
    ids = {row["source_term"]: row["id"] for row in pending}
    approve_glossary_term(temp_db_path, ids["待审"])
    reject_glossary_term(temp_db_path, ids["拒绝"])

    with get_connection(temp_db_path) as conn:
        approved = conn.execute(
            "SELECT source_key, review_status, approved, locked, confidence, version FROM glossary_terms WHERE id = ?",
            (ids["待审"],),
        ).fetchone()
        archived = conn.execute(
            "SELECT archived_at FROM glossary_terms WHERE id = ?",
            (ids["拒绝"],),
        ).fetchone()
        actions = [
            row["action"]
            for row in conn.execute(
                "SELECT action FROM glossary_history WHERE term_id IN (?, ?) ORDER BY id",
                (ids["待审"], ids["拒绝"]),
            )
        ]

    assert tuple(approved) == ("待审", "APPROVED", 1, 0, 0.75, 2)
    assert archived is not None and archived["archived_at"]
    assert actions == ["add", "add", "approve", "archive"]
    assert get_pending_glossary(temp_db_path, book_id) == []


def test_dashboard_candidate_refresh_preserves_reviewer_metadata(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    add_pending_glossary_term(temp_db_path, book_id, "待审", "initial", category="term")
    term_id = get_pending_glossary(temp_db_path, book_id)[0]["id"]
    assert update_glossary_term(
        temp_db_path,
        term_id,
        target_term="reviewed target",
        category="reviewed category",
        mode="context",
        pinyin="reviewed pinyin",
        notes_vi="reviewed notes",
        variants="reviewed variants",
        priority=77,
        term_type="concept",
    )

    add_pending_glossary_term(
        temp_db_path,
        book_id,
        "待审",
        "background target",
        category="background category",
        confidence=0.1,
    )

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            """
            SELECT target_term, category, mode, pinyin, notes_vi, variants,
                   priority, term_type, occurrence_count, version
            FROM glossary_terms WHERE id = ?
            """,
            (term_id,),
        ).fetchone()
        actions = [
            row["action"]
            for row in conn.execute(
                "SELECT action FROM glossary_history WHERE term_id = ? ORDER BY id",
                (term_id,),
            )
        ]

    assert tuple(term) == (
        "reviewed target",
        "reviewed category",
        "context",
        "reviewed pinyin",
        "reviewed notes",
        "reviewed variants",
        77,
        "concept",
        2,
        3,
    )
    assert actions == ["add", "update", "observe"]
