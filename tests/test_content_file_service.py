from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.database.db import add_book, add_chapter, init_db, update_chapter_paths
from app.mobile_api.services.content_file_service import ContentFileService
from app.storage.artifact_paths import ArtifactClass, ArtifactPathError, ResolutionStatus


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service(temp_db_path: Path, data_dir: Path, legacy_root: Path | None = None) -> ContentFileService:
    init_db(temp_db_path)
    return ContentFileService(data_dir=data_dir, db_path=temp_db_path, legacy_artifact_root=legacy_root)


def test_content_reader_preserves_source_translation_and_html_payload_without_rewriting_files(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    raw_path = data_dir / "raw" / "chapter.txt"
    cleaned_path = data_dir / "cleaned" / "chapter.txt"
    translated_path = data_dir / "translated" / "chapter.txt"
    html_path = data_dir / "translated" / "chapter.html"
    for path, text in (
        (raw_path, "第一段。\n\n\n第二段。"),
        (cleaned_path, "cleaned must not replace raw"),
        (translated_path, "Đoạn thứ nhất.\n\nĐoạn thứ hai."),
        (html_path, "<p>Đoạn thứ nhất.</p>"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    before = {path: _digest(path) for path in (raw_path, cleaned_path, translated_path, html_path)}
    service = _service(temp_db_path, data_dir)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(
        temp_db_path,
        chapter_id,
        cleaned_text_path=cleaned_path,
        translated_text_path=translated_path,
        content_html_path=html_path,
    )

    assert service.get_chapter_source(chapter_id) == "第一段。\n\n第二段。"
    assert service.get_chapter_translation(chapter_id) == "Đoạn thứ nhất.\n\nĐoạn thứ hai."
    assert service.get_chapter_content(chapter_id) == {
        "text": "Đoạn thứ nhất.\n\nĐoạn thứ hai.",
        "html": "<p>Đoạn thứ nhất.</p>",
    }
    assert {path: _digest(path) for path in before} == before


def test_content_reader_remaps_only_the_exact_legacy_prefix(temp_db_path: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    legacy_root = Path("/legacy/novel-pipeline")
    target = data_dir / "raw" / "chapter.txt"
    target.parent.mkdir(parents=True)
    target.write_text("原文", encoding="utf-8")
    service = _service(temp_db_path, data_dir, legacy_root)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(
        temp_db_path,
        book_id,
        1,
        "Chapter",
        raw_text_path=legacy_root / "data/raw/chapter.txt",
    )

    assert service.get_chapter_source(chapter_id) == "原文"
    assert service.resolve_artifact_file(
        legacy_root / "data/raw/chapter.txt",
        ArtifactClass.RAW,
    ) == target.resolve()


def test_content_reader_preserves_blank_and_missing_metadata_behavior(temp_db_path: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = _service(temp_db_path, data_dir)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")

    assert service.get_chapter_source(chapter_id) is None
    assert service.get_chapter_translation(chapter_id) is None
    assert service.get_chapter_content(chapter_id) is None
    assert service.get_chapter_source(999_999) is None

    missing = data_dir / "raw" / "missing.txt"
    update_chapter_paths(temp_db_path, chapter_id, raw_text_path=missing)
    with pytest.raises(ArtifactPathError) as raised:
        service.get_chapter_source(chapter_id)
    assert raised.value.status is ResolutionStatus.FILE_MISSING


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        ("../outside.txt", ResolutionStatus.OUTSIDE_ALLOWED_ROOT),
        ("https://example.test/chapter.txt", ResolutionStatus.OUTSIDE_ALLOWED_ROOT),
    ],
)
def test_content_reader_rejects_unsafe_artifact_values(
    temp_db_path: Path,
    tmp_path: Path,
    value: str,
    expected_status: ResolutionStatus,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = _service(temp_db_path, data_dir)

    with pytest.raises(ArtifactPathError) as raised:
        service.resolve_artifact_file(value, ArtifactClass.RAW)
    assert raised.value.status is expected_status


def test_content_reader_rejects_directories_and_symlink_escapes(temp_db_path: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    symlink = raw_dir / "escape.txt"
    try:
        symlink.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this filesystem")
    service = _service(temp_db_path, data_dir)

    with pytest.raises(ArtifactPathError) as directory_error:
        service.resolve_artifact_file(raw_dir, ArtifactClass.RAW)
    assert directory_error.value.status is ResolutionStatus.WRONG_TYPE

    with pytest.raises(ArtifactPathError) as symlink_error:
        service.resolve_artifact_file(symlink, ArtifactClass.RAW)
    assert symlink_error.value.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT


def test_content_requires_translation_before_optional_html(temp_db_path: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    html_path = data_dir / "translated" / "chapter.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<p>HTML only</p>", encoding="utf-8")
    service = _service(temp_db_path, data_dir)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, content_html_path=html_path)

    assert service.get_chapter_content(chapter_id) is None
