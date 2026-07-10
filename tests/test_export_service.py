from __future__ import annotations

from pathlib import Path
import subprocess
from zipfile import ZipFile

import httpx
import pytest

from app.database.db import add_book, add_chapter, add_reader_annotation, init_db, update_book, update_chapter_paths
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import exports as exports_router
from app.mobile_api.services.export_service import ExportService
from app.mobile_api.services.pipeline_service import PipelineService


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


def make_export_service(db_path: Path, data_dir: Path) -> ExportService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    pipeline.data_dir = data_dir
    return ExportService(pipeline)


def seed_translated_book(db_path: Path, data_dir: Path) -> int:
    init_db(db_path)
    book_id = add_book(db_path, "凡人修仙传", author="忘语", source="manual")
    translated_dir = data_dir / "translated"
    translated_dir.mkdir(parents=True, exist_ok=True)

    first_translation = translated_dir / "chapter-1.txt"
    first_translation.write_text("Lập tức, hắn bước vào sơn thôn.\n\nLục ca gật đầu.", encoding="utf-8")
    first_id = add_chapter(db_path, book_id, 1, "山边小村")
    update_chapter_paths(db_path, first_id, translated_text_path=first_translation, status="translated")

    second_translation = translated_dir / "chapter-2.txt"
    second_translation.write_text("Thiếu niên đi qua Thanh Ngưu trấn.", encoding="utf-8")
    second_id = add_chapter(db_path, book_id, 2, "青牛镇")
    update_chapter_paths(db_path, second_id, translated_text_path=second_translation, status="translated")
    return book_id


def test_export_service_creates_txt_docx_and_epub(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)

    txt = service.export_book(book_id, "txt")
    docx = service.export_book(book_id, "docx")
    epub = service.export_book(book_id, "epub")

    assert txt["chapter_count"] == 2
    assert Path(txt["path"]).read_text(encoding="utf-8").startswith("凡人修仙传\n忘语")
    assert "Chương 1: 山边小村" in Path(txt["path"]).read_text(encoding="utf-8")

    with ZipFile(docx["path"]) as archive:
        assert "word/document.xml" in archive.namelist()
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "凡人修仙传" in document_xml
        assert "Lập tức" in document_xml

    assert Path(epub["path"]).exists()
    assert Path(epub["path"]).stat().st_size > 0


def test_export_service_sanitizes_export_filename(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "../../Phàm Nhân:*?", author="Tác giả", source="manual")
    translated_dir = tmp_path / "translated"
    translated_dir.mkdir(parents=True, exist_ok=True)
    translation = translated_dir / "chapter-1.txt"
    translation.write_text("Bản dịch", encoding="utf-8")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chương 1")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translation, status="translated")
    service = make_export_service(temp_db_path, tmp_path)

    exported = service.export_book(book_id, "txt")

    assert exported["filename"] == "Ph_m_Nh_n.txt"


