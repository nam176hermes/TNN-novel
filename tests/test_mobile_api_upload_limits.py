from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, get_book_by_id, init_db
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import books as books_router
from app.mobile_api.routers import import_routes
from app.mobile_api.services.ebook_import_service import EbookImportService
from app.mobile_api.services.pipeline_service import PipelineService
from tests.test_mobile_api_import_ebook import minimal_epub_bytes


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


@pytest.fixture
def override_import_pipeline(temp_pipeline: PipelineService):
    app.dependency_overrides[import_routes.get_pipeline] = lambda: temp_pipeline
    try:
        yield temp_pipeline
    finally:
        app.dependency_overrides.pop(import_routes.get_pipeline, None)


@pytest.fixture
def override_ebook_service(temp_db_path: Path, tmp_path: Path) -> EbookImportService:
    init_db(temp_db_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    app.dependency_overrides[import_routes.get_ebook_import_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(import_routes.get_ebook_import_service, None)


@pytest.fixture
def set_upload_limit():
    original = getattr(mobile_settings, "upload_max_bytes", None)

    def apply(limit: int) -> None:
        object.__setattr__(mobile_settings, "upload_max_bytes", limit)

    yield apply

    if original is None:
        try:
            object.__delattr__(mobile_settings, "upload_max_bytes")
        except AttributeError:
            pass
    else:
        object.__setattr__(mobile_settings, "upload_max_bytes", original)


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_raw_text_upload_rejects_oversized_file_without_partial_import(
    override_import_pipeline: PipelineService,
    set_upload_limit,
) -> None:
    set_upload_limit(8)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/file",
            files={"file": ("chapter.txt", b"123456789", "text/plain")},
            headers=headers,
        )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()
    assert list((override_import_pipeline.data_dir / "raw").glob("upload_*")) == []


@pytest.mark.asyncio
async def test_raw_text_upload_limit_is_configurable(
    override_import_pipeline: PipelineService,
    set_upload_limit,
) -> None:
    set_upload_limit(1024)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/file",
            data={"title": "Small Upload", "chapter_number": "1", "chapter_title": "Chương 1"},
            files={"file": ("chapter.txt", "Thiếu niên vào núi.", "text/plain")},
            headers=headers,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ebook_upload_rejects_oversized_file_and_does_not_stage_upload(
    override_ebook_service: EbookImportService,
    set_upload_limit,
) -> None:
    payload = minimal_epub_bytes()
    set_upload_limit(len(payload) - 1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/import/ebook/preview",
            files={"file": ("translated.epub", payload, "application/epub+zip")},
            headers=headers,
        )

    assert response.status_code == 413
    upload_dir = override_ebook_service.data_dir / "import_uploads"
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_cover_upload_rejects_oversized_file_without_updating_book(
    override_books_pipeline: PipelineService,
    set_upload_limit,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Cover Limit")
    set_upload_limit(4)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/cover",
            files={"cover": ("cover.jpg", b"12345", "image/jpeg")},
            headers=headers,
        )

    assert response.status_code == 413
    book = get_book_by_id(override_books_pipeline.db_path, book_id)
    assert book is not None
    assert book["cover_path"] == ""
    assert list((override_books_pipeline.data_dir / "covers").glob("*")) == []


@pytest.mark.asyncio
async def test_dictionary_upload_rejects_oversized_file_without_partial_pack(
    override_books_pipeline: PipelineService,
    set_upload_limit,
) -> None:
    set_upload_limit(8)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            "/api/reader/dictionaries",
            files={"file": ("custom.u8", b"# too long", "text/plain")},
            headers=headers,
        )

    assert response.status_code == 413
    assert list((override_books_pipeline.data_dir / "dictionaries").glob("*")) == []
