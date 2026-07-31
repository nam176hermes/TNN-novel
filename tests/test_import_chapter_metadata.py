from __future__ import annotations

from pathlib import Path
import unicodedata

import pytest

from app.database.db import get_chapter, init_db
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.schemas import URLFetchChapterResult
from app.mobile_api.services import import_metadata
from app.mobile_api.services.pipeline_service import PipelineService


def _pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    pipeline.data_dir = data_dir
    pipeline.legacy_artifact_root = None
    return pipeline


def test_import_from_text_returns_normalized_stored_metadata(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    pipeline = _pipeline(temp_db_path, tmp_path)
    source_text = "\ufeff  Ca\u0302u chuyen\u0302 cu\u0309 \r\n\r\nDo\u0300ng hai\u00a0  \n"
    assert hasattr(import_metadata, "normalize_import_text")
    expected_text = import_metadata.normalize_import_text(source_text)

    result = pipeline.import_from_text("Sach", 1, "Mo dau", source_text)

    chapter = get_chapter(temp_db_path, result.book_id, 1)
    assert chapter is not None
    stored_text = Path(chapter["raw_text_path"]).read_text(encoding="utf-8")
    assert stored_text == expected_text
    assert result.stored_text_length == len(stored_text)
    assert result.content_hash == import_metadata.source_hash(stored_text)
    assert result.operation == "created"
    assert result["stored_text_length"] == len(stored_text)
    assert result["content_hash"] == import_metadata.source_hash(stored_text)
    assert "text" not in result.to_dict()


def test_import_text_normalization_has_deterministic_length_and_hash() -> None:
    first = unicodedata.normalize("NFD", "Câu chuyện\r\nDòng hai\u00a0\n")
    second = "Câu chuyện\nDòng hai\n"

    assert hasattr(import_metadata, "normalize_import_text")
    assert import_metadata.normalize_import_text(first) == import_metadata.normalize_import_text(second)
    assert import_metadata.source_hash(first) == import_metadata.source_hash(second)
    assert len(import_metadata.normalize_import_text(first)) == len(import_metadata.normalize_import_text(second))


def test_import_from_text_rejects_empty_normalized_content(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    pipeline = _pipeline(temp_db_path, tmp_path)

    with pytest.raises(SourceAdapterError) as raised:
        pipeline.import_from_text("Sach", 1, "Mo dau", " \r\n\t\u00a0 ")

    assert raised.value.code is FetchErrorCode.CONTENT_INVALID
    assert raised.value.retryable is False


def test_url_fetch_chapter_result_accepts_legacy_payload_with_metadata_defaults() -> None:
    result = URLFetchChapterResult.model_validate(
        {
            "chapter_number": 1,
            "title": "Chương một",
            "url": "https://example.test/chapter/1",
            "success": True,
            "error": "",
            "text_length": 12,
            "book_id": 7,
            "chapter_id": 9,
        }
    )

    assert result.error_code == ""
    assert result.retryable is False
    assert result.content_hash == ""
    assert result.model_dump()["operation"] == ""
