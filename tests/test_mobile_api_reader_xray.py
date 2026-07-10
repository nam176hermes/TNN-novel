from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import (
    add_book,
    add_chapter,
    add_reader_entity,
    add_reader_entity_mention,
    add_reader_timeline_event,
    init_db,
    put_glossary_term,
)
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import books as books_router
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


def seed_xray_data(pipeline: PipelineService) -> tuple[int, int, int, int]:
    book_id = add_book(pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_1_id = add_chapter(pipeline.db_path, book_id, 1, "Sơn biên tiểu thôn")
    chapter_2_id = add_chapter(pipeline.db_path, book_id, 2, "Thanh Ngưu trấn")
    chapter_3_id = add_chapter(pipeline.db_path, book_id, 3, "Thất Huyền Môn")

    han_lap = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Hàn Lập",
        aliases=["韓立"],
        description="Nhân vật chính.",
        first_chapter_number=1,
        importance=100,
    )
    future_character = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Lệ Phi Vũ",
        description="Nhân vật xuất hiện ở chương sau.",
        first_chapter_number=3,
        importance=80,
    )
    realm = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="realm",
        name="Trúc Cơ",
        aliases=["筑基"],
        description="Cảnh giới tu luyện.",
        first_chapter_number=1,
        importance=70,
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=han_lap["id"],
        chapter_id=chapter_1_id,
        chapter_number=1,
        paragraph_index=0,
        mention_text="Hàn Lập",
        context="Hàn Lập rời thôn.",
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=realm["id"],
        chapter_id=chapter_2_id,
        chapter_number=2,
        paragraph_index=2,
        mention_text="Trúc Cơ",
        context="Hắn nghe nói tới Trúc Cơ.",
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=future_character["id"],
        chapter_id=chapter_3_id,
        chapter_number=3,
        paragraph_index=1,
        mention_text="Lệ Phi Vũ",
        context="Lệ Phi Vũ xuất hiện.",
    )
    add_reader_timeline_event(
        pipeline.db_path,
        book_id=book_id,
        chapter_id=chapter_1_id,
        chapter_number=1,
        event_order=1,
        title="Hàn Lập rời thôn",
        summary="Hàn Lập bắt đầu rời Sơn biên tiểu thôn.",
        entities=["Hàn Lập"],
    )
    add_reader_timeline_event(
        pipeline.db_path,
        book_id=book_id,
        chapter_id=chapter_3_id,
        chapter_number=3,
        event_order=1,
        title="Lệ Phi Vũ xuất hiện",
        summary="Một nhân vật mới bước vào tuyến truyện.",
        entities=["Lệ Phi Vũ"],
    )
    return book_id, chapter_1_id, chapter_2_id, chapter_3_id


