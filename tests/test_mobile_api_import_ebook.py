from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import zipfile

import httpx
import pytest

from app.database.db import (
    add_book,
    get_book_by_title,
    init_db,
    list_books,
    list_chapters,
    list_ebook_import_runs,
)
from app.mobile_api import upload_limits
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import import_routes
from app.mobile_api.routers.import_routes import _stage_ebook_upload
from app.mobile_api.services.ebook_import_service import EbookImportService
from app.mobile_api.services.job_service import get_shared_job_tracker


def minimal_epub_bytes() -> bytes:
    temp_path = Path("/tmp/minimal-import-test.epub")
    with zipfile.ZipFile(temp_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Đấu Phá Thương Khung</dc:title>
    <dc:creator>Thiên Tằm Thổ Đậu</dc:creator>
    <dc:language>vi</dc:language>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/c1.xhtml",
            "<html><body><h1>Chương 1: Vẫn Lạc Thiên Tài</h1><p>Đấu khí, ba đoạn!</p></body></html>",
        )
        epub.writestr("OEBPS/cover.jpg", b"api-cover")
    data = temp_path.read_bytes()
    temp_path.unlink(missing_ok=True)
    return data


def missing_title_epub_bytes() -> bytes:
    temp_path = Path("/tmp/missing-title-import-test.epub")
    with zipfile.ZipFile(temp_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/c1.xhtml",
            "<html><body><h1>Chương 1: Vào núi</h1><p>Thiếu niên bước vào núi.</p></body></html>",
        )
    data = temp_path.read_bytes()
    temp_path.unlink(missing_ok=True)
    return data


def heading_split_epub_bytes() -> bytes:
    temp_path = Path("/tmp/heading-split-import-test.epub")
    with zipfile.ZipFile(temp_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Linh Vực</dc:title>
    <dc:creator>Tịnh Vô Ngân</dc:creator>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="body" href="body.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="body"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/body.xhtml",
            """<html><body>
<h1>Chương 1: Sơn cốc</h1><p>Thiếu niên ngẩng đầu.</p>
<h1>Chương 2: Kiếm ý</h1><p>Kiếm khí lạnh thấu xương.</p>
</body></html>""",
        )
    data = temp_path.read_bytes()
    temp_path.unlink(missing_ok=True)
    return data


def translated_txt_bytes() -> bytes:
    return (
        "Chương 1: Gió nổi\n"
        "Thiếu niên áo xanh đứng trước sơn môn.\n\n"
        "Chương 2: Kiếm ý\n"
        "Một luồng kiếm khí lạnh thấu xương vụt qua.\n"
    ).encode("utf-8")


def write_minimal_epub(path: Path) -> None:
    path.write_bytes(minimal_epub_bytes())


