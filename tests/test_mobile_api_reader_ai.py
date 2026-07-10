from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import add_book, add_chapter, init_db, put_glossary_term
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import books as books_router
from app.mobile_api.services.pipeline_service import PipelineService, _build_reader_xray_enrich_prompt


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
async def test_reader_ai_explain_returns_terms_and_uses_cache(
    override_books_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Độc Tu")
    chapter_id = add_chapter(override_books_pipeline.db_path, book_id, 19, "Tuyệt đối không thể phạm sai lầm")
    put_glossary_term(
        override_books_pipeline.db_path,
        book_id,
        "筑基",
        "Trúc Cơ",
        notes_vi="cảnh giới tu luyện",
        approved=1,
        mode="translate",
    )
    calls: list[str] = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs["prompt"])
        return (
            '{"explanation":"筑基 là cảnh giới đặt nền móng tu luyện.",'
            '"terms":[{"source":"筑基","target":"Trúc Cơ","note":"cảnh giới tu luyện"}]}'
        )

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    payload = {
        "text": "筑基",
        "context_before": "Hắn bế quan nhiều năm.",
        "context_after": "Linh khí trong động phủ cuồn cuộn.",
        "spoiler_mode": "no_spoiler",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/reader/explain",
            json=payload,
            headers=headers,
        )
        second = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/reader/explain",
            json={**payload, "context_after": "Khác ngữ cảnh nhưng cùng text và spoiler."},
            headers=headers,
        )

    assert first.status_code == 200
    assert first.json() == {
        "explanation": "筑基 là cảnh giới đặt nền móng tu luyện.",
        "terms": [
            {"source": "筑基", "target": "Trúc Cơ", "note": "thuật ngữ trong glossary"},
        ],
    }
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(calls) == 1
    assert "Không tiết lộ nội dung sau đoạn được chọn" in calls[0]