def seed_xray_graph_data(pipeline: PipelineService) -> tuple[int, int]:
    book_id = add_book(pipeline.db_path, "Đại Đạo Độc Hành")
    chapter_1_id = add_chapter(pipeline.db_path, book_id, 1, "Nhập môn")
    chapter_2_id = add_chapter(pipeline.db_path, book_id, 2, "Trúc Cơ")
    chapter_3_id = add_chapter(pipeline.db_path, book_id, 3, "Ngoại viện")

    han_lap = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Hàn Lập",
        description="Đệ tử mới nhập môn.",
        first_chapter_number=1,
        importance=100,
        metadata={
            "faction": "Thất Huyền Môn",
            "power_rank": 20,
            "power_label": "Trúc Cơ sơ kỳ",
            "power_basis": "Được trưởng lão xác nhận đã chạm ngưỡng Trúc Cơ.",
            "relationships": [
                {
                    "target": "Trúc Cơ",
                    "relation": "cảnh giới hiện tại",
                    "evidence": "Hàn Lập được trưởng lão nhắc tới ngưỡng Trúc Cơ.",
                    "chapter_number": 2,
                    "strength": 0.9,
                }
            ],
        },
    )
    faction = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="faction",
        name="Thất Huyền Môn",
        description="Tông môn thu nhận đệ tử ngoại viện.",
        first_chapter_number=1,
        importance=85,
        metadata={"parent": "Việt Quốc tu tiên giới"},
    )
    realm = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="realm",
        name="Trúc Cơ",
        description="Cảnh giới đặt nền móng tu luyện.",
        first_chapter_number=2,
        importance=70,
        metadata={"order": 2},
    )
    future_character = add_reader_entity(
        pipeline.db_path,
        book_id=book_id,
        entity_type="character",
        name="Lệ Phi Vũ",
        description="Đệ tử xuất hiện sau.",
        first_chapter_number=3,
        importance=60,
        metadata={"faction": "Thất Huyền Môn", "power_rank": 10, "power_label": "Luyện Khí"},
    )

    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=han_lap["id"],
        chapter_id=chapter_1_id,
        chapter_number=1,
        paragraph_index=0,
        mention_text="Hàn Lập",
        context="Hàn Lập bái nhập Thất Huyền Môn.",
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=faction["id"],
        chapter_id=chapter_1_id,
        chapter_number=1,
        paragraph_index=0,
        mention_text="Thất Huyền Môn",
        context="Hàn Lập bái nhập Thất Huyền Môn.",
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=realm["id"],
        chapter_id=chapter_2_id,
        chapter_number=2,
        paragraph_index=1,
        mention_text="Trúc Cơ",
        context="Trưởng lão nói Hàn Lập đã chạm ngưỡng Trúc Cơ.",
    )
    add_reader_entity_mention(
        pipeline.db_path,
        book_id=book_id,
        entity_id=future_character["id"],
        chapter_id=chapter_3_id,
        chapter_number=3,
        paragraph_index=0,
        mention_text="Lệ Phi Vũ",
        context="Lệ Phi Vũ được phân tới ngoại viện.",
    )

    add_reader_timeline_event(
        pipeline.db_path,
        book_id=book_id,
        chapter_id=chapter_1_id,
        chapter_number=1,
        event_order=1,
        title="Hàn Lập nhập môn",
        summary="Hàn Lập chính thức gia nhập Thất Huyền Môn.",
        entities=["Hàn Lập", "Thất Huyền Môn"],
    )
    add_reader_timeline_event(
        pipeline.db_path,
        book_id=book_id,
        chapter_id=chapter_2_id,
        chapter_number=2,
        event_order=1,
        title="Chạm ngưỡng Trúc Cơ",
        summary="Trưởng lão nhận ra căn cơ của Hàn Lập đã gần Trúc Cơ.",
        entities=["Hàn Lập", "Trúc Cơ"],
    )

    return book_id, chapter_2_id


