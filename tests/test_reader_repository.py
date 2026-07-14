from __future__ import annotations

import importlib
import inspect
import sqlite3
from pathlib import Path

import pytest

from app.database import db


READER_EXPORTS = (
    "get_reader_progress",
    "upsert_reader_progress",
    "list_reader_annotations",
    "get_reader_annotation",
    "get_reader_annotation_by_client_id",
    "add_reader_annotation",
    "update_reader_annotation",
    "soft_delete_reader_annotation",
    "get_reader_ai_cache",
    "upsert_reader_ai_cache",
    "get_reader_dictionary_cache",
    "upsert_reader_dictionary_cache",
    "add_reader_entity",
    "add_reader_entity_mention",
    "add_reader_timeline_event",
    "list_reader_xray_entities",
    "list_reader_timeline_events",
)


def _reader_repository():
    return importlib.import_module("app.database.reader_repository")


def _book_with_chapters(db_path: Path) -> tuple[int, int, int]:
    book_id = db.add_book(db_path, "Phàm Nhân Tu Tiên", "Vong Ngữ")
    first_chapter_id = db.add_chapter(db_path, book_id, 1, "Rời làng")
    second_chapter_id = db.add_chapter(db_path, book_id, 2, "Gặp Mặc đại phu")
    return book_id, first_chapter_id, second_chapter_id


def test_db_reader_exports_are_exact_repository_function_objects() -> None:
    repository = _reader_repository()

    for name in READER_EXPORTS:
        facade_function = getattr(db, name)
        repository_function = getattr(repository, name)
        assert facade_function is repository_function
        assert inspect.signature(facade_function) == inspect.signature(repository_function)


def test_repository_depends_only_on_connection_and_stdlib() -> None:
    repository = _reader_repository()
    source = inspect.getsource(repository)

    assert "from app.database.connection import get_connection" in source
    assert "from app.database import db" not in source
    assert "app.mobile_api" not in source


def test_progress_upsert_preserves_payload_and_replaces_one_row(temp_db_path: Path) -> None:
    repository = _reader_repository()
    book_id, first_chapter_id, second_chapter_id = _book_with_chapters(temp_db_path)

    repository.upsert_reader_progress(
        temp_db_path,
        book_id=book_id,
        chapter_id=first_chapter_id,
        mode="scroll",
        percent=20,
        paragraph_index=3,
        anchor={"text": "Hàn Lập", "offset": 2},
        updated_at="2026-07-14T01:00:00+00:00",
    )
    updated = repository.upsert_reader_progress(
        temp_db_path,
        book_id=book_id,
        chapter_id=second_chapter_id,
        mode="paginated",
        percent=75,
        paragraph_index=8,
        char_offset=4,
        absolute_char_offset=904,
        page_index=6,
        anchor={"offset": 7, "text": "Mặc đại phu"},
        updated_at="2026-07-14T02:00:00+00:00",
    )

    assert updated == {
        "book_id": book_id,
        "chapter_id": second_chapter_id,
        "chapter_number": 2,
        "chapter_title": "Gặp Mặc đại phu",
        "mode": "paginated",
        "percent": 75,
        "paragraph_index": 8,
        "char_offset": 4,
        "absolute_char_offset": 904,
        "page_index": 6,
        "anchor": {"offset": 7, "text": "Mặc đại phu"},
        "updated_at": "2026-07-14T02:00:00+00:00",
    }
    with db.get_connection(temp_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reader_progress").fetchone()[0] == 1


def test_annotation_conflict_and_soft_delete_semantics(temp_db_path: Path) -> None:
    repository = _reader_repository()
    book_id, chapter_id, _ = _book_with_chapters(temp_db_path)

    with pytest.raises(sqlite3.IntegrityError):
        repository.add_reader_annotation(
            temp_db_path,
            book_id=book_id,
            chapter_id=chapter_id,
            kind="unsupported",
        )

    annotation = repository.add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        kind="note",
        paragraph_index=2,
        selected_text="Linh căn",
        note="Ghi chú cũ",
        client_id=" client-1 ",
        created_at="2026-07-14T01:00:00+00:00",
        updated_at="2026-07-14T01:00:00+00:00",
    )
    assert annotation is not None
    assert annotation["client_id"] == "client-1"
    assert repository.get_reader_annotation_by_client_id(
        temp_db_path, book_id, " client-1 "
    ) == annotation

    updated = repository.update_reader_annotation(
        temp_db_path,
        book_id=book_id,
        annotation_id=annotation["id"],
        note="Ghi chú mới",
        color="emerald",
        updated_at="2026-07-14T02:00:00+00:00",
    )
    assert updated is not None
    assert updated["note"] == "Ghi chú mới"
    assert updated["color"] == "emerald"

    assert repository.soft_delete_reader_annotation(
        temp_db_path,
        book_id,
        annotation["id"],
        deleted_at="2026-07-14T03:00:00+00:00",
    ) is True
    assert repository.soft_delete_reader_annotation(
        temp_db_path, book_id, annotation["id"]
    ) is False
    assert repository.get_reader_annotation(temp_db_path, book_id, annotation["id"]) is None
    deleted = repository.get_reader_annotation(
        temp_db_path, book_id, annotation["id"], include_deleted=True
    )
    assert deleted is not None
    assert deleted["deleted_at"] == "2026-07-14T03:00:00+00:00"