@pytest.mark.asyncio
async def test_reader_ai_explain_rejects_wrong_book_chapter(
    override_books_pipeline: PipelineService,
) -> None:
    book_id = add_book(override_books_pipeline.db_path, "Book A")
    other_book_id = add_book(override_books_pipeline.db_path, "Book B")
    other_chapter_id = add_chapter(override_books_pipeline.db_path, other_book_id, 1, "Wrong chapter")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        response = await client.post(
            f"/api/books/{book_id}/chapters/{other_chapter_id}/reader/explain",
            json={"text": "筑基", "spoiler_mode": "no_spoiler"},
            headers=headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Chapter not found"


def test_reader_xray_ai_timeline_upserts_new_entities_for_no_spoiler_graph(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Thất Huyền Môn")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "timeline": [
                {
                    "chapter_number": 1,
                    "event_order": 2,
                    "title": "Hàn Lập gặp Mặc Cư Nhân",
                    "summary": "Mặc Cư Nhân chú ý tới Hàn Lập trong Thất Huyền Môn.",
                    "entities": ["Hàn Lập", "Mặc Cư Nhân", "Thất Huyền Môn"],
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=1,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    entity_names = {entity["name"] for entity in xray["entities"]}
    assert {"Hàn Lập", "Mặc Cư Nhân", "Thất Huyền Môn"}.issubset(entity_names)
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Mặc Cư Nhân"
        and relationship["source_type"] == "timeline"
        for relationship in xray["relationships"]
    )


def test_reader_xray_ai_prompt_requests_entity_profiles() -> None:
    prompt = _build_reader_xray_enrich_prompt(
        book_title="Phàm Nhân Tu Tiên",
        chapter_number=3,
        spoiler_mode="no_spoiler",
        chapter_text="Hàn Lập nhập Thất Huyền Môn.",
        entities=[],
        timeline=[],
    )

    assert '"entities":[{"name":"Hàn Lập","type":"character","aliases":["Hàn tiểu tử"]' in prompt
    assert '"relationships":[{"target":"Mặc Cư Nhân","relation":"bị quan sát căn cốt"' in prompt
    assert '"faction":"Thất Huyền Môn"' in prompt
    assert '"power_label":"Luyện Khí sơ kỳ"' in prompt
    assert '"items":[{"name":"Thanh Trúc Phong Vân Kiếm","description":"pháp khí"' in prompt
    assert '"skills":[{"name":"Ngự Kiếm Thuật","description":"kiếm quyết"' in prompt
    assert '"realms":[{"name":"Luyện Khí","description":"cảnh giới nhập môn","order":1' in prompt


def test_reader_xray_ai_prompt_includes_existing_graph_context() -> None:
    prompt = _build_reader_xray_enrich_prompt(
        book_title="Phàm Nhân Tu Tiên",
        chapter_number=8,
        spoiler_mode="no_spoiler",
        chapter_text="Hàn Lập nghi ngờ Mặc Cư Nhân đang che giấu công pháp.",
        entities=[
            {
                "name": "Hàn Lập",
                "type": "character",
                "aliases": ["Hàn tiểu tử"],
                "description": "Thiếu niên cẩn trọng.",
                "first_chapter_number": 1,
                "metadata": {
                    "faction": "Thất Huyền Môn",
                    "power_rank": 12,
                    "power_label": "Luyện Khí sơ kỳ",
                    "relationships": [
                        {
                            "target": "Mặc Cư Nhân",
                            "relation": "nghi kỵ",
                            "evidence": "Hắn thấy lời nói của Mặc Cư Nhân có sơ hở.",
                            "chapter_number": 8,
                            "strength": 0.7,
                        }
                    ],
                },
                "mentions": [],
            },
            {
                "name": "Trúc Cơ",
                "type": "realm",
                "aliases": [],
                "description": "Cảnh giới đặt nền móng đạo cơ.",
                "first_chapter_number": 8,
                "metadata": {
                    "parent": "Tu tiên cảnh giới",
                    "order": 2,
                    "previous": "Luyện Khí",
                    "next": "Kết Đan",
                },
                "mentions": [],
            },
        ],
        timeline=[
            {
                "chapter_number": 8,
                "event_order": 3,
                "title": "Hàn Lập sinh nghi",
                "summary": "Hàn Lập bắt đầu đề phòng Mặc Cư Nhân.",
                "entities": ["Hàn Lập", "Mặc Cư Nhân"],
            }
        ],
    )

    assert '"relationships": [{"target": "Mặc Cư Nhân", "relation": "nghi kỵ"' in prompt
    assert '"parent": "Tu tiên cảnh giới"' in prompt
    assert '"order": 2' in prompt
    assert '"previous": "Luyện Khí"' in prompt
    assert '"event_order": 3' in prompt


def test_reader_xray_enrich_book_prompt_includes_multiple_chapter_contexts(
    temp_pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Độc Tu")
    chapter_1_id = add_chapter(temp_pipeline.db_path, book_id, 1, "Mưa trong cốc")
    chapter_2_id = add_chapter(temp_pipeline.db_path, book_id, 2, "Đèn đồng")
    assert temp_pipeline.update_chapter_translation(
        chapter_1_id,
        "một tiếng chuông cổ vang trong mưa.\n\nnét chữ trên bia đá mờ đi.",
    )
    assert temp_pipeline.update_chapter_translation(
        chapter_2_id,
        "đèn đồng trong mật thất tắt rồi lại sáng.\n\ncánh cửa đá khép kín sau lưng.",
    )

    prompts: list[str] = []

    monkeypatch.setattr(
        temp_pipeline,
        "_reader_ai_provider_options",
        lambda: {
            "api_key": "test-key",
            "host": "https://example.test/v1/chat/completions",
            "model": "test-model",
            "provider_id": "test-provider",
        },
    )

    def fake_call_llm(**kwargs):
        prompts.append(kwargs["prompt"])
        return '{"entities":[],"timeline":[]}'

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)

    result = temp_pipeline.enrich_reader_xray(book_id, spoiler_mode="allow_spoiler")

    assert result is not None
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "Chương 1: Mưa trong cốc\nmột tiếng chuông cổ vang trong mưa." in prompt
    assert "Chương 2: Đèn đồng\nđèn đồng trong mật thất tắt rồi lại sáng." in prompt
    assert prompt.index("Chương 1: Mưa trong cốc") < prompt.index("Chương 2: Đèn đồng")


def test_reader_xray_ai_faction_and_power_entities_are_visible_in_no_spoiler_graph(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 2, "Thất Huyền Môn")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "factions": [
                {
                    "name": "Thất Huyền Môn",
                    "description": "Môn phái kiểm tra căn cơ của đệ tử mới.",
                    "members": ["Mặc Cư Nhân"],
                    "chapter_number": 2,
                },
            ],
            "power_rankings": [
                {
                    "name": "Mặc Cư Nhân",
                    "rank": 30,
                    "label": "Y sư thần bí",
                    "basis": "Có địa vị vượt xa đệ tử mới.",
                    "faction": "Thất Huyền Môn",
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=2,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    assert any(entity["name"] == "Mặc Cư Nhân" for entity in xray["entities"])
    assert xray["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Môn phái kiểm tra căn cơ của đệ tử mới.",
            "parent": "",
            "first_chapter_number": 2,
            "members": ["Mặc Cư Nhân"],
            "children": [],
        }
    ]
    assert any(
        ranking["name"] == "Mặc Cư Nhân" and ranking["label"] == "Y sư thần bí"
        for ranking in xray["power_rankings"]
    )


def test_reader_xray_ai_entity_profiles_update_relationships_faction_and_power(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 3, "Thất Huyền Môn")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "entities": [
                {
                    "name": "Hàn Lập",
                    "type": "character",
                    "aliases": ["Hàn tiểu tử", "Lập nhi"],
                    "description": "Thiếu niên thận trọng, đang bị Mặc Cư Nhân quan sát căn cốt.",
                    "importance": 95,
                    "chapter_number": 3,
                    "faction": "Thất Huyền Môn",
                    "power_rank": 12,
                    "power_label": "Luyện Khí sơ kỳ",
                    "power_basis": "Đã cảm nhận được linh khí nhưng chưa Trúc Cơ.",
                    "relationships": [
                        {
                            "target": "Mặc Cư Nhân",
                            "relation": "bị quan sát căn cốt",
                            "evidence": "Mặc Cư Nhân âm thầm quan sát hắn.",
                            "strength": 0.9,
                        },
                    ],
                },
                {
                    "name": "Mặc Cư Nhân",
                    "type": "character",
                    "description": "Y sư thần bí của Thất Huyền Môn.",
                    "chapter_number": 3,
                    "faction": "Thất Huyền Môn",
                },
                {
                    "name": "Thất Huyền Môn",
                    "type": "faction",
                    "description": "Môn phái đang thu nhận và khảo sát đệ tử.",
                    "chapter_number": 3,
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=3,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="allow_spoiler")

    assert xray is not None
    han_lap = next(entity for entity in xray["entities"] if entity["name"] == "Hàn Lập")
    assert han_lap["aliases"] == ["Hàn tiểu tử", "Lập nhi"]
    assert "thận trọng" in han_lap["description"]
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Mặc Cư Nhân"
        and relationship["relation"] == "bị quan sát căn cốt"
        and relationship["source_type"] == "ai"
        for relationship in xray["relationships"]
    )
    assert xray["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Môn phái đang thu nhận và khảo sát đệ tử.",
            "parent": "",
            "first_chapter_number": 3,
            "members": ["Hàn Lập", "Mặc Cư Nhân"],
            "children": [],
        }
    ]
    assert any(
        ranking["name"] == "Hàn Lập"
        and ranking["label"] == "Luyện Khí sơ kỳ"
        and ranking["basis"] == "Đã cảm nhận được linh khí nhưng chưa Trúc Cơ."
        for ranking in xray["power_rankings"]
    )


def test_reader_xray_ai_items_skills_and_realms_are_visible_in_no_spoiler_graph(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 4, "Pháp bảo")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "items": [
                {
                    "name": "Thanh Trúc Phong Vân Kiếm",
                    "description": "Pháp khí mộc thuộc tính dùng để ngự kiếm.",
                    "owner": "Hàn Lập",
                    "category": "pháp khí",
                    "chapter_number": 4,
                },
            ],
            "skills": [
                {
                    "name": "Ngự Kiếm Thuật",
                    "description": "Kỹ pháp điều khiển phi kiếm từ xa.",
                    "user": "Hàn Lập",
                    "category": "kiếm quyết",
                    "chapter_number": 4,
                },
            ],
            "realms": [
                {
                    "name": "Luyện Khí",
                    "description": "Cảnh giới nhập môn của người tu tiên.",
                    "order": 1,
                    "chapter_number": 4,
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=4,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")
    xray_all = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="allow_spoiler")

    assert xray is not None
    assert xray_all is not None
    entities_by_name = {entity["name"]: entity for entity in xray["entities"]}
    all_entities_by_name = {entity["name"]: entity for entity in xray_all["entities"]}
    assert entities_by_name["Thanh Trúc Phong Vân Kiếm"]["type"] == "item"
    assert all_entities_by_name["Thanh Trúc Phong Vân Kiếm"]["metadata"]["owner"] == "Hàn Lập"
    assert entities_by_name["Ngự Kiếm Thuật"]["type"] == "skill"
    assert all_entities_by_name["Ngự Kiếm Thuật"]["metadata"]["user"] == "Hàn Lập"
    assert entities_by_name["Luyện Khí"]["type"] == "realm"
    assert all_entities_by_name["Luyện Khí"]["metadata"]["order"] == 1
    assert any(entity["name"] == "Thanh Trúc Phong Vân Kiếm" for entity in xray["entities"])
    assert any(entity["name"] == "Ngự Kiếm Thuật" for entity in xray["entities"])
    assert any(entity["name"] == "Luyện Khí" for entity in xray["entities"])
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Thanh Trúc Phong Vân Kiếm"
        and relationship["relation"] == "sở hữu"
        for relationship in xray["relationships"]
    )
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Ngự Kiếm Thuật"
        and relationship["relation"] == "tu luyện"
        for relationship in xray["relationships"]
    )


def test_reader_xray_ai_realm_hierarchy_creates_graph_relationships(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 5, "Cảnh giới")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "realms": [
                {
                    "name": "Luyện Khí",
                    "description": "Cảnh giới nhập môn của người tu tiên.",
                    "order": 1,
                    "next": "Trúc Cơ",
                    "chapter_number": 5,
                },
                {
                    "name": "Trúc Cơ",
                    "description": "Cảnh giới đặt nền móng đạo cơ.",
                    "order": 2,
                    "previous": "Luyện Khí",
                    "parent": "Tu tiên cảnh giới",
                    "chapter_number": 5,
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=5,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    assert any(entity["name"] == "Tu tiên cảnh giới" and entity["type"] == "realm" for entity in xray["entities"])
    assert any(
        relationship["source"] == "Luyện Khí"
        and relationship["target"] == "Trúc Cơ"
        and relationship["relation"] == "tiến tới cảnh giới"
        and relationship["source_type"] == "ai"
        for relationship in xray["relationships"]
    )
    assert any(
        relationship["source"] == "Trúc Cơ"
        and relationship["target"] == "Luyện Khí"
        and relationship["relation"] == "sau cảnh giới"
        for relationship in xray["relationships"]
    )
    assert any(
        relationship["source"] == "Trúc Cơ"
        and relationship["target"] == "Tu tiên cảnh giới"
        and relationship["relation"] == "thuộc hệ cảnh giới"
        for relationship in xray["relationships"]
    )


def test_reader_xray_ai_accepts_common_llm_graph_field_aliases(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 6, "Động phủ")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "relationship_graph": [
                {
                    "source": "Hàn Lập",
                    "target": "Mặc Cư Nhân",
                    "relation": "đề phòng",
                    "evidence": "Hàn Lập âm thầm cảnh giác Mặc Cư Nhân.",
                    "chapter_number": 6,
                },
            ],
            "faction_tree": [
                {
                    "name": "Thất Huyền Môn",
                    "description": "Môn phái có nhiều phân đường.",
                    "members": ["Hàn Lập"],
                    "chapter_number": 6,
                },
            ],
            "power_ranking": [
                {
                    "name": "Hàn Lập",
                    "rank": 18,
                    "label": "Luyện Khí sơ kỳ",
                    "basis": "Mới nhập môn, pháp lực còn mỏng.",
                    "faction": "Thất Huyền Môn",
                    "chapter_number": 6,
                },
            ],
            "realm_hierarchy": [
                {
                    "name": "Trúc Cơ",
                    "description": "Cảnh giới đặt nền móng đạo cơ.",
                    "order": 2,
                    "previous": "Luyện Khí",
                    "chapter_number": 6,
                },
            ],
            "timeline_events": [
                {
                    "chapter_number": 6,
                    "event_order": 1,
                    "title": "Hàn Lập vào động phủ",
                    "summary": "Hàn Lập bước vào động phủ và cảnh giác Mặc Cư Nhân.",
                    "entities": ["Hàn Lập", "Mặc Cư Nhân"],
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=6,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Mặc Cư Nhân"
        and relationship["relation"] == "đề phòng"
        for relationship in xray["relationships"]
    )
    assert xray["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Môn phái có nhiều phân đường.",
            "parent": "",
            "first_chapter_number": 6,
            "members": ["Hàn Lập"],
            "children": [],
        }
    ]
    assert any(
        ranking["name"] == "Hàn Lập"
        and ranking["label"] == "Luyện Khí sơ kỳ"
        for ranking in xray["power_rankings"]
    )
    assert any(entity["name"] == "Trúc Cơ" and entity["type"] == "realm" for entity in xray["entities"])
    assert "Hàn Lập vào động phủ" in [event["title"] for event in xray["timeline"]]


def test_reader_xray_ai_accepts_graph_object_nodes_edges_and_timeline_participants(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 7, "Nghi kỵ")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "relationship_graph": {
                "nodes": [
                    {"id": "han_lap", "label": "Hàn Lập", "type": "character"},
                    {"id": "mac_cu_nhan", "label": "Mặc Cư Nhân", "type": "character"},
                ],
                "edges": [
                    {
                        "from": "han_lap",
                        "to": "mac_cu_nhan",
                        "label": "nghi kỵ",
                        "evidence": "Hàn Lập nhận ra Mặc Cư Nhân đang giấu bí mật.",
                        "chapter": 7,
                        "weight": 0.66,
                    },
                ],
            },
            "faction_tree": {
                "nodes": [
                    {
                        "name": "Thất Huyền Môn",
                        "description": "Môn phái có nhiều phân đường.",
                        "members": [{"name": "Hàn Lập", "role": "đệ tử"}],
                        "chapter": 7,
                    },
                ],
            },
            "power_rankings": {
                "rankings": [
                    {
                        "character": "Hàn Lập",
                        "power_level": 19,
                        "realm": "Luyện Khí tầng ba",
                        "reason": "Pháp lực còn thấp nhưng linh căn ổn định.",
                        "sect": "Thất Huyền Môn",
                        "chapter": 7,
                    },
                ],
            },
            "timeline": {
                "events": [
                    {
                        "chapter": 7,
                        "order": 3,
                        "event": "Hàn Lập sinh nghi",
                        "summary": "Hàn Lập bắt đầu nghi ngờ mục đích của Mặc Cư Nhân.",
                        "participants": [{"name": "Hàn Lập"}, {"name": "Mặc Cư Nhân"}],
                    },
                ],
            },
        },
        default_chapter_id=chapter_id,
        default_chapter_number=7,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    entity_names = {entity["name"] for entity in xray["entities"]}
    assert {"Hàn Lập", "Mặc Cư Nhân", "Thất Huyền Môn"} <= entity_names
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Mặc Cư Nhân"
        and relationship["relation"] == "nghi kỵ"
        and relationship["source_type"] == "ai"
        and relationship["strength"] == 0.66
        for relationship in xray["relationships"]
    )
    assert xray["faction_tree"] == [
        {
            "name": "Thất Huyền Môn",
            "description": "Môn phái có nhiều phân đường.",
            "parent": "",
            "first_chapter_number": 7,
            "members": ["Hàn Lập"],
            "children": [],
        }
    ]
    assert any(
        ranking["name"] == "Hàn Lập"
        and ranking["rank"] == 19
        and ranking["label"] == "Luyện Khí tầng ba"
        and ranking["basis"] == "Pháp lực còn thấp nhưng linh căn ổn định."
        and ranking["faction"] == "Thất Huyền Môn"
        for ranking in xray["power_rankings"]
    )
    assert any(
        event["title"] == "Hàn Lập sinh nghi"
        and event["event_order"] == 3
        and event["entities"] == ["Hàn Lập", "Mặc Cư Nhân"]
        for event in xray["timeline"]
    )


def test_reader_xray_ai_timeline_merges_locations_factions_items_and_realms(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 8, "Thanh Ngưu trấn")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "timeline": [
                {
                    "chapter_number": 8,
                    "event_order": 4,
                    "title": "Hàn Lập vào Thanh Ngưu trấn",
                    "summary": "Hàn Lập mang linh thạch vào Thanh Ngưu trấn và nghe tin Thất Huyền Môn.",
                    "characters": [{"name": "Hàn Lập"}],
                    "locations": [{"name": "Thanh Ngưu trấn"}],
                    "factions": [{"name": "Thất Huyền Môn"}],
                    "items": [{"name": "linh thạch"}],
                    "realms": [{"name": "Luyện Khí"}],
                },
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=8,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")

    assert xray is not None
    event = next(item for item in xray["timeline"] if item["title"] == "Hàn Lập vào Thanh Ngưu trấn")
    assert event["entities"] == [
        "Hàn Lập",
        "Thanh Ngưu trấn",
        "Thất Huyền Môn",
        "linh thạch",
        "Luyện Khí",
    ]
    entities_by_name = {entity["name"]: entity for entity in xray["entities"]}
    assert entities_by_name["Thanh Ngưu trấn"]["type"] == "location"
    assert entities_by_name["Thất Huyền Môn"]["type"] == "faction"
    assert entities_by_name["linh thạch"]["type"] == "item"
    assert entities_by_name["Luyện Khí"]["type"] == "realm"


def test_reader_xray_ai_top_level_locations_create_map_nodes_and_links(
    temp_pipeline: PipelineService,
) -> None:
    book_id = add_book(temp_pipeline.db_path, "Phàm Nhân Tu Tiên")
    chapter_id = add_chapter(temp_pipeline.db_path, book_id, 8, "Thanh Ngưu trấn")

    temp_pipeline._apply_reader_xray_ai_payload(
        book_id,
        {
            "world_map": {
                "locations": [
                    {
                        "name": "Thanh Ngưu trấn",
                        "description": "Trấn nhỏ dưới chân núi, nơi tán tu tụ hội.",
                        "chapter_number": 8,
                        "region": "Việt Quốc",
                        "parent": "Việt Quốc",
                        "characters": ["Hàn Lập"],
                        "factions": ["Thất Huyền Môn"],
                    }
                ]
            }
        },
        default_chapter_id=chapter_id,
        default_chapter_number=8,
    )

    xray = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="no_spoiler")
    xray_all = temp_pipeline.get_reader_xray(book_id, chapter_id=chapter_id, spoiler_mode="allow_spoiler")

    assert xray is not None
    assert xray_all is not None
    entities_by_name = {entity["name"]: entity for entity in xray["entities"]}
    all_entities_by_name = {entity["name"]: entity for entity in xray_all["entities"]}
    assert entities_by_name["Thanh Ngưu trấn"]["type"] == "location"
    assert all_entities_by_name["Thanh Ngưu trấn"]["metadata"]["region"] == "Việt Quốc"
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Thanh Ngưu trấn"
        and relationship["relation"] == "xuất hiện tại"
        for relationship in xray["relationships"]
    )
    assert any(
        relationship["source"] == "Thất Huyền Môn"
        and relationship["target"] == "Thanh Ngưu trấn"
        and relationship["relation"] == "có thế lực tại"
        for relationship in xray["relationships"]
    )
