from __future__ import annotations

from pathlib import Path

from app.database.db import add_book, add_chapter, init_db, update_chapter_paths
from app.scheduler.daily_queue import generate_daily_report, get_pending_chapters


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