def test_stage_ebook_upload_handles_cross_device_temp_files(tmp_path: Path, temp_db_path: Path) -> None:
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    source = Path("/tmp/novel-stage-cross-device.epub")
    source.write_bytes(b"ebook")

    upload_id = _stage_ebook_upload(service, source, "translated.epub")

    staged = service.data_dir / "import_uploads" / f"{upload_id}.epub"
    assert staged.read_bytes() == b"ebook"
    assert not source.exists()


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def override_ebook_service(temp_db_path: Path, tmp_path: Path) -> EbookImportService:
    init_db(temp_db_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    app.dependency_overrides[import_routes.get_ebook_import_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(import_routes.get_ebook_import_service, None)


@pytest.mark.asyncio
async def test_ebook_preview_endpoint_returns_metadata_and_chapter_samples(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Đấu Phá Thương Khung"
    assert data["author"] == "Thiên Tằm Thổ Đậu"
    assert data["language"] == "vi"
    assert data["chapter_count"] == 1
    assert data["cover_present"] is True
    assert data["cover_preview_url"].startswith("/covers/previews/")
    assert data["chapters"][0]["title"] == "Vẫn Lạc Thiên Tài"
    assert data["chapters"][0]["sample"] == "Đấu khí, ba đoạn!"
    assert data["first_chapters"][0]["title"] == "Vẫn Lạc Thiên Tài"
    assert data["last_chapters"][0]["title"] == "Vẫn Lạc Thiên Tài"
    assert data["dry_run"]["new_chapters"] == 1
    assert data["dry_run"]["duplicate_chapters"] == 0
    assert data["upload_id"]


@pytest.mark.asyncio
async def test_ebook_preview_endpoint_uses_original_filename_as_fallback_title(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("Thanh Son ban dich.epub", missing_title_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["title"] == "Thanh Son ban dich"


@pytest.mark.asyncio
async def test_ebook_preview_endpoint_supports_single_split_mode(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/ebook/preview",
            data={"split_mode": "single"},
            files={"file": ("translated.epub", heading_split_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["chapter_count"] == 1
    assert data["chapters"][0]["title"] == "Toàn bộ ebook"
    assert "Chương 2: Kiếm ý" in data["chapters"][0]["sample"]


@pytest.mark.asyncio
async def test_ebook_import_endpoint_adds_translated_book_to_library(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Imported translated ebook"
    assert data["imported_chapters"] == 1
    assert data["cover_url"].startswith("/covers/")
    book = get_book_by_title(override_ebook_service.db_path, "Đấu Phá Thương Khung")
    assert book is not None
    assert Path(book["cover_path"]).read_bytes() == b"api-cover"
    chapters = list_chapters(override_ebook_service.db_path, book["id"])
    assert chapters[0]["status"] == "translated"
    assert Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8") == "Đấu khí, ba đoạn!"


@pytest.mark.asyncio
async def test_translated_txt_preview_and_import_endpoint_adds_book_to_library(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        preview = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("Thanh Sơn bản dịch.txt", translated_txt_bytes(), "text/plain")},
            headers=headers,
        )
        imported = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("Thanh Sơn bản dịch.txt", translated_txt_bytes(), "text/plain")},
            headers=headers,
        )

    assert preview.status_code == 200
    assert preview.json()["source_format"] == "txt"
    assert preview.json()["split_method"] == "regex"
    assert preview.json()["chapter_count"] == 2
    assert imported.status_code == 200
    data = imported.json()
    assert data["imported_chapters"] == 2
    book = get_book_by_title(override_ebook_service.db_path, "Thanh Sơn bản dịch")
    assert book is not None
    chapters = sorted(
        list_chapters(override_ebook_service.db_path, book["id"]),
        key=lambda chapter: chapter["chapter_number"],
    )
    assert [chapter["title"] for chapter in chapters] == ["Gió nổi", "Kiếm ý"]


@pytest.mark.asyncio
async def test_ebook_import_endpoint_accepts_preview_upload_id_without_reuploading_file(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        preview = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        assert preview.status_code == 200

        response = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error", "upload_id": preview.json()["upload_id"]},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Imported translated ebook"
    assert data["imported_chapters"] == 1
    upload_dir = override_ebook_service.data_dir / "import_uploads"
    assert not list(upload_dir.glob("*"))


@pytest.mark.asyncio
async def test_ebook_import_job_endpoint_imports_preview_upload_in_background(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        preview = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        assert preview.status_code == 200

        response = await client.post(
            "/api/import/ebook/job",
            data={"duplicate_strategy": "error", "upload_id": preview.json()["upload_id"]},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Translated ebook import job started"
    job_id = data["job_id"]

    tracker = get_shared_job_tracker(override_ebook_service.db_path)
    job = None
    for _ in range(100):
        job = tracker.get_job(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)

    assert job is not None
    assert job.status == "completed"
    assert job.progress == 1
    assert "Imported 1 translated ebook chapter" in job.message
    book = get_book_by_title(override_ebook_service.db_path, "Đấu Phá Thương Khung")
    assert book is not None
    chapters = list_chapters(override_ebook_service.db_path, book["id"])
    assert chapters[0]["status"] == "translated"
    upload_dir = override_ebook_service.data_dir / "import_uploads"
    assert not list(upload_dir.glob("*"))


@pytest.mark.asyncio
async def test_ebook_inbox_preview_and_import_use_server_file_without_browser_upload(
    override_ebook_service: EbookImportService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inbox_dir = tmp_path / "inbox" / "ebooks"
    inbox_dir.mkdir(parents=True)
    write_minimal_epub(inbox_dir / "translated-from-inbox.epub")
    monkeypatch.setenv("EBOOK_INBOX_DIR", str(inbox_dir))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        listing = await client.get("/api/import/ebook/inbox", headers=headers)
        preview = await client.post(
            "/api/import/ebook/inbox/preview",
            data={"filename": "translated-from-inbox.epub"},
            headers=headers,
        )
        imported = await client.post(
            "/api/import/ebook",
            data={"inbox_file": "translated-from-inbox.epub", "duplicate_strategy": "error"},
            headers=headers,
        )

    assert listing.status_code == 200
    assert listing.json()["files"][0]["name"] == "translated-from-inbox.epub"
    assert preview.status_code == 200
    assert preview.json()["inbox_file"] == "translated-from-inbox.epub"
    assert preview.json()["title"] == "Đấu Phá Thương Khung"
    assert imported.status_code == 200
    assert imported.json()["imported_chapters"] == 1
    assert (inbox_dir / "translated-from-inbox.epub").exists()


@pytest.mark.asyncio
async def test_ebook_import_endpoint_defaults_to_skipping_duplicate_chapters(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        second = await client.post(
            "/api/import/ebook",
            data={"confirmed_existing_book_id": str(first.json()["book_id"])},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    data = second.json()
    assert data["imported_chapters"] == 0
    assert data["skipped_chapters"] == 1


@pytest.mark.asyncio
async def test_existing_ebook_requires_confirmation_before_sync_import(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        missing = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "skip"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        mismatched = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "skip", "confirmed_existing_book_id": str(first.json()["book_id"] + 1)},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        confirmed = await client.post(
            "/api/import/ebook",
            data={
                "duplicate_strategy": "skip",
                "confirmed_existing_book_id": str(first.json()["book_id"]),
            },
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    safe_detail = "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
    assert first.status_code == 200
    assert missing.status_code == 409
    assert missing.json()["detail"] == safe_detail
    assert mismatched.status_code == 409
    assert mismatched.json()["detail"] == safe_detail
    assert confirmed.status_code == 200


@pytest.mark.asyncio
async def test_confirmed_existing_ebook_job_is_created_only_after_staged_preflight(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        preview = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        upload_id = preview.json()["upload_id"]
        missing = await client.post(
            "/api/import/ebook/job",
            data={"duplicate_strategy": "skip", "upload_id": upload_id},
            headers=headers,
        )
        mismatched = await client.post(
            "/api/import/ebook/job",
            data={
                "duplicate_strategy": "skip",
                "upload_id": upload_id,
                "confirmed_existing_book_id": str(first.json()["book_id"] + 1),
            },
            headers=headers,
        )

        tracker = get_shared_job_tracker(override_ebook_service.db_path)
        assert tracker.list_jobs() == []
        upload_dir = override_ebook_service.data_dir / "import_uploads"
        assert (upload_dir / f"{upload_id}.epub").exists()
        assert (upload_dir / f"{upload_id}.json").exists()
        books_before_confirmed_import = list_books(override_ebook_service.db_path)

        confirmed = await client.post(
            "/api/import/ebook/job",
            data={
                "duplicate_strategy": "skip",
                "upload_id": upload_id,
                "confirmed_existing_book_id": str(first.json()["book_id"]),
            },
            headers=headers,
        )

    safe_detail = "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
    assert first.status_code == 200
    assert preview.status_code == 200
    assert missing.status_code == 409
    assert missing.json()["detail"] == safe_detail
    assert mismatched.status_code == 409
    assert mismatched.json()["detail"] == safe_detail
    assert all(
        forbidden not in missing.text
        for forbidden in ("/home/", "/mnt/", "traceback", "Đấu khí, ba đoạn!")
    )
    assert confirmed.status_code == 200
    job = tracker.get_job(confirmed.json()["job_id"])
    assert job is not None
    assert job.params["confirmed_existing_book_id"] == first.json()["book_id"]
    for _ in range(100):
        job = tracker.get_job(confirmed.json()["job_id"])
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert job is not None
    assert job.status == "completed"
    books_after_confirmed_import = list_books(override_ebook_service.db_path)
    assert len(books_after_confirmed_import) == 1
    assert [
        (book["id"], book["book_key"])
        for book in books_after_confirmed_import
    ] == [
        (book["id"], book["book_key"])
        for book in books_before_confirmed_import
    ]
    assert books_after_confirmed_import[0]["book_key"] == "đấupháthươngkhung"


@pytest.mark.asyncio
async def test_new_title_preview_race_requires_confirmation_before_any_import_mutation(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        preview = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["dry_run"]["book_match_reason"] == "new"
        upload_id = preview.json()["upload_id"]

        raced_book_id = add_book(
            override_ebook_service.db_path,
            "Đấu Phá Thương Khung",
            "Thiên Tằm Thổ Đậu",
            "manual",
        )
        artifact_root = override_ebook_service.data_dir
        artifacts_before = sorted(
            path.relative_to(artifact_root).as_posix()
            for path in artifact_root.rglob("*")
            if path.is_file()
        )
        chapters_before = list_chapters(override_ebook_service.db_path, raced_book_id)
        history_before = list_ebook_import_runs(override_ebook_service.db_path)

        conflict = await client.post(
            "/api/import/ebook/job",
            data={"duplicate_strategy": "skip", "upload_id": upload_id},
            headers=headers,
        )

    safe_detail = "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == safe_detail
    assert list_chapters(override_ebook_service.db_path, raced_book_id) == chapters_before == []
    assert list_ebook_import_runs(override_ebook_service.db_path) == history_before == []
    assert sorted(
        path.relative_to(artifact_root).as_posix()
        for path in artifact_root.rglob("*")
        if path.is_file()
    ) == artifacts_before
    assert get_shared_job_tracker(override_ebook_service.db_path).list_jobs() == []


@pytest.mark.asyncio
async def test_confirmed_existing_ebook_job_conflict_cleans_direct_upload_temp(
    override_ebook_service: EbookImportService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(upload_limits.tempfile, "tempdir", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        conflict = await client.post(
            "/api/import/ebook/job",
            data={"duplicate_strategy": "skip"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert not list(tmp_path.glob("novel-ebook-*"))


@pytest.mark.asyncio
async def test_existing_inbox_ebook_job_conflict_is_safe_and_retains_source(
    override_ebook_service: EbookImportService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inbox_dir = tmp_path / "inbox" / "ebooks"
    inbox_dir.mkdir(parents=True)
    inbox_path = inbox_dir / "translated-from-inbox.epub"
    write_minimal_epub(inbox_path)
    monkeypatch.setenv("EBOOK_INBOX_DIR", str(inbox_dir))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            "/api/import/ebook",
            data={"inbox_file": inbox_path.name, "duplicate_strategy": "error"},
            headers=headers,
        )
        conflict = await client.post(
            "/api/import/ebook/job",
            data={"inbox_file": inbox_path.name, "duplicate_strategy": "skip"},
            headers=headers,
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
    )
    assert inbox_path.exists()
    assert all(
        forbidden not in conflict.text
        for forbidden in ("/home/", "/mnt/", "traceback", "Đấu khí, ba đoạn!")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["staged", "direct", "inbox"])
async def test_background_target_race_preserves_recovery_source_and_reports_confirmation_conflict(
    source_kind: str,
    override_ebook_service: EbookImportService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = override_ebook_service
    entered_background_import = threading.Event()
    release_background_import = threading.Event()
    original_import = service.import_translated_ebook

    def import_after_barrier(*args, **kwargs):  # type: ignore[no-untyped-def]
        entered_background_import.set()
        assert release_background_import.wait(timeout=5)
        return original_import(*args, **kwargs)

    monkeypatch.setattr(service, "import_translated_ebook", import_after_barrier)
    monkeypatch.setattr(upload_limits.tempfile, "tempdir", str(tmp_path))

    inbox_path = tmp_path / "inbox" / "ebooks" / "translated-race.epub"
    if source_kind == "inbox":
        inbox_path.parent.mkdir(parents=True)
        write_minimal_epub(inbox_path)
        monkeypatch.setenv("EBOOK_INBOX_DIR", str(inbox_path.parent))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        upload_id = ""
        if source_kind == "staged":
            preview = await client.post(
                "/api/import/ebook/preview",
                files={"file": ("translated-race.epub", minimal_epub_bytes(), "application/epub+zip")},
                headers=headers,
            )
            assert preview.status_code == 200
            upload_id = preview.json()["upload_id"]
            response = await client.post(
                "/api/import/ebook/job",
                data={"duplicate_strategy": "skip", "upload_id": upload_id},
                headers=headers,
            )
        elif source_kind == "inbox":
            response = await client.post(
                "/api/import/ebook/job",
                data={"duplicate_strategy": "skip", "inbox_file": inbox_path.name},
                headers=headers,
            )
        else:
            response = await client.post(
                "/api/import/ebook/job",
                data={"duplicate_strategy": "skip"},
                files={"file": ("translated-race.epub", minimal_epub_bytes(), "application/epub+zip")},
                headers=headers,
            )

        assert response.status_code == 200
        assert await asyncio.to_thread(entered_background_import.wait, 5)

        raced_book_id = add_book(
            service.db_path,
            "Đấu Phá Thương Khung",
            "Thiên Tằm Thổ Đậu",
            "manual",
        )
        release_background_import.set()

    tracker = get_shared_job_tracker(service.db_path)
    job_id = response.json()["job_id"]
    job = None
    for _ in range(200):
        job = tracker.get_job(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)

    safe_detail = "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
    assert job is not None
    assert job.status == "failed"
    assert job.error == safe_detail
    assert job.message == safe_detail
    expected_source = {"staged": "preview_upload", "direct": "upload", "inbox": "inbox"}[source_kind]
    assert job.params["source"] == expected_source
    assert job.params["original_filename"] == "translated-race.epub"
    assert list_chapters(service.db_path, raced_book_id) == []
    assert list_ebook_import_runs(service.db_path) == []
    assert not list((service.data_dir / "raw").glob("*"))

    if source_kind == "inbox":
        assert inbox_path.exists()
        assert job.params["retry_inbox_file"] == inbox_path.name
        assert "retry_upload_id" not in job.params
    else:
        retry_upload_id = job.params["retry_upload_id"]
        if source_kind == "staged":
            assert retry_upload_id == upload_id
        retry_path, retry_name = import_routes._resolve_staged_ebook_upload(service, retry_upload_id)
        assert retry_path.exists()
        assert retry_name == "translated-race.epub"

    assert all(
        forbidden not in f"{job.error} {job.message}"
        for forbidden in ("/home/", "/mnt/", "traceback", "Đấu khí, ba đoạn!")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["staged", "direct", "inbox"])
async def test_background_non_confirmation_failure_keeps_existing_source_cleanup_rules(
    source_kind: str,
    override_ebook_service: EbookImportService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = override_ebook_service
    source_path = tmp_path / f"{source_kind}.epub"
    write_minimal_epub(source_path)
    cleanup_upload_id = ""
    cleanup_temp_path = source_kind == "direct"
    if source_kind == "staged":
        cleanup_upload_id = _stage_ebook_upload(service, source_path, source_path.name)
        source_path, _ = import_routes._resolve_staged_ebook_upload(service, cleanup_upload_id)

    def fail_import(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("ordinary ebook validation failure")

    monkeypatch.setattr(service, "import_translated_ebook", fail_import)
    tracker = get_shared_job_tracker(service.db_path)
    job = tracker.create_job("import_ebook", [], 1, {"source": source_kind})

    await import_routes._run_translated_ebook_import_job(
        job_id=job.job_id,
        tracker=tracker,
        service=service,
        ebook_path=source_path,
        original_name=f"{source_kind}.epub",
        target_book_id=None,
        duplicate_strategy="skip",
        split_mode="auto",
        confirmed_existing_book_id=None,
        cleanup_upload_id=cleanup_upload_id,
        cleanup_temp_path=cleanup_temp_path,
    )

    failed_job = tracker.get_job(job.job_id)
    assert failed_job is not None
    assert failed_job.status == "failed"
    assert failed_job.error == (
        "Translated ebook import failed. Check duplicate settings, ebook file, and server logs."
    )
    if source_kind == "inbox":
        assert source_path.exists()
    else:
        assert not source_path.exists()
    assert not list((service.data_dir / "import_uploads").glob("*"))


@pytest.mark.asyncio
async def test_ebook_preview_endpoint_reports_duplicate_dry_run_after_import(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        imported = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        preview = await client.post(
            "/api/import/ebook/preview",
            data={"duplicate_strategy": "overwrite"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )

    assert imported.status_code == 200
    assert preview.status_code == 200
    dry_run = preview.json()["dry_run"]
    assert dry_run["duplicate_chapters"] == 1
    assert dry_run["would_overwrite"] == 1
    assert dry_run["would_import"] == 1


@pytest.mark.asyncio
async def test_ebook_import_history_endpoint_lists_recent_runs(
    override_ebook_service: EbookImportService,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        imported = await client.post(
            "/api/import/ebook",
            data={"duplicate_strategy": "skip"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")},
            headers=headers,
        )
        history = await client.get("/api/import/ebook/history", headers=headers)

    assert imported.status_code == 200
    assert history.status_code == 200
    runs = history.json()["runs"]
    assert runs[0]["filename"] == "translated.epub"
    assert runs[0]["imported_chapters"] == 1
    assert runs[0]["skipped_chapters"] == 0
