from __future__ import annotations

from pathlib import Path

from app.database.db import add_book, get_connection, init_db, put_glossary_term
from app.mobile_api.services.glossary_service import GlossaryService


def make_glossary_service(db_path: Path) -> GlossaryService:
    service = object.__new__(GlossaryService)
    service.db_path = db_path
    return service


def test_update_term_does_not_increment_occurrence_count(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate", approved=0)

    with get_connection(temp_db_path) as conn:
        before = conn.execute(
            "SELECT id, occurrence_count FROM glossary_terms WHERE source_term = ?",
            ("灵石",),
        ).fetchone()

    service = make_glossary_service(temp_db_path)

    assert service.update_term(before["id"], {"target_term": "linh thạch mới", "mode": "context"})

    with get_connection(temp_db_path) as conn:
        after = conn.execute(
            "SELECT target_term, mode, approved, occurrence_count FROM glossary_terms WHERE id = ?",
            (before["id"],),
        ).fetchone()

    assert after["target_term"] == "linh thạch mới"
    assert after["mode"] == "context"
    assert after["approved"] == 0
    assert after["occurrence_count"] == before["occurrence_count"]


def test_add_and_update_term_supports_p2_metadata(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = make_glossary_service(temp_db_path)

    term_id = service.add_term(
        {
            "book_id": book_id,
            "source_term": "筑基",
            "target_term": "Trúc Cơ",
            "mode": "translate",
            "term_type": "realm",
            "genre": "tien_hiep",
            "priority": 20,
            "locked": 1,
            "approved": 1,
        }
    )

    assert service.update_term(
        term_id,
        {
            "target_term": "Trúc Cơ kỳ",
            "term_type": "realm",
            "genre": "huyen_huyen",
            "priority": 30,
            "locked": 0,
        },
    )

    terms, total = service.list_terms(book_id=book_id, limit=10)
    term = next(item for item in terms if item["id"] == term_id)

    assert total == 1
    assert term["target_term"] == "Trúc Cơ kỳ"
    assert term["term_type"] == "realm"
    assert term["genre"] == "huyen_huyen"
    assert term["priority"] == 30
    assert term["locked"] == 0


def test_lock_and_unlock_term(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = make_glossary_service(temp_db_path)
    term_id = service.add_term(
        {
            "book_id": book_id,
            "source_term": "灵石",
            "target_term": "linh thạch",
            "mode": "translate",
        }
    )

    assert service.set_term_locked(term_id, True) is True
    assert service.set_term_locked(term_id, False) is True
    assert service.set_term_locked(999999, True) is False

    terms, _ = service.list_terms(book_id=book_id, limit=10)
    term = next(item for item in terms if item["id"] == term_id)
    assert term["locked"] == 0


def test_translation_memory_service_add_search_and_clear(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = make_glossary_service(temp_db_path)

    entry_id = service.add_tm_entry(
        source_text="他拿起灵石。",
        translation_text="Hắn cầm linh thạch lên.",
        score=94,
        book_id=book_id,
        chapter_number=2,
    )
    matches = service.search_tm("他拿起灵石。", threshold=80)

    assert entry_id > 0
    assert matches[0]["translation_text"] == "Hắn cầm linh thạch lên."
    assert matches[0]["match_score"] == 100
    assert matches[0]["book_id"] == book_id
    assert matches[0]["chapter_number"] == 2
    assert service.clear_tm() == 1
    assert service.search_tm("他拿起灵石。", threshold=80) == []