@pytest.mark.asyncio
async def test_reader_xray_no_spoiler_hides_future_chapters(
    override_books_pipeline: PipelineService,
) -> None:
    book_id, _, chapter_2_id, _ = seed_xray_data(override_books_pipeline)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/reader/xray",
            params={"chapter_id": chapter_2_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["spoiler_mode"] == "no_spoiler"
    assert data["current_chapter_number"] == 2
    entity_names = {item["name"] for item in data["entities"]}
    assert entity_names == {"Hàn Lập", "Trúc Cơ"}
    assert all(mention["chapter_number"] <= 2 for item in data["entities"] for mention in item["mentions"])
    assert [event["title"] for event in data["timeline"]] == ["Hàn Lập rời thôn"]
    assert "Lệ Phi Vũ" not in str(data)


@pytest.mark.asyncio
async def test_reader_xray_allow_spoiler_shows_whole_book(
    override_books_pipeline: PipelineService,
) -> None:
    book_id, _, chapter_2_id, _ = seed_xray_data(override_books_pipeline)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/reader/xray",
            params={"chapter_id": chapter_2_id, "spoiler_mode": "allow_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["spoiler_mode"] == "allow_spoiler"
    entity_names = {item["name"] for item in data["entities"]}
    assert {"Hàn Lập", "Trúc Cơ", "Lệ Phi Vũ"} <= entity_names
    assert "Lệ Phi Vũ xuất hiện" in [event["title"] for event in data["timeline"]]


@pytest.mark.asyncio
async def test_reader_xray_returns_relationships_faction_tree_and_power_rankings(
    override_books_pipeline: PipelineService,
) -> None:
    book_id, chapter_2_id = seed_xray_graph_data(override_books_pipeline)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/reader/xray",
            params={"chapter_id": chapter_2_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()

    assert data["relationships"][0] == {
        "source": "Hàn Lập",
        "target": "Trúc Cơ",
        "relation": "cảnh giới hiện tại",
        "evidence": "Hàn Lập được trưởng lão nhắc tới ngưỡng Trúc Cơ.",
        "chapter_number": 2,
        "strength": 0.9,
        "source_type": "metadata",
    }
    assert data["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Tông môn thu nhận đệ tử ngoại viện.",
            "parent": "Việt Quốc tu tiên giới",
            "first_chapter_number": 1,
            "members": ["Hàn Lập"],
            "children": [],
        }
    ]
    assert data["power_rankings"] == [
        {
            "name": "Hàn Lập",
            "type": "character",
            "rank": 20,
            "label": "Trúc Cơ sơ kỳ",
            "basis": "Được trưởng lão xác nhận đã chạm ngưỡng Trúc Cơ.",
            "chapter_number": 1,
            "faction": "Thất Huyền Môn",
        }
    ]
    assert "Lệ Phi Vũ" not in str(data["faction_tree"])
    assert "Lệ Phi Vũ" not in str(data["power_rankings"])


@pytest.mark.asyncio
async def test_reader_xray_enrich_uses_ai_payload_to_update_graph(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id, _, chapter_2_id, _ = seed_xray_data(override_books_pipeline)
    calls: list[str] = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs["prompt"])
        return """
        {
          "relationships": [
            {
              "source": "Hàn Lập",
              "target": "Trúc Cơ",
              "relation": "đang hướng tới cảnh giới",
              "evidence": "Hắn nghe nói tới Trúc Cơ.",
              "chapter_number": 2,
              "strength": 0.82
            }
          ],
          "factions": [
            {
              "name": "Thất Huyền Môn",
              "description": "Môn phái đang quan sát căn cơ của Hàn Lập.",
              "parent": "Việt Quốc tu tiên giới",
              "members": ["Hàn Lập"],
              "chapter_number": 2
            }
          ],
          "power_rankings": [
            {
              "name": "Hàn Lập",
              "rank": 12,
              "label": "Luyện Khí hậu kỳ",
              "basis": "Chưa Trúc Cơ nhưng đã có căn cơ ổn định.",
              "faction": "Thất Huyền Môn"
            }
          ],
          "timeline": [
            {
              "chapter_number": 2,
              "event_order": 2,
              "title": "Manh mối Trúc Cơ",
              "summary": "Hàn Lập biết tới con đường Trúc Cơ.",
              "entities": ["Hàn Lập", "Trúc Cơ"]
            }
          ]
        }
        """

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/xray/enrich",
            json={"chapter_id": chapter_2_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert calls
    assert "relationship graph" in calls[0]
    assert data["relationships"][0]["source_type"] == "ai"
    assert data["relationships"][0]["relation"] == "đang hướng tới cảnh giới"
    assert data["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Môn phái đang quan sát căn cơ của Hàn Lập.",
            "parent": "Việt Quốc tu tiên giới",
            "first_chapter_number": 2,
            "members": ["Hàn Lập"],
            "children": [],
        }
    ]
    assert data["power_rankings"][0]["label"] == "Luyện Khí hậu kỳ"
    assert "Manh mối Trúc Cơ" in [event["title"] for event in data["timeline"]]


@pytest.mark.asyncio
async def test_reader_xray_enrich_materializes_nested_ai_faction_tree(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id, _, chapter_2_id, _ = seed_xray_data(override_books_pipeline)

    def fake_call_llm(**_kwargs):
        return """
        {
          "factions": [
            {
              "name": "Việt Quốc tu tiên giới",
              "description": "Thế lực bao trùm các môn phái tu tiên tại Việt Quốc.",
              "chapter_number": 2,
              "children": [
                {
                  "name": "Thất Huyền Môn",
                  "description": "Môn phái đang tiếp nhận Hàn Lập.",
                  "members": ["Hàn Lập"],
                  "chapter_number": 2
                },
                "Ngoại viện"
              ]
            }
          ]
        }
        """

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/reader/xray/enrich",
            json={"chapter_id": chapter_2_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    faction_tree = response.json()["faction_tree"]
    names = {item["name"] for item in faction_tree}
    assert {"Việt Quốc tu tiên giới", "Thất Huyền Môn", "Ngoại viện"} <= names
    parent = next(item for item in faction_tree if item["name"] == "Việt Quốc tu tiên giới")
    child = next(item for item in faction_tree if item["name"] == "Thất Huyền Môn")
    string_child = next(item for item in faction_tree if item["name"] == "Ngoại viện")

    assert parent["children"] == ["Ngoại viện", "Thất Huyền Môn"]
    assert child["parent"] == "Việt Quốc tu tiên giới"
    assert child["members"] == ["Hàn Lập"]
    assert string_child["parent"] == "Việt Quốc tu tiên giới"


def test_reader_xray_auto_ai_enriches_graph_when_provider_is_configured(
    temp_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Auto AI X-Ray")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Nhập môn")
    assert temp_pipeline.update_chapter_translation(
        chapter_id,
        "Hàn Lập bái nhập Thất Huyền Môn, Mặc Cư Nhân âm thầm quan sát căn cốt của hắn.",
    )
    monkeypatch.setattr(
        temp_pipeline,
        "_reader_ai_provider_options",
        lambda: {
            "provider_id": "test-ai",
            "model": "reader-xray-test",
            "host": "https://example.invalid",
            "api_key": "test",
        },
    )
    monkeypatch.setenv("READER_XRAY_AUTO_AI", "1")
    calls: list[str] = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs["task_type"])
        return """
        {
          "relationships": [
            {
              "source": "Hàn Lập",
              "target": "Mặc Cư Nhân",
              "relation": "được quan sát căn cốt",
              "evidence": "Mặc Cư Nhân âm thầm quan sát căn cốt của hắn.",
              "chapter_number": 1,
              "strength": 0.9
            }
          ],
          "factions": [
            {
              "name": "Thất Huyền Môn",
              "description": "Môn phái Hàn Lập vừa bái nhập.",
              "members": ["Hàn Lập", "Mặc Cư Nhân"],
              "chapter_number": 1
            }
          ],
          "power_rankings": [
            {
              "name": "Mặc Cư Nhân",
              "rank": 1,
              "label": "Y sư thần bí",
              "basis": "Có quyền quan sát căn cốt người mới.",
              "faction": "Thất Huyền Môn"
            }
          ],
          "timeline": [
            {
              "chapter_number": 1,
              "event_order": 2,
              "title": "Hàn Lập nhập Thất Huyền Môn",
              "summary": "Hàn Lập bái nhập môn phái và bị Mặc Cư Nhân để mắt.",
              "entities": ["Hàn Lập", "Mặc Cư Nhân", "Thất Huyền Môn"]
            }
          ]
        }
        """

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    assert calls == ["reader_xray_auto_enrich"]
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Mặc Cư Nhân"
        and relationship["source_type"] == "ai"
        for relationship in xray["relationships"]
    )
    assert xray["faction_tree"][0]["name"] == "Thất Huyền Môn"
    assert xray["power_rankings"][0]["name"] == "Mặc Cư Nhân"
    assert "Hàn Lập nhập Thất Huyền Môn" in [event["title"] for event in xray["timeline"]]


def test_reader_xray_auto_ai_enriches_each_chapter_once(
    temp_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Auto AI X-Ray nhiều chương")
    chapter_1_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Nhập môn")
    chapter_2_id = add_chapter(temp_pipeline.db_path, book_id, 2, "Gặp đồng môn")
    assert temp_pipeline.update_chapter_translation(
        chapter_1_id,
        "Hàn Lập bái nhập Thất Huyền Môn, Mặc Cư Nhân âm thầm quan sát căn cốt.",
    )
    assert temp_pipeline.update_chapter_translation(
        chapter_2_id,
        "Hàn Lập gặp Lệ Phi Vũ, hai người cùng luyện kiếm dưới chân núi.",
    )
    monkeypatch.setattr(
        temp_pipeline,
        "_reader_ai_provider_options",
        lambda: {
            "provider_id": "test-ai",
            "model": "reader-xray-test",
            "host": "https://example.invalid",
            "api_key": "test",
        },
    )
    monkeypatch.setenv("READER_XRAY_AUTO_AI", "1")
    calls: list[int] = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs["chapter_id"])
        if kwargs["chapter_id"] == chapter_1_id:
            return """
            {
              "relationships": [
                {
                  "source": "Hàn Lập",
                  "target": "Mặc Cư Nhân",
                  "relation": "được quan sát căn cốt",
                  "evidence": "Mặc Cư Nhân âm thầm quan sát căn cốt.",
                  "chapter_number": 1
                }
              ]
            }
            """
        return """
        {
          "relationships": [
            {
              "source": "Hàn Lập",
              "target": "Lệ Phi Vũ",
              "relation": "gặp đồng môn",
              "evidence": "Hai người cùng luyện kiếm dưới chân núi.",
              "chapter_number": 2
            }
          ],
          "timeline": [
            {
              "chapter_number": 2,
              "event_order": 2,
              "title": "Hàn Lập gặp Lệ Phi Vũ",
              "summary": "Hàn Lập gặp đồng môn và cùng luyện kiếm.",
              "entities": ["Hàn Lập", "Lệ Phi Vũ"]
            }
          ]
        }
        """

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    first_xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_1_id, spoiler_mode="no_spoiler")
    second_xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_2_id, spoiler_mode="no_spoiler")
    second_xray_again = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_2_id, spoiler_mode="no_spoiler")

    assert first_xray is not None
    assert second_xray is not None
    assert calls == [chapter_1_id, chapter_2_id]
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Lệ Phi Vũ"
        and relationship["relation"] == "gặp đồng môn"
        and relationship["source_type"] == "ai"
        for relationship in second_xray["relationships"]
    )
    assert "Hàn Lập gặp Lệ Phi Vũ" in [event["title"] for event in second_xray["timeline"]]
    assert second_xray_again is not None


