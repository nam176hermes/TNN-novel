from __future__ import annotations

from app.config import settings
from app.database.db import add_book, add_chapter, init_db
from app.mobile_api.services.pipeline_service import PipelineService


def test_reader_xray_ai_payload_accepts_named_relationship_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    for subdir in ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    init_db(tmp_path / "pipeline.db")

    book_id = add_book(tmp_path / "pipeline.db", "X-Ray Shape Book")
    chapter_id = add_chapter(tmp_path / "pipeline.db", book_id, 1, "Nhập môn")
    service = PipelineService()

    service._apply_reader_xray_ai_payload(
        book_id,
        {
            "entities": [
                {
                    "name": "Hàn Lập",
                    "type": "character",
                    "chapter_number": 1,
                    "description": "Thiếu niên mới nhập môn.",
                },
                {
                    "name": "Thất Huyền Môn",
                    "type": "faction",
                    "chapter_number": 1,
                    "description": "Môn phái nơi Hàn Lập gia nhập.",
                },
            ],
            "relationships": [
                {
                    "source_name": "Hàn Lập",
                    "target_name": "Thất Huyền Môn",
                    "relation": "gia nhập",
                    "evidence": "Hàn Lập bái nhập Thất Huyền Môn.",
                    "chapter_number": 1,
                    "strength": 0.9,
                }
            ],
        },
        default_chapter_id=chapter_id,
        default_chapter_number=1,
    )

    xray = service.get_reader_xray(
        book_id,
        chapter_id=chapter_id,
        spoiler_mode="no_spoiler",
        auto_ai=False,
    )

    assert xray is not None
    assert any(
        relationship["source"] == "Hàn Lập"
        and relationship["target"] == "Thất Huyền Môn"
        and relationship["relation"] == "gia nhập"
        and relationship["source_type"] == "ai"
        for relationship in xray["relationships"]
    )
