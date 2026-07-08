from __future__ import annotations

from app.mobile_api.services.import_metadata import detect_import_metadata


def test_detect_import_metadata_parses_large_chinese_chapter_numbers() -> None:
    metadata = detect_import_metadata(
        text="《凡人修仙传》\n第一百二十三章 云涌\n张铁睁开双眼。"
    )

    assert metadata["title"] == "凡人修仙传"
    assert metadata["chapter_number"] == 123
    assert metadata["chapter_title"] == "云涌"