@pytest.mark.asyncio
async def test_reader_xray_auto_extracts_from_translated_chapter(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Auto X-Ray")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 1, "Gặp tiên duyên")
    put_glossary_term(
        override_books_pipeline.db_path,
        book_id,
        "筑基",
        "Trúc Cơ",
        category="realm",
        mode="translate",
    )
    assert override_books_pipeline.update_chapter_translation(
        chapter_id,
        (
            "Hàn Lập rời sơn thôn, trên đường nghe trưởng lão nhắc tới Trúc Cơ.\n\n"
            "Đến Thanh Vân Tông, Hàn Lập được giao một ngọc giản cũ."
        ),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/reader/xray",
            params={"chapter_id": chapter_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    entity_names = {item["name"] for item in data["entities"]}
    assert {"Hàn Lập", "Trúc Cơ", "Thanh Vân Tông"} <= entity_names
    assert any(item["mentions"] for item in data["entities"])
    assert data["timeline"]
    assert data["timeline"][0]["title"] == "Gặp tiên duyên"
    assert "Hàn Lập" in data["timeline"][0]["entities"]


@pytest.mark.asyncio
async def test_reader_xray_rejects_chapter_from_another_book(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Book A")
    other_book_id = add_book(override_books_pipeline.db_path, "Book B")
    other_chapter_id = add_chapter(override_books_pipeline.db_path, other_book_id, 1, "Wrong chapter")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.get(
            f"/api/books/{book_id}/reader/xray",
            params={"chapter_id": other_chapter_id, "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 404