def test_export_service_embeds_book_cover_in_epub(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(b"export-cover")
    update_book(temp_db_path, book_id, cover_path=str(cover_path))
    service = make_export_service(temp_db_path, tmp_path)

    epub = service.export_book(book_id, "epub")

    with ZipFile(epub["path"]) as archive:
        cover_members = [name for name in archive.namelist() if name.endswith("cover.png")]
        assert cover_members
        assert archive.read(cover_members[0]) == b"export-cover"
        opf_members = [name for name in archive.namelist() if name.endswith(".opf")]
        assert opf_members
        assert "cover" in archive.read(opf_members[0]).decode("utf-8")


def test_export_service_packages_inline_chapter_images_in_epub(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    chapters = sorted(make_export_service(temp_db_path, tmp_path).pipeline.list_chapters(book_id), key=lambda item: item["chapter_number"])
    asset_dir = tmp_path / "book_assets" / str(book_id)
    asset_dir.mkdir(parents=True)
    image_path = asset_dir / "ch1_sword.png"
    image_path.write_bytes(b"inline-export-image")
    content_html_path = tmp_path / "translated" / "chapter-1.html"
    content_html_path.write_text(
        f'<p>Lập tức, hắn bước vào sơn thôn.</p><img src="/book-assets/{book_id}/ch1_sword.png" alt="Kiếm quang"/>',
        encoding="utf-8",
    )
    update_chapter_paths(
        temp_db_path,
        chapters[0]["id"],
        content_html_path=content_html_path,
        status="translated",
    )
    service = make_export_service(temp_db_path, tmp_path)

    exported = service.export_book(book_id, "epub")

    with ZipFile(exported["path"]) as archive:
        image_members = [name for name in archive.namelist() if name.endswith("images/ch1_sword.png")]
        assert image_members
        assert archive.read(image_members[0]) == b"inline-export-image"
        chapter_members = [name for name in archive.namelist() if name.endswith("chapter_0001.xhtml")]
        assert chapter_members
        chapter_html = archive.read(chapter_members[0]).decode("utf-8")
        assert 'src="images/ch1_sword.png"' in chapter_html
        assert "Kiếm quang" in chapter_html


def test_export_service_creates_m4b_audiobook(temp_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    chapters = sorted(service.pipeline.list_chapters(book_id), key=lambda item: item["chapter_number"])
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    first_audio = audio_dir / "chapter-1.mp3"
    first_audio.write_bytes(b"audio-1")
    second_audio = audio_dir / "chapter-2.mp3"
    second_audio.write_bytes(b"audio-2")
    update_chapter_paths(temp_db_path, chapters[0]["id"], audio_path=first_audio, status="audio_done")
    update_chapter_paths(temp_db_path, chapters[1]["id"], audio_path=second_audio, status="audio_done")
    calls: list[tuple[str, str, int, Path]] = []

    def fake_export_m4b(book_title: str, author: str, chapters_arg: list[dict], output_path: Path) -> Path:
        calls.append((book_title, author, len(chapters_arg), output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"m4b")
        return output_path

    monkeypatch.setattr("app.mobile_api.services.export_service.export_m4b", fake_export_m4b)

    exported = service.export_audiobook(book_id, "m4b")

    assert calls == [("凡人修仙传", "忘语", 2, Path(exported["path"]))]
    assert exported == {
        "book_id": book_id,
        "book_title": "凡人修仙传",
        "format": "m4b",
        "filename": Path(exported["path"]).name,
        "path": exported["path"],
        "media_type": "audio/mp4",
        "size_bytes": 3,
        "chapter_count": 2,
    }


def test_export_m4b_uses_isolated_concat_file_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.export.m4b_exporter import export_m4b

    chapter = tmp_path / "chapter.mp3"
    chapter.write_bytes(b"audio")
    output_path = tmp_path / "exports" / "book.m4b"
    commands: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        commands.append((command, kwargs))
        Path(command[-1]).write_bytes(b"m4b")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.export.m4b_exporter.subprocess.run", fake_run)

    assert export_m4b("Book", "Author", [{"chapter_number": 1, "audio_path": str(chapter)}], output_path) == output_path
    command, kwargs = commands[0]
    concat_path = Path(command[command.index("-i") + 1])
    assert concat_path.name != "m4b_concat.txt"
    assert command[-1] == str(output_path)
    assert kwargs["timeout"] == 600


@pytest.mark.asyncio
async def test_export_download_endpoint_returns_file(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    app.dependency_overrides[exports_router.get_export_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            response = await client.get(
                f"/api/books/{book_id}/exports/txt/download",
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert "Lập tức" in response.text


@pytest.mark.asyncio
async def test_export_download_endpoint_requires_authentication(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    app.dependency_overrides[exports_router.get_export_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/books/{book_id}/exports/txt/download")
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_audiobook_export_download_endpoint_returns_m4b(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    chapters = sorted(service.pipeline.list_chapters(book_id), key=lambda item: item["chapter_number"])
    audio_path = tmp_path / "chapter-1.mp3"
    audio_path.write_bytes(b"audio")
    update_chapter_paths(temp_db_path, chapters[0]["id"], audio_path=audio_path, status="audio_done")

    def fake_export_m4b(book_title: str, author: str, chapters_arg: list[dict], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"m4b-download")
        return output_path

    monkeypatch.setattr("app.mobile_api.services.export_service.export_m4b", fake_export_m4b)
    app.dependency_overrides[exports_router.get_export_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthenticated = await client.get(f"/api/books/{book_id}/exports/audiobook/m4b/download")
            headers = await auth_headers(client)
            response = await client.get(
                f"/api/books/{book_id}/exports/audiobook/m4b/download",
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mp4")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content == b"m4b-download"


@pytest.mark.asyncio
async def test_annotation_export_download_returns_json_and_markdown(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    chapters = sorted(service.pipeline.list_chapters(book_id), key=lambda item: item["chapter_number"])
    add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapters[0]["id"],
        kind="highlight",
        paragraph_index=0,
        char_start=0,
        char_end=16,
        selected_text="Lập tức, hắn",
        note="",
        color="yellow",
        client_id="phone-highlight-1",
    )
    add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapters[1]["id"],
        kind="note",
        paragraph_index=0,
        selected_text="Thanh Ngưu trấn",
        note="Giữ địa danh nhất quán.",
        color="blue",
        client_id="phone-note-1",
    )
    app.dependency_overrides[exports_router.get_export_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            json_response = await client.get(
                f"/api/books/{book_id}/exports/annotations/json/download",
                headers=headers,
            )
            md_response = await client.get(
                f"/api/books/{book_id}/exports/annotations/md/download",
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    json_payload = json_response.json()
    assert json_payload["format"] == "novel_tnn_reader_annotations"
    assert json_payload["version"] == 2
    assert json_payload["scope"] == {"kinds": [], "label": "annotations"}
    assert json_payload["book"]["title"] == "凡人修仙传"
    assert json_payload["annotation_count"] == 2
    assert json_payload["kind_counts"] == {"bookmark": 0, "highlight": 1, "note": 1}
    assert json_payload["chapter_count"] == 2
    assert json_payload["chapters"] == [
        {
            "chapter_id": chapters[0]["id"],
            "chapter_number": 1,
            "chapter_title": chapters[0]["title"],
            "annotation_count": 1,
            "kind_counts": {"bookmark": 0, "highlight": 1, "note": 0},
            "annotation_ids": [json_payload["annotations"][0]["id"]],
            "client_ids": ["phone-highlight-1"],
        },
        {
            "chapter_id": chapters[1]["id"],
            "chapter_number": 2,
            "chapter_title": chapters[1]["title"],
            "annotation_count": 1,
            "kind_counts": {"bookmark": 0, "highlight": 0, "note": 1},
            "annotation_ids": [json_payload["annotations"][1]["id"]],
            "client_ids": ["phone-note-1"],
        },
    ]
    assert [item["kind"] for item in json_payload["annotations"]] == ["highlight", "note"]
    assert json_payload["annotations"][0]["client_id"] == "phone-highlight-1"
    assert json_payload["annotations"][1]["note"] == "Giữ địa danh nhất quán."
    assert json_payload["annotations"][1]["client_id"] == "phone-note-1"

    assert md_response.status_code == 200
    assert md_response.headers["content-type"].startswith("text/markdown")
    assert "# 凡人修仙传 - Reader annotations" in md_response.text
    assert "- Client ID: phone-note-1" in md_response.text
    assert "> Lập tức, hắn" in md_response.text
    assert "Giữ địa danh nhất quán." in md_response.text


@pytest.mark.asyncio
async def test_annotation_export_download_filters_by_annotation_kind(temp_db_path: Path, tmp_path: Path) -> None:
    book_id = seed_translated_book(temp_db_path, tmp_path)
    service = make_export_service(temp_db_path, tmp_path)
    chapters = sorted(service.pipeline.list_chapters(book_id), key=lambda item: item["chapter_number"])
    add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapters[0]["id"],
        kind="highlight",
        paragraph_index=0,
        char_start=0,
        char_end=16,
        selected_text="Lập tức, hắn",
        note="",
        color="yellow",
    )
    add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapters[0]["id"],
        kind="bookmark",
        paragraph_index=1,
        char_start=0,
        char_end=0,
        selected_text="",
        note="",
        color="gray",
        client_id="phone-bookmark-1",
    )
    add_reader_annotation(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapters[1]["id"],
        kind="note",
        paragraph_index=0,
        selected_text="Thanh Ngưu trấn",
        note="Giữ địa danh nhất quán.",
        color="blue",
    )
    app.dependency_overrides[exports_router.get_export_service] = lambda: service

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            highlights = await client.get(
                f"/api/books/{book_id}/exports/annotations/json/download",
                params={"kind": "highlight"},
                headers=headers,
            )
            bookmarks = await client.get(
                f"/api/books/{book_id}/exports/annotations/csv/download",
                params={"kind": "bookmark"},
                headers=headers,
            )
            notes = await client.get(
                f"/api/books/{book_id}/exports/annotations/md/download",
                params={"kind": "note"},
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(exports_router.get_export_service, None)

    assert highlights.status_code == 200
    assert highlights.json()["annotation_count"] == 1
    assert highlights.json()["scope"] == {"kinds": ["highlight"], "label": "highlights"}
    assert highlights.json()["kind_counts"] == {"bookmark": 0, "highlight": 1, "note": 0}
    assert [item["kind"] for item in highlights.json()["annotations"]] == ["highlight"]
    assert "highlights" in highlights.headers["content-disposition"]

    assert bookmarks.status_code == 200
    assert "client_id" in bookmarks.text.splitlines()[0]
    assert "phone-bookmark-1" in bookmarks.text
    assert "bookmark" in bookmarks.text
    assert "highlight" not in bookmarks.text
    assert "notes" not in bookmarks.headers["content-disposition"]

    assert notes.status_code == 200
    assert "- Type: note" in notes.text
    assert "Giữ địa danh nhất quán." in notes.text
    assert "- Type: highlight" not in notes.text
