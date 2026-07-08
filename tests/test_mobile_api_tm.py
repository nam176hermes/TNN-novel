from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, init_db
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import glossary as glossary_router
from app.mobile_api.services.glossary_service import GlossaryService


def make_glossary_service(db_path: Path) -> GlossaryService:
    service = object.__new__(GlossaryService)
    service.db_path = db_path
    return service


@pytest.fixture
def override_glossary_service(temp_db_path: Path) -> GlossaryService:
    init_db(temp_db_path)
    service = make_glossary_service(temp_db_path)
    app.dependency_overrides[glossary_router.get_glossary_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(glossary_router.get_glossary_service, None)


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
async def test_translation_memory_api_add_search_and_clear(
    override_glossary_service: GlossaryService,
) -> None:
    book_id = add_book(override_glossary_service.db_path, "Book")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        add_response = await client.post(
            "/api/glossary/tm",
            json={
                "source_text": "他拿起灵石。",
                "translation_text": "Hắn cầm linh thạch lên.",
                "score": 93,
                "book_id": book_id,
                "chapter_number": 1,
            },
            headers=headers,
        )
        search_response = await client.get(
            "/api/glossary/tm/search",
            params={"q": "他拿起灵石。", "threshold": 80},
            headers=headers,
        )
        clear_response = await client.delete("/api/glossary/tm", headers=headers)

    assert add_response.status_code == 201
    assert add_response.json()["id"] > 0
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["total"] == 1
    assert payload["results"][0]["translation_text"] == "Hắn cầm linh thạch lên."
    assert payload["results"][0]["match_score"] == 100
    assert payload["results"][0]["book_id"] == book_id
    assert payload["results"][0]["chapter_number"] == 1
    assert clear_response.status_code == 200
    assert clear_response.json()["deleted"] == 1
