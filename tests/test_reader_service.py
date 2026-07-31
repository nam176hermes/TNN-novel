from __future__ import annotations

from pathlib import Path

from app.database.db import add_book, add_chapter, init_db, update_chapter_paths
from app.mobile_api.services.content_file_service import ContentFileService
from app.mobile_api.services.reader_service import ReaderService


def _service(temp_db_path: Path, tmp_path: Path) -> ReaderService:
    init_db(temp_db_path)
    content_files = ContentFileService(
        data_dir=tmp_path,
        db_path=temp_db_path,
        legacy_artifact_root=None,
    )
    return ReaderService(db_path=temp_db_path, content_file_service=content_files)


def test_reader_service_orchestrates_progress_and_content(temp_db_path: Path, tmp_path: Path) -> None:
    service = _service(temp_db_path, tmp_path)
    translated = tmp_path / "translated" / "chapter.txt"
    translated.parent.mkdir(parents=True)
    translated.write_text("Bản dịch chương.", encoding="utf-8")
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translated)

    progress = service.save_reader_progress(
        book_id,
        chapter_id=chapter_id,
        mode="paginated",
        percent=64,
        paragraph_index=3,
        char_offset=8,
        absolute_char_offset=208,
        page_index=2,
        anchor={"text": "Bản dịch"},
    )

    assert progress is not None
    assert progress["chapter_id"] == chapter_id
    assert progress["mode"] == "paginated"
    assert service.get_reader_state(book_id) == {"progress": progress, "annotations": []}
    assert service.get_chapter_content(chapter_id) == {"text": "Bản dịch chương.", "html": ""}
    assert service.save_reader_progress(book_id, chapter_id=999_999) is None
    assert service.get_reader_state(999_999) is None


def test_reader_service_orchestrates_annotation_lifecycle(temp_db_path: Path, tmp_path: Path) -> None:
    service = _service(temp_db_path, tmp_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    other_book_id = add_book(temp_db_path, "Other")
    other_chapter_id = add_chapter(temp_db_path, other_book_id, 1, "Other chapter")

    created = service.create_reader_annotation(
        book_id,
        chapter_id,
        kind="highlight",
        paragraph_index=2,
        char_start=1,
        char_end=5,
        selected_text="dịch",
        color="yellow",
        client_id="phone-1",
    )

    assert created is not None
    assert service.create_reader_annotation(book_id, other_chapter_id, kind="note") is None
    updated = service.update_reader_annotation(
        book_id,
        created["id"],
        kind="note",
        note="Giữ cách xưng hô.",
        color="blue",
    )
    assert updated is not None
    assert updated["kind"] == "note"
    assert updated["note"] == "Giữ cách xưng hô."
    assert service.list_reader_annotations(book_id) == [updated]
    assert service.delete_reader_annotation(book_id, created["id"]) is True
    assert service.delete_reader_annotation(book_id, created["id"]) is False
    assert service.list_reader_annotations(book_id) == []


def test_reader_service_sync_preserves_newer_client_state(temp_db_path: Path, tmp_path: Path) -> None:
    service = _service(temp_db_path, tmp_path)
    book_id = add_book(temp_db_path, "Book")
    first_chapter_id = add_chapter(temp_db_path, book_id, 1, "One")
    second_chapter_id = add_chapter(temp_db_path, book_id, 2, "Two")
    service.save_reader_progress(
        book_id,
        chapter_id=first_chapter_id,
        percent=10,
        updated_at="2026-07-01T10:00:00+00:00",
    )

    state = service.sync_reader_state(
        book_id,
        device_id="phone",
        last_sync_at="2026-07-01T09:00:00+00:00",
        progress={
            "chapter_id": second_chapter_id,
            "mode": "scroll",
            "percent": 75,
            "updated_at": "2026-07-01T11:00:00+00:00",
        },
        annotations=[
            {
                "chapter_id": second_chapter_id,
                "kind": "bookmark",
                "client_id": "phone-bookmark",
                "updated_at": "2026-07-01T11:00:00+00:00",
            }
        ],
    )

    assert state is not None
    assert state["progress"]["chapter_id"] == second_chapter_id
    assert state["progress"]["percent"] == 75
    assert len(state["annotations"]) == 1
    assert state["annotations"][0]["client_id"] == "phone-bookmark"
    assert state["conflicts"][0]["entity"] == "progress"
    assert state["conflicts"][0]["resolution"] == "client_won"
