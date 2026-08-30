from __future__ import annotations

import gzip
import io
import struct
import zipfile
from pathlib import Path

import httpx
import pytest

from app.database.db import (
    add_book,
    add_chapter,
    add_reader_entity,
    add_reader_entity_mention,
    get_connection,
    init_db,
    put_glossary_term,
    update_chapter_paths,
)
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import books as books_router
from app.mobile_api.services import pipeline_service as pipeline_service_module
from app.mobile_api.services.pipeline_service import PipelineService


def make_pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    pipeline.data_dir = data_dir
    return pipeline


@pytest.fixture
def temp_pipeline(temp_db_path: Path, tmp_path: Path) -> PipelineService:
    init_db(temp_db_path)
    return make_pipeline(temp_db_path, tmp_path)


@pytest.fixture
def override_books_pipeline(temp_pipeline: PipelineService):
    app.dependency_overrides[books_router.get_pipeline] = lambda: temp_pipeline
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(books_router.get_pipeline, None)


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_reader_progress_is_saved_and_returned_with_state(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 2, "Thanh Ngưu trấn")
    anchor = {
        "version": 1,
        "text": "Hàn Lập khẽ gật đầu.",
        "offset": 7,
        "prefix": "Sơn đạo",
        "suffix": "Lục ca",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        update = await client.patch(
            f"/api/books/{book_id}/reader/progress",
            json={
                "chapter_id": chapter_id,
                "mode": "paginated",
                "percent": 67,
                "paragraph_index": 4,
                "char_offset": 12,
                "absolute_char_offset": 712,
                "page_index": 1,
                "anchor": anchor,
            },
            headers=headers,
        )
        state = await client.get(f"/api/books/{book_id}/reader/state", headers=headers)

    assert update.status_code == 200
    assert update.json()["progress"] == {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "chapter_number": 2,
        "chapter_title": "Thanh Ngưu trấn",
        "mode": "paginated",
        "percent": 67,
        "paragraph_index": 4,
        "char_offset": 12,
        "absolute_char_offset": 712,
        "page_index": 1,
        "anchor": anchor,
        "updated_at": update.json()["progress"]["updated_at"],
    }
    assert state.status_code == 200
    assert state.json()["progress"] == update.json()["progress"]
    assert state.json()["annotations"] == []


@pytest.mark.asyncio
async def test_reader_annotations_crud_and_filter_deleted_items(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        created = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/annotations",
            json={
                "kind": "highlight",
                "paragraph_index": 3,
                "char_start": 5,
                "char_end": 19,
                "selected_text": "Hàn Lập khẽ gật đầu.",
                "color": "yellow",
            },
            headers=headers,
        )
        annotation_id = created.json()["annotation"]["id"]
        updated = await client.patch(
            f"/api/books/{book_id}/annotations/{annotation_id}",
            json={"kind": "note", "note": "Giữ xưng hô cổ trang.", "color": "blue"},
            headers=headers,
        )
        listed = await client.get(f"/api/books/{book_id}/annotations", headers=headers)
        deleted = await client.delete(f"/api/books/{book_id}/annotations/{annotation_id}", headers=headers)
        listed_after_delete = await client.get(f"/api/books/{book_id}/annotations", headers=headers)

    assert created.status_code == 201
    assert created.json()["annotation"] == {
        "id": annotation_id,
        "book_id": book_id,
        "chapter_id": chapter_id,
        "chapter_number": 1,
        "chapter_title": "Sơn biên tiểu thôn",
        "kind": "highlight",
        "paragraph_index": 3,
        "char_start": 5,
        "char_end": 19,
        "selected_text": "Hàn Lập khẽ gật đầu.",
        "note": "",
        "color": "yellow",
        "client_id": "",
        "created_at": created.json()["annotation"]["created_at"],
        "updated_at": created.json()["annotation"]["updated_at"],
        "deleted_at": None,
    }
    assert updated.status_code == 200
    assert updated.json()["annotation"]["kind"] == "note"
    assert updated.json()["annotation"]["note"] == "Giữ xưng hô cổ trang."
    assert updated.json()["annotation"]["color"] == "blue"
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["annotations"]] == [annotation_id]
    assert deleted.status_code == 200
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["annotations"] == []

    with get_connection(override_books_pipeline.db_path) as conn:
        row = conn.execute("SELECT deleted_at FROM reader_annotations WHERE id = ?", (annotation_id,)).fetchone()
        assert row is not None
        assert row["deleted_at"]