def test_ai_and_dictionary_cache_upserts_preserve_normalized_payloads(
    temp_db_path: Path,
) -> None:
    repository = _reader_repository()
    book_id, chapter_id, _ = _book_with_chapters(temp_db_path)

    first_ai = repository.upsert_reader_ai_cache(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        text_hash="hash-1",
        spoiler_mode="no_spoiler",
        selected_text="韩立",
        response={
            "explanation": "Tên nhân vật",
            "terms": [{"source": "韩立", "target": "Hàn Lập", "note": ""}, "ignored"],
        },
    )
    second_ai = repository.upsert_reader_ai_cache(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        text_hash="hash-1",
        spoiler_mode="no_spoiler",
        selected_text="韩立",
        response={"explanation": "Đã cập nhật", "terms": []},
    )
    assert first_ai["terms"] == [{"source": "韩立", "target": "Hàn Lập", "note": ""}]
    assert second_ai == {"explanation": "Đã cập nhật", "terms": []}
    assert repository.get_reader_ai_cache(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        text_hash="hash-1",
        spoiler_mode="no_spoiler",
    ) == second_ai

    response = {
        "sources": [{"source": "glossary", "term": "韩立"}, "ignored"],
        "online": {"status": "ready", "error": "", "count": 4},
    }
    normalized = repository.upsert_reader_dictionary_cache(
        temp_db_path,
        book_id=book_id,
        query="韩立",
        query_norm="韩立",
        response=response,
    )
    cached = repository.get_reader_dictionary_cache(
        temp_db_path, book_id=book_id, query_norm="韩立"
    )
    assert normalized == {
        "sources": [{"source": "glossary", "term": "韩立"}],
        "online": {"status": "ready", "error": "", "count": 4},
    }
    assert cached is not None
    assert cached["sources"] == normalized["sources"]
    assert cached["online"] == normalized["online"]
    assert cached["updated_at"]


def test_xray_entities_mentions_and_timeline_keep_stable_ordering(temp_db_path: Path) -> None:
    repository = _reader_repository()
    book_id, first_chapter_id, second_chapter_id = _book_with_chapters(temp_db_path)

    low = repository.add_reader_entity(
        temp_db_path,
        book_id=book_id,
        entity_type="location",
        name="Thanh Ngưu trấn",
        aliases=["Thanh Ngưu"],
        description="Một thị trấn",
        first_chapter_number=1,
        importance=2,
        metadata={"region": "Việt Quốc"},
    )
    high = repository.add_reader_entity(
        temp_db_path,
        book_id=book_id,
        entity_type="character",
        name="Hàn Lập",
        aliases=["Hàn lão ma"],
        description="Nhân vật chính",
        first_chapter_number=1,
        importance=10,
        metadata={"realm": "Luyện Khí"},
    )
    repository.add_reader_entity_mention(
        temp_db_path,
        book_id=book_id,
        entity_id=high["id"],
        chapter_id=second_chapter_id,
        chapter_number=2,
        paragraph_index=4,
        mention_text="Hàn Lập",
    )
    repository.add_reader_entity_mention(
        temp_db_path,
        book_id=book_id,
        entity_id=high["id"],
        chapter_id=first_chapter_id,
        chapter_number=1,
        paragraph_index=2,
        mention_text="Hàn Lập",
    )
    repository.add_reader_entity_mention(
        temp_db_path,
        book_id=book_id,
        entity_id=low["id"],
        chapter_id=first_chapter_id,
        chapter_number=1,
        mention_text="Thanh Ngưu trấn",
    )

    repository.add_reader_timeline_event(
        temp_db_path,
        book_id=book_id,
        chapter_id=second_chapter_id,
        chapter_number=2,
        event_order=0,
        title="Gặp Mặc đại phu",
        entities=["Hàn Lập"],
    )
    repository.add_reader_timeline_event(
        temp_db_path,
        book_id=book_id,
        chapter_id=first_chapter_id,
        chapter_number=1,
        event_order=2,
        title="Rời làng",
        entities=["Hàn Lập", "Thanh Ngưu trấn"],
    )
    repository.add_reader_timeline_event(
        temp_db_path,
        book_id=book_id,
        chapter_id=first_chapter_id,
        chapter_number=1,
        event_order=1,
        title="Đến Thanh Ngưu trấn",
        entities=["Thanh Ngưu trấn"],
    )

    entities = repository.list_reader_xray_entities(temp_db_path, book_id)
    assert [entity["name"] for entity in entities] == ["Hàn Lập", "Thanh Ngưu trấn"]
    assert [mention["chapter_number"] for mention in entities[0]["mentions"]] == [1, 2]
    assert entities[0]["aliases"] == ["Hàn lão ma"]
    assert entities[0]["metadata"] == {"realm": "Luyện Khí"}

    no_spoiler = repository.list_reader_xray_entities(
        temp_db_path, book_id, max_chapter_number=1
    )
    assert [entity["name"] for entity in no_spoiler] == ["Hàn Lập", "Thanh Ngưu trấn"]
    assert no_spoiler[0]["aliases"] == []
    assert no_spoiler[0]["description"] == ""
    assert no_spoiler[0]["metadata"] == {}
    assert no_spoiler[0]["mention_count"] == 1

    timeline = repository.list_reader_timeline_events(temp_db_path, book_id)
    assert [event["title"] for event in timeline] == [
        "Đến Thanh Ngưu trấn",
        "Rời làng",
        "Gặp Mặc đại phu",
    ]
    assert repository.list_reader_timeline_events(
        temp_db_path, book_id, max_chapter_number=1
    ) == timeline[:2]