@pytest.mark.asyncio
async def test_reader_annotations_reject_chapter_from_another_book(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Book A")
    other_book_id = add_book(override_books_pipeline.db_path, "Book B")
    other_chapter_id = add_chapter(override_books_pipeline.db_path, other_book_id, 1, "Wrong chapter")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/chapters/{other_chapter_id}/annotations",
            json={"kind": "bookmark", "paragraph_index": 0},
            headers=headers,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reader_annotations_import_json_restores_marks_by_chapter_number_and_client_id(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")

    payload = {
        "annotations": [
            {
                "client_id": "phone-highlight-1",
                "chapter_id": 9999,
                "chapter_number": 1,
                "kind": "highlight",
                "paragraph_index": 3,
                "char_start": 5,
                "char_end": 19,
                "selected_text": "Hàn Lập khẽ gật đầu.",
                "color": "yellow",
            },
            {
                "client_id": "phone-note-1",
                "chapter_number": 1,
                "kind": "note",
                "paragraph_index": 4,
                "char_start": 0,
                "char_end": 8,
                "selected_text": "Lục ca",
                "note": "Giữ xưng hô cổ trang.",
                "color": "blue",
            },
        ],
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            f"/api/books/{book_id}/annotations/import",
            json=payload,
            headers=headers,
        )
        second = await client.post(
            f"/api/books/{book_id}/annotations/import",
            json=payload,
            headers=headers,
        )
        listed = await client.get(f"/api/books/{book_id}/annotations", headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["summary"] == {
        "imported": 2,
        "skipped": 0,
        "duplicates": 0,
        "invalid": 0,
    }
    assert second.status_code == 200, second.text
    assert second.json()["summary"] == {
        "imported": 0,
        "skipped": 2,
        "duplicates": 2,
        "invalid": 0,
    }
    assert listed.status_code == 200
    annotations = listed.json()["annotations"]
    assert len(annotations) == 2
    assert {item["client_id"] for item in annotations} == {"phone-highlight-1", "phone-note-1"}
    assert all(item["chapter_id"] == chapter_id for item in annotations)
    assert any(item["kind"] == "note" and item["note"] == "Giữ xưng hô cổ trang." for item in annotations)


@pytest.mark.asyncio
async def test_reader_sync_merges_progress_and_reports_annotation_conflicts(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_1_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    chapter_2_id = add_chapter(override_books_pipeline.db_path, book_id, 2, "Thanh Ngưu trấn")
    override_books_pipeline.save_reader_progress(
        book_id,
        chapter_id=chapter_1_id,
        mode="scroll",
        percent=10,
        paragraph_index=0,
    )
    server_annotation = override_books_pipeline.create_reader_annotation(
        book_id,
        chapter_1_id,
        kind="highlight",
        paragraph_index=1,
        selected_text="Server newer highlight",
        color="yellow",
    )
    assert server_annotation is not None
    with get_connection(override_books_pipeline.db_path) as conn:
        conn.execute(
            "UPDATE reader_progress SET updated_at = ? WHERE book_id = ?",
            ("2026-06-01T10:00:00+00:00", book_id),
        )
        conn.execute(
            "UPDATE reader_annotations SET updated_at = ? WHERE id = ?",
            ("2026-06-01T12:00:00+00:00", server_annotation["id"]),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json={
                "device_id": "phone",
                "progress": {
                    "chapter_id": chapter_2_id,
                    "mode": "scroll",
                    "percent": 55,
                    "paragraph_index": 4,
                    "char_offset": 8,
                    "absolute_char_offset": 248,
                    "page_index": 0,
                    "updated_at": "2026-06-01T11:00:00+00:00",
                },
                "annotations": [
                    {
                        "id": server_annotation["id"],
                        "chapter_id": chapter_1_id,
                        "kind": "note",
                        "paragraph_index": 1,
                        "selected_text": "Client older note",
                        "note": "Client edit should lose",
                        "color": "blue",
                        "updated_at": "2026-06-01T11:00:00+00:00",
                    },
                    {
                        "client_id": "local-bookmark-1",
                        "chapter_id": chapter_2_id,
                        "kind": "bookmark",
                        "paragraph_index": 0,
                        "updated_at": "2026-06-01T13:00:00+00:00",
                    },
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"]["chapter_id"] == chapter_2_id
    assert payload["progress"]["absolute_char_offset"] == 248
    assert payload["progress"]["updated_at"] == "2026-06-01T11:00:00+00:00"
    assert any(item["kind"] == "bookmark" and item["chapter_id"] == chapter_2_id for item in payload["annotations"])
    original = next(item for item in payload["annotations"] if item["id"] == server_annotation["id"])
    assert original["kind"] == "highlight"
    assert original["selected_text"] == "Server newer highlight"
    assert len(payload["conflicts"]) == 1
    conflict = payload["conflicts"][0]
    assert {
        "entity": conflict["entity"],
        "id": conflict["id"],
        "client_id": conflict["client_id"],
        "resolution": conflict["resolution"],
        "reason": conflict["reason"],
    } == {
        "entity": "annotation",
        "id": server_annotation["id"],
        "client_id": None,
        "resolution": "server_won",
        "reason": "server_newer",
    }
    assert conflict["server_annotation"]["selected_text"] == "Server newer highlight"
    assert conflict["client_annotation"]["selected_text"] == "Client older note"
    assert conflict["client_annotation"]["note"] == "Client edit should lose"


@pytest.mark.asyncio
async def test_reader_sync_reports_same_timestamp_progress_conflict(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_1_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    chapter_2_id = add_chapter(override_books_pipeline.db_path, book_id, 2, "Thanh Ngưu trấn")
    same_timestamp = "2026-06-01T12:00:00+00:00"
    override_books_pipeline.save_reader_progress(
        book_id,
        chapter_id=chapter_1_id,
        mode="scroll",
        percent=20,
        paragraph_index=2,
        char_offset=9,
        absolute_char_offset=109,
        page_index=0,
        updated_at=same_timestamp,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json={
                "device_id": "tablet",
                "last_sync_at": "2026-06-01T11:00:00+00:00",
                "progress": {
                    "chapter_id": chapter_2_id,
                    "mode": "paginated",
                    "percent": 55,
                    "paragraph_index": 4,
                    "char_offset": 8,
                    "absolute_char_offset": 248,
                    "page_index": 3,
                    "updated_at": same_timestamp,
                },
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"]["chapter_id"] == chapter_1_id
    assert payload["progress"]["absolute_char_offset"] == 109
    assert payload["conflicts"] == [
        {
            "entity": "progress",
            "id": None,
            "client_id": "tablet",
            "resolution": "server_won",
            "reason": "same_timestamp_different",
        }
    ]


@pytest.mark.asyncio
async def test_reader_sync_reports_same_timestamp_annotation_conflict(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    server_annotation = override_books_pipeline.create_reader_annotation(
        book_id,
        chapter_id,
        kind="highlight",
        paragraph_index=2,
        selected_text="Server edit",
        color="yellow",
    )
    assert server_annotation is not None
    same_timestamp = "2026-06-01T12:00:00+00:00"
    with get_connection(override_books_pipeline.db_path) as conn:
        conn.execute(
            "UPDATE reader_annotations SET updated_at = ? WHERE id = ?",
            (same_timestamp, server_annotation["id"]),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json={
                "device_id": "tablet",
                "annotations": [
                    {
                        "id": server_annotation["id"],
                        "chapter_id": chapter_id,
                        "kind": "note",
                        "paragraph_index": 2,
                        "selected_text": "Client edit",
                        "note": "Client note at same timestamp",
                        "color": "blue",
                        "updated_at": same_timestamp,
                    },
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    synced = next(item for item in payload["annotations"] if item["id"] == server_annotation["id"])
    assert synced["kind"] == "highlight"
    assert synced["selected_text"] == "Server edit"
    assert len(payload["conflicts"]) == 1
    conflict = payload["conflicts"][0]
    assert {
        "entity": conflict["entity"],
        "id": conflict["id"],
        "client_id": conflict["client_id"],
        "resolution": conflict["resolution"],
        "reason": conflict["reason"],
    } == {
        "entity": "annotation",
        "id": server_annotation["id"],
        "client_id": None,
        "resolution": "server_won",
        "reason": "same_timestamp_different",
    }
    assert conflict["server_annotation"]["selected_text"] == "Server edit"
    assert conflict["client_annotation"]["selected_text"] == "Client edit"
    assert conflict["client_annotation"]["note"] == "Client note at same timestamp"


@pytest.mark.asyncio
async def test_reader_sync_deduplicates_local_annotations_by_client_id(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    request_payload = {
        "device_id": "phone",
        "last_sync_at": "2026-06-01T10:00:00+00:00",
        "annotations": [
            {
                "client_id": "phone-highlight-1",
                "chapter_id": chapter_id,
                "kind": "highlight",
                "paragraph_index": 2,
                "char_start": 4,
                "char_end": 12,
                "selected_text": "Hàn Lập",
                "color": "yellow",
                "updated_at": "2026-06-01T11:00:00+00:00",
            },
        ],
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json=request_payload,
            headers=headers,
        )
        second = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json=request_payload,
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_annotations = [
        item for item in first.json()["annotations"]
        if item.get("client_id") == "phone-highlight-1"
    ]
    second_annotations = [
        item for item in second.json()["annotations"]
        if item.get("client_id") == "phone-highlight-1"
    ]
    assert len(first_annotations) == 1
    assert len(second_annotations) == 1
    assert first_annotations[0]["updated_at"] == "2026-06-01T11:00:00+00:00"
    assert second_annotations[0]["id"] == first_annotations[0]["id"]


@pytest.mark.asyncio
async def test_reader_sync_preserves_client_annotation_timestamp_when_client_update_wins(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    server_annotation = override_books_pipeline.create_reader_annotation(
        book_id,
        chapter_id,
        kind="highlight",
        paragraph_index=2,
        selected_text="Hàn Lập",
        color="yellow",
    )
    assert server_annotation is not None
    with get_connection(override_books_pipeline.db_path) as conn:
        conn.execute(
            "UPDATE reader_annotations SET updated_at = ? WHERE id = ?",
            ("2026-06-01T10:00:00+00:00", server_annotation["id"]),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json={
                "device_id": "phone",
                "last_sync_at": "2026-06-01T09:00:00+00:00",
                "annotations": [
                    {
                        "id": server_annotation["id"],
                        "client_id": "phone-note-1",
                        "chapter_id": chapter_id,
                        "kind": "note",
                        "paragraph_index": 2,
                        "char_start": 4,
                        "char_end": 12,
                        "selected_text": "Hàn Lập",
                        "note": "Nhân vật chính",
                        "color": "blue",
                        "updated_at": "2026-06-01T11:00:00+00:00",
                    },
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    synced = next(item for item in payload["annotations"] if item["id"] == server_annotation["id"])
    assert synced["kind"] == "note"
    assert synced["note"] == "Nhân vật chính"
    assert synced["updated_at"] == "2026-06-01T11:00:00+00:00"
    assert len(payload["conflicts"]) == 1
    conflict = payload["conflicts"][0]
    assert {
        "entity": conflict["entity"],
        "id": conflict["id"],
        "client_id": conflict["client_id"],
        "resolution": conflict["resolution"],
        "reason": conflict["reason"],
    } == {
        "entity": "annotation",
        "id": server_annotation["id"],
        "client_id": "phone-note-1",
        "resolution": "client_won",
        "reason": "diverged_since_last_sync",
    }
    assert conflict["server_annotation"]["selected_text"] == "Hàn Lập"
    assert conflict["client_annotation"]["selected_text"] == "Hàn Lập"
    assert conflict["client_annotation"]["note"] == "Nhân vật chính"


@pytest.mark.asyncio
async def test_reader_sync_preserves_client_annotation_deleted_at_when_client_delete_wins(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    server_annotation = override_books_pipeline.create_reader_annotation(
        book_id,
        chapter_id,
        kind="highlight",
        paragraph_index=2,
        selected_text="Hàn Lập",
        color="yellow",
    )
    assert server_annotation is not None
    with get_connection(override_books_pipeline.db_path) as conn:
        conn.execute(
            "UPDATE reader_annotations SET updated_at = ? WHERE id = ?",
            ("2026-06-01T10:00:00+00:00", server_annotation["id"]),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/sync",
            json={
                "device_id": "phone",
                "annotations": [
                    {
                        "id": server_annotation["id"],
                        "chapter_id": chapter_id,
                        "kind": "highlight",
                        "paragraph_index": 2,
                        "selected_text": "Hàn Lập",
                        "color": "yellow",
                        "updated_at": "2026-06-01T11:00:00+00:00",
                        "deleted_at": "2026-06-01T11:00:00+00:00",
                    },
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    synced = next(item for item in payload["annotations"] if item["id"] == server_annotation["id"])
    assert synced["deleted_at"] == "2026-06-01T11:00:00+00:00"
    assert synced["updated_at"] == "2026-06-01T11:00:00+00:00"


@pytest.mark.asyncio
async def test_reader_search_finds_translation_notes_and_highlights(
    override_books_pipeline: PipelineService,
    tmp_path: Path,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_1_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    chapter_2_id = add_chapter(override_books_pipeline.db_path, book_id, 2, "Thanh Ngưu trấn")
    chapter_1_path = tmp_path / "chapter_1_vi.txt"
    chapter_2_path = tmp_path / "chapter_2_vi.txt"
    chapter_1_path.write_text("Hàn Lập khẽ gật đầu.\n\nLục ca, ta cảm tạ huynh.", encoding="utf-8")
    chapter_2_path.write_text("Không có kết quả trùng ở chương này.", encoding="utf-8")
    update_chapter_paths(
        override_books_pipeline.db_path,
        chapter_1_id,
        translated_text_path=chapter_1_path,
        status="translated",
    )
    update_chapter_paths(
        override_books_pipeline.db_path,
        chapter_2_id,
        translated_text_path=chapter_2_path,
        status="translated",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        created_highlight = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_1_id}/annotations",
            json={
                "kind": "highlight",
                "paragraph_index": 1,
                "selected_text": "Lục ca, ta cảm tạ huynh.",
            },
            headers=headers,
        )
        created_note = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_2_id}/annotations",
            json={
                "kind": "note",
                "paragraph_index": 0,
                "char_start": 8,
                "char_end": 42,
                "selected_text": "Không có kết quả trùng ở chương này.",
                "note": "Giữ xưng hô cổ trang.",
            },
            headers=headers,
        )
        mixed = await client.get(
            f"/api/books/{book_id}/search",
            params={"q": "Lục", "scope": "translation,highlights,notes"},
            headers=headers,
        )
        notes_only = await client.get(
            f"/api/books/{book_id}/search",
            params={"q": "xưng hô", "scope": "notes"},
            headers=headers,
        )
        invalid_regex = await client.get(
            f"/api/books/{book_id}/search",
            params={"q": "[", "regex": "true"},
            headers=headers,
        )

    assert created_highlight.status_code == 201
    assert created_note.status_code == 201
    assert mixed.status_code == 200
    assert [item["source"] for item in mixed.json()["results"]] == ["translation", "highlight"]
    assert mixed.json()["results"][0] == {
        "chapter_id": chapter_1_id,
        "chapter_number": 1,
        "chapter_title": "Sơn biên tiểu thôn",
        "char_start": 0,
        "char_end": 3,
        "snippet": "Lục ca, ta cảm tạ huynh.",
        "paragraph_index": 1,
        "score": 99,
        "source": "translation",
    }
    assert notes_only.status_code == 200
    assert notes_only.json()["results"][0] == {
        "chapter_id": chapter_2_id,
        "chapter_number": 2,
        "chapter_title": "Thanh Ngưu trấn",
        "char_start": 8,
        "char_end": 42,
        "snippet": "Giữ xưng hô cổ trang.\nKhông có kết quả trùng ở chương...",
        "paragraph_index": 0,
        "score": 85,
        "source": "note",
    }
    assert invalid_regex.status_code == 400


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_returns_glossary_xray_and_online_fallback(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    put_glossary_term(
        override_books_pipeline.db_path,
        book_id,
        "筑基",
        "Trúc Cơ",
        category="realm",
        mode="translate",
        notes_vi="Cảnh giới tu luyện sau Luyện Khí.",
        variants="truc co",
    )
    entity = add_reader_entity(
        override_books_pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Hàn Lập",
        aliases=["Han Li"],
        description="Nhân vật chính, xuất thân từ sơn thôn.",
        first_chapter_number=1,
        importance=100,
    )
    add_reader_entity_mention(
        override_books_pipeline.db_path,
        book_id=book_id,
        entity_id=entity["id"],
        chapter_id=chapter_id,
        chapter_number=1,
        paragraph_index=0,
        mention_text="Hàn Lập",
        context="Hàn Lập bước vào Thất Huyền Môn.",
    )

    def fake_online_lookup(query: str, *, timeout: float = 2.0) -> list[dict]:
        return [
            {
                "source": "online",
                "provider": "test",
                "term": query,
                "definition": "mocked online definition",
            }
        ]

    monkeypatch.setattr(pipeline_service_module, "fetch_online_dictionary_lookup", fake_online_lookup)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        glossary_response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "Trúc Cơ", "chapter_id": chapter_id},
            headers=headers,
        )
        xray_response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "Hàn Lập", "chapter_id": chapter_id},
            headers=headers,
        )

    assert glossary_response.status_code == 200
    glossary_payload = glossary_response.json()
    assert glossary_payload["query"] == "Trúc Cơ"
    assert glossary_payload["online"]["status"] == "ok"
    assert any(item["source"] == "glossary" and item["target"] == "Trúc Cơ" for item in glossary_payload["sources"])
    assert any(item["source"] == "online" and item["definition"] == "mocked online definition" for item in glossary_payload["sources"])

    assert xray_response.status_code == 200
    xray_sources = xray_response.json()["sources"]
    assert any(item["source"] == "xray" and item["term"] == "Hàn Lập" for item in xray_sources)


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_keeps_offline_results_when_online_fails(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    put_glossary_term(
        override_books_pipeline.db_path,
        book_id,
        "灵石",
        "linh thạch",
        category="item",
        notes_vi="Đá linh khí dùng để tu luyện.",
    )

    def failing_online_lookup(query: str, *, timeout: float = 2.0) -> list[dict]:
        raise TimeoutError("network timeout")

    monkeypatch.setattr(pipeline_service_module, "fetch_online_dictionary_lookup", failing_online_lookup)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "linh thạch"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "error"
    assert "network timeout" in payload["online"]["error"]
    assert payload["sources"][0]["source"] == "glossary"
    assert payload["sources"][0]["target"] == "linh thạch"


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_uses_builtin_cn_vi_lexicon_offline(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "灵石", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert payload["offline_count"] >= 1
    assert payload["sources"][0]["source"] == "builtin"
    assert payload["sources"][0]["target"] == "linh thạch"
    assert "tu luyện" in payload["sources"][0]["definition"]


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_matches_traditional_chinese_builtin_terms(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "靈氣", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert payload["offline_count"] >= 1
    assert payload["sources"][0]["source"] == "builtin"
    assert payload["sources"][0]["term"] == "灵气"
    assert payload["sources"][0]["target"] == "linh khí"


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_matches_terms_inside_selected_phrase(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "hắn lấy ra một khối 灵石, linh khí lập tức tản ra", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert any(
        item["source"] == "builtin" and item["term"] == "灵石" and item["target"] == "linh thạch"
        for item in payload["sources"]
    )


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_orders_phrase_matches_by_selection_position(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "hắn vỗ nhẹ 储物袋 rồi lấy ra một viên 灵石", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    builtin_terms = [
        item["term"]
        for item in payload["sources"]
        if item["source"] == "builtin"
    ]
    assert builtin_terms[:2] == ["储物袋", "灵石"]


@pytest.mark.asyncio
async def test_reader_dictionary_builtin_lexicon_covers_common_cultivation_terms(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        responses = [
            await client.get(
                f"/api/books/{book_id}/dictionary/lookup",
                params={"q": query, "include_online": "false"},
                headers=headers,
            )
            for query in ("心魔", "储物袋", "阵法")
        ]

    payloads = [response.json() for response in responses]
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert [payload["online"]["status"] for payload in payloads] == ["skipped", "skipped", "skipped"]
    assert [payload["sources"][0]["target"] for payload in payloads] == ["tâm ma", "túi trữ vật", "trận pháp"]
    assert all(payload["sources"][0]["source"] == "builtin" for payload in payloads)


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_uses_file_backed_offline_dictionary(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    dictionaries_dir = override_books_pipeline.data_dir / "dictionaries"
    dictionaries_dir.mkdir(parents=True)
    (dictionaries_dir / "reader_cn_vi.tsv").write_text(
        "\n".join(
            [
                "term\ttarget\tcategory\tdefinition\tvariants",
                "道心\tđạo tâm\tconcept\tTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\tdao tam|tâm đạo",
            ]
        ),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "đạo tâm", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert payload["offline_count"] >= 1
    assert payload["sources"][0] == {
        "source": "offline_dictionary",
        "provider": "reader_cn_vi.tsv",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "concept",
        "variants": ["dao tam", "tâm đạo"],
    }


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_matches_unaccented_vietnamese_without_variants(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    dictionaries_dir = override_books_pipeline.data_dir / "dictionaries"
    dictionaries_dir.mkdir(parents=True)
    (dictionaries_dir / "reader_terms.csv").write_text(
        "\n".join(
            [
                "term,target,category,definition",
                "道心,đạo tâm,concept,Tâm cảnh tu đạo của tu sĩ.",
            ]
        ),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "dao tam", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert payload["offline_count"] >= 1
    assert {
        "source": "offline_dictionary",
        "provider": "reader_terms.csv",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo của tu sĩ.",
        "category": "concept",
        "variants": [],
    } in payload["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_lookup_uses_cc_cedict_offline_dictionary(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    dictionaries_dir = override_books_pipeline.data_dir / "dictionaries"
    dictionaries_dir.mkdir(parents=True)
    (dictionaries_dir / "cedict_ts.u8").write_text(
        "\n".join(
            [
                "# CC-CEDICT style test fixture",
                "道心 道心 [dao4 xin1] /Dao heart/state of spiritual resolve/cultivation will/",
                "飛劍 飞剑 [fei1 jian4] /flying sword/magic sword/",
            ]
        ),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "飞剑", "include_online": "false"},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["online"]["status"] == "skipped"
    assert payload["offline_count"] >= 1
    assert {
        "source": "offline_dictionary",
        "provider": "cedict_ts.u8",
        "term": "飞剑",
        "target": "fei1 jian4",
        "definition": "flying sword; magic sword",
        "category": "cc-cedict",
        "variants": ["飛劍", "fei1 jian4", "flying sword", "magic sword"],
    } in payload["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_file_management_uploads_lists_and_deletes_pack(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "custom_cedict.u8",
                    "# custom dictionary\n飛劍 飞剑 [fei1 jian4] /flying sword/magic sword/",
                    "text/plain",
                )
            },
            headers=headers,
        )
        listed = await client.get("/api/reader/dictionaries", headers=headers)
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "飞剑", "include_online": "false"},
            headers=headers,
        )
        deleted = await client.delete("/api/reader/dictionaries/custom_cedict.u8", headers=headers)
        listed_after_delete = await client.get("/api/reader/dictionaries", headers=headers)

    assert upload.status_code == 201
    upload_payload = upload.json()
    assert upload_payload["filename"] == "custom_cedict.u8"
    assert upload_payload["entry_count"] == 1
    assert upload_payload["size_bytes"] > 0

    assert listed.status_code == 200
    assert listed.json()["dictionaries"] == [
        {
            "filename": "custom_cedict.u8",
            "entry_count": 1,
            "size_bytes": upload_payload["size_bytes"],
        }
    ]

    assert lookup.status_code == 200
    assert {
        "source": "offline_dictionary",
        "provider": "custom_cedict.u8",
        "term": "飞剑",
        "target": "fei1 jian4",
        "definition": "flying sword; magic sword",
        "category": "cc-cedict",
        "variants": ["飛劍", "fei1 jian4", "flying sword", "magic sword"],
    } in lookup.json()["sources"]

    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Dictionary deleted", "filename": "custom_cedict.u8"}
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["dictionaries"] == []


@pytest.mark.asyncio
async def test_reader_dictionary_file_download_returns_uploaded_pack(
    override_books_pipeline: PipelineService,
) -> None:
    dictionaries_dir = override_books_pipeline.data_dir / "dictionaries"
    dictionaries_dir.mkdir(parents=True)
    (dictionaries_dir / "reader_cn_vi.tsv").write_text(
        "term\ttarget\tdefinition\n道心\tđạo tâm\tTâm cảnh tu đạo.",
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            "/api/reader/dictionaries/reader_cn_vi.tsv/download",
            headers=headers,
        )
        unsupported = await client.get(
            "/api/reader/dictionaries/reader_cn_vi.zip/download",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/tab-separated-values")
    assert "reader_cn_vi.tsv" in response.headers["content-disposition"]
    assert response.text == "term\ttarget\tdefinition\n道心\tđạo tâm\tTâm cảnh tu đạo."
    assert unsupported.status_code == 400


@pytest.mark.asyncio
async def test_reader_dictionary_upload_accepts_csv_term_packs(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "custom_terms.csv",
                    "\n".join(
                            [
                                "term,target,category,definition,variants",
                            '法宝,pháp bảo,item,"Bảo vật luyện chế, dùng khi đấu pháp",phap bao|bảo khí',
                        ]
                    ),
                    "text/csv",
                )
            },
            headers=headers,
        )
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "pháp bảo", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    assert upload.json()["entry_count"] == 1
    assert lookup.status_code == 200, lookup.text
    assert {
        "source": "offline_dictionary",
        "provider": "custom_terms.csv",
        "term": "法宝",
        "target": "pháp bảo",
        "definition": "Bảo vật luyện chế, dùng khi đấu pháp",
        "category": "item",
        "variants": ["phap bao", "bảo khí"],
    } in lookup.json()["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_upload_accepts_headerless_stardict_tsv(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "reader_stardict.tsv",
                    "\n".join(
                        [
                            "# term<TAB>target<TAB>definition<TAB>variants",
                            "道心\tđạo tâm\tTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\tdao tam|tâm đạo",
                            "飞剑\tphi kiếm\tKiếm bay dùng trong đấu pháp.\tfei jian|flying sword",
                        ]
                    ),
                    "text/tab-separated-values",
                )
            },
            headers=headers,
        )
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "tâm đạo", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    assert upload.json()["entry_count"] == 2
    assert lookup.status_code == 200, lookup.text
    assert {
        "source": "offline_dictionary",
        "provider": "reader_stardict.tsv",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "term",
        "variants": ["dao tam", "tâm đạo"],
    } in lookup.json()["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_upload_accepts_lingvo_dsl_files(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "tu_tien.dsl",
                    "\n".join(
                        [
                            "#NAME \"Tu tiên CN-VI\"",
                            "#INDEX_LANGUAGE \"Chinese\"",
                            "#CONTENTS_LANGUAGE \"Vietnamese\"",
                            "道心",
                            "\tđạo tâm",
                            "\tTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
                            "\tvariants: dao tam|tâm đạo",
                            "",
                            "飞剑",
                            "    phi kiếm",
                            "    Kiếm bay dùng trong đấu pháp.",
                        ]
                    ),
                    "text/plain",
                )
            },
            headers=headers,
        )
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "tâm đạo", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    assert upload.json()["entry_count"] == 2
    assert lookup.status_code == 200, lookup.text
    assert {
        "source": "offline_dictionary",
        "provider": "tu_tien.dsl",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "term",
        "variants": ["dao tam", "tâm đạo"],
    } in lookup.json()["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_upload_extracts_supported_zip_packs(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "nested/reader_terms.tsv",
            "\n".join(
                [
                    "term\ttarget\tdefinition\tvariants",
                    "道心\tđạo tâm\tTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\tdao tam|tâm đạo",
                ]
            ),
        )
        zip_file.writestr(
            "cedict/custom_cedict.u8",
            "# custom dictionary\n飛劍 飞剑 [fei1 jian4] /flying sword/magic sword/",
        )
        zip_file.writestr("notes/readme.md", "not a dictionary")
        zip_file.writestr("../escape.tsv", "term\ttarget\n邪修\ttà tu")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "offline_reader_pack.zip",
                    archive.getvalue(),
                    "application/zip",
                )
            },
            headers=headers,
        )
        listed = await client.get("/api/reader/dictionaries", headers=headers)
        lookup_tsv = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "tâm đạo", "include_online": "false"},
            headers=headers,
        )
        lookup_cedict = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "飞剑", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    upload_payload = upload.json()
    assert upload_payload["filename"] == "offline_reader_pack.zip"
    assert upload_payload["entry_count"] == 2
    assert upload_payload["file_count"] == 2
    assert [item["filename"] for item in upload_payload["files"]] == ["custom_cedict.u8", "reader_terms.tsv"]

    assert listed.status_code == 200
    assert [item["filename"] for item in listed.json()["dictionaries"]] == ["custom_cedict.u8", "reader_terms.tsv"]

    assert lookup_tsv.status_code == 200, lookup_tsv.text
    assert {
        "source": "offline_dictionary",
        "provider": "reader_terms.tsv",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "term",
        "variants": ["dao tam", "tâm đạo"],
    } in lookup_tsv.json()["sources"]

    assert lookup_cedict.status_code == 200, lookup_cedict.text
    assert {
        "source": "offline_dictionary",
        "provider": "custom_cedict.u8",
        "term": "飞剑",
        "target": "fei1 jian4",
        "definition": "flying sword; magic sword",
        "category": "cc-cedict",
        "variants": ["飛劍", "fei1 jian4", "flying sword", "magic sword"],
    } in lookup_cedict.json()["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_upload_accepts_stardict_zip_packs(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    entries = [
        ("道心", "đạo tâm\nTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\nvariants: dao tam|tâm đạo"),
        ("飞剑", "phi kiếm\nKiếm bay dùng trong đấu pháp."),
    ]
    dict_bytes = bytearray()
    idx_bytes = bytearray()
    for term, definition in entries:
        encoded_definition = definition.encode("utf-8")
        idx_bytes.extend(term.encode("utf-8"))
        idx_bytes.append(0)
        idx_bytes.extend(struct.pack(">II", len(dict_bytes), len(encoded_definition)))
        dict_bytes.extend(encoded_definition)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "stardict/tu_tien.ifo",
            "\n".join(
                [
                    "StarDict's dict ifo file",
                    "version=2.4.2",
                    "bookname=Tu tiên CN-VI",
                    f"wordcount={len(entries)}",
                    f"idxfilesize={len(idx_bytes)}",
                    "sametypesequence=m",
                ]
            ),
        )
        zip_file.writestr("stardict/tu_tien.idx", bytes(idx_bytes))
        zip_file.writestr("stardict/tu_tien.dict", bytes(dict_bytes))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "stardict_tu_tien.zip",
                    archive.getvalue(),
                    "application/zip",
                )
            },
            headers=headers,
        )
        listed = await client.get("/api/reader/dictionaries", headers=headers)
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "tâm đạo", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    upload_payload = upload.json()
    assert upload_payload["filename"] == "stardict_tu_tien.zip"
    assert upload_payload["entry_count"] == 2
    assert upload_payload["file_count"] == 1
    assert upload_payload["files"] == [
        {
            "filename": "tu_tien.stardict.jsonl",
            "entry_count": 2,
            "size_bytes": upload_payload["files"][0]["size_bytes"],
        }
    ]

    assert listed.status_code == 200
    assert [item["filename"] for item in listed.json()["dictionaries"]] == ["tu_tien.stardict.jsonl"]

    assert lookup.status_code == 200, lookup.text
    assert {
        "source": "offline_dictionary",
        "provider": "tu_tien.stardict.jsonl",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "stardict",
        "variants": ["dao tam", "tâm đạo"],
    } in lookup.json()["sources"]


@pytest.mark.asyncio
async def test_reader_dictionary_upload_accepts_compressed_stardict_dict_zip_packs(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    entries = [
        ("道心", "đạo tâm\nTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\nvariants: dao tam|tâm đạo"),
        ("飞剑", "phi kiếm\nKiếm bay dùng trong đấu pháp."),
    ]
    dict_bytes = bytearray()
    idx_bytes = bytearray()
    for term, definition in entries:
        encoded_definition = definition.encode("utf-8")
        idx_bytes.extend(term.encode("utf-8"))
        idx_bytes.append(0)
        idx_bytes.extend(struct.pack(">II", len(dict_bytes), len(encoded_definition)))
        dict_bytes.extend(encoded_definition)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "stardict/tu_tien.ifo",
            "\n".join(
                [
                    "StarDict's dict ifo file",
                    "version=2.4.2",
                    "bookname=Tu tiên CN-VI",
                    f"wordcount={len(entries)}",
                    f"idxfilesize={len(idx_bytes)}",
                    "sametypesequence=m",
                ]
            ),
        )
        zip_file.writestr("stardict/tu_tien.idx", bytes(idx_bytes))
        zip_file.writestr("stardict/tu_tien.dict.dz", gzip.compress(bytes(dict_bytes)))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload = await client.post(
            "/api/reader/dictionaries",
            files={
                "file": (
                    "stardict_tu_tien_dz.zip",
                    archive.getvalue(),
                    "application/zip",
                )
            },
            headers=headers,
        )
        lookup = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "tâm đạo", "include_online": "false"},
            headers=headers,
        )

    assert upload.status_code == 201, upload.text
    assert upload.json()["entry_count"] == 2
    assert upload.json()["files"][0]["filename"] == "tu_tien.stardict.jsonl"
    assert lookup.status_code == 200, lookup.text
    assert {
        "source": "offline_dictionary",
        "provider": "tu_tien.stardict.jsonl",
        "term": "道心",
        "target": "đạo tâm",
        "definition": "Tâm cảnh tu đạo, căn cơ ý chí của tu sĩ.",
        "category": "stardict",
        "variants": ["dao tam", "tâm đạo"],
    } in lookup.json()["sources"]


def test_fetch_online_dictionary_lookup_uses_zh_wiktionary_for_cjk_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return (
                b'{"query":{"pages":{"12":{"title":"\\u9053\\u5fc3",'
                b'"extract":"\\u4fee\\u9053\\u8005\\u7684\\u5fc3\\u5883\\u4e0e\\u610f\\u5fd7"}}}}'
            )

    def fake_urlopen(request, timeout: float = 2.0):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(pipeline_service_module, "urlopen", fake_urlopen)

    results = pipeline_service_module.fetch_online_dictionary_lookup("道心")

    assert requested_urls[0].startswith("https://api.mymemory.translated.net/get?")
    assert requested_urls[1].startswith("https://zh.wiktionary.org/w/api.php")
    assert results == [
        {
            "source": "online",
            "provider": "zh.wiktionary.org",
            "term": "道心",
            "definition": "修道者的心境与意志",
            "part_of_speech": "",
        }
    ]


def test_fetch_online_dictionary_lookup_translates_cjk_to_vietnamese_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return (
                b'{"responseData":{"translatedText":"\\u0111\\u1ea1o t\\u00e2m","match":0.93},'
                b'"matches":[{"translation":"\\u0111\\u1ea1o t\\u00e2m","match":0.93}]}'
            )

    def fake_urlopen(request, timeout: float = 2.0):
        requested_urls.append(request.full_url)
        assert request.full_url.startswith("https://api.mymemory.translated.net/get?")
        return FakeResponse()

    monkeypatch.setattr(pipeline_service_module, "urlopen", fake_urlopen)

    results = pipeline_service_module.fetch_online_dictionary_lookup("道心")

    assert "langpair=zh-CN%7Cvi" in requested_urls[0]
    assert results == [
        {
            "source": "online",
            "provider": "mymemory.translated.net",
            "term": "道心",
            "target": "đạo tâm",
            "definition": "Bản dịch nhanh Trung-Việt từ MyMemory.",
            "part_of_speech": "translation",
        }
    ]


@pytest.mark.asyncio
async def test_reader_dictionary_pack_returns_offline_sources_for_browser_cache(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Lý Thiên Lương")
    put_glossary_term(
        override_books_pipeline.db_path,
        book_id,
        "筑基",
        "Trúc Cơ",
        category="realm",
        notes_vi="Cảnh giới đặt nền móng tu luyện.",
        variants="truc co",
    )
    dictionaries_dir = override_books_pipeline.data_dir / "dictionaries"
    dictionaries_dir.mkdir(parents=True)
    (dictionaries_dir / "reader_cn_vi.tsv").write_text(
        "\n".join(
            [
                "term\ttarget\tcategory\tdefinition\tvariants",
                "道心\tđạo tâm\tconcept\tTâm cảnh tu đạo, căn cơ ý chí của tu sĩ.\tdao tam|tâm đạo",
            ]
        ),
        encoding="utf-8",
    )
    entity = add_reader_entity(
        override_books_pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Lý Thiên Lương",
        aliases=["Ly Thien Luong"],
        description="Đệ tử dẫn đội bắt độc xà.",
        first_chapter_number=1,
        importance=75,
    )
    add_reader_entity_mention(
        override_books_pipeline.db_path,
        book_id=book_id,
        entity_id=entity["id"],
        chapter_id=chapter_id,
        chapter_number=1,
        paragraph_index=0,
        mention_text="Lý Thiên Lương",
        context="Lý Thiên Lương phân phó mọi người bắt rắn.",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/dictionary/pack",
            params={"chapter_id": chapter_id},
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["book_id"] == book_id
    assert payload["chapter_id"] == chapter_id
    assert payload["online"]["status"] == "skipped"
    assert payload["source_count"] == len(payload["sources"])
    assert payload["counts"]["glossary"] >= 1
    assert payload["counts"]["offline_dictionary"] == 1
    assert payload["counts"]["xray"] == 1
    assert payload["counts"]["builtin"] >= 1
    assert not any(item["source"] == "online" for item in payload["sources"])
    assert any(item["source"] == "glossary" and item["target"] == "Trúc Cơ" for item in payload["sources"])
    assert any(item["source"] == "builtin" and item["target"] == "linh thạch" for item in payload["sources"])
    assert any(item["source"] == "offline_dictionary" and item["target"] == "đạo tâm" for item in payload["sources"])
    assert any(item["source"] == "xray" and item["term"] == "Lý Thiên Lương" for item in payload["sources"])


@pytest.mark.asyncio
async def test_reader_dictionary_online_lookup_is_cached(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    calls: list[str] = []

    def fake_online_lookup(query: str, *, timeout: float = 2.0) -> list[dict]:
        calls.append(query)
        return [
            {
                "source": "online",
                "provider": "test",
                "term": query,
                "definition": "cached online definition",
            }
        ]

    monkeypatch.setattr(pipeline_service_module, "fetch_online_dictionary_lookup", fake_online_lookup)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "alchemy"},
            headers=headers,
        )
        second = await client.get(
            f"/api/books/{book_id}/dictionary/lookup",
            params={"q": "alchemy"},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["alchemy"]
    assert first.json()["cache"]["stored"] is True
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    assert second.json()["cache"]["stored"] is False
    assert second.json()["sources"][0]["definition"] == "cached online definition"
