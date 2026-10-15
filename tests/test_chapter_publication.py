from pathlib import Path
import sqlite3

import pytest

from app.database.db import add_book, add_chapter, get_chapter_by_id, init_db, update_chapter_paths
from app.mobile_api.services.pipeline_service import PipelineService


@pytest.fixture
def publication(tmp_path):
    db = tmp_path / "pipeline.db"
    init_db(db)
    book = add_book(db, "Publication fixture")
    chapter = add_chapter(db, book, 1, "Chapter")
    directory = tmp_path / "translated"
    directory.mkdir()
    text = directory / "old.txt"
    html = directory / "old.html"
    text.write_text("Bản dịch cũ.", encoding="utf-8")
    html.write_text("<p>Bản dịch cũ.</p>", encoding="utf-8")
    update_chapter_paths(db, chapter, translated_text_path=text, content_html_path=html)
    service = object.__new__(PipelineService)
    service.db_path, service.data_dir, service.legacy_artifact_root = db, tmp_path, None
    return service, book, chapter, text, html


def test_failed_publication_preserves_active_artifacts(publication):
    service, _, chapter, text, html = publication
    with sqlite3.connect(service.db_path) as conn:
        conn.execute("""CREATE TRIGGER reject_publication BEFORE UPDATE OF translated_text_path
                      ON chapters BEGIN SELECT RAISE(ABORT, 'publication failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="publication failed"):
        service.update_chapter_translation(chapter, "Bản dịch mới.")
    row = get_chapter_by_id(service.db_path, chapter)
    assert row["translated_text_path"] == str(text)
    assert row["content_html_path"] == str(html)
    assert text.read_text(encoding="utf-8") == "Bản dịch cũ."
    assert html.exists()
    assert set(text.parent.iterdir()) == {text, html}


def test_failed_deletion_preserves_active_artifacts(publication):
    service, book, chapter, text, html = publication
    with sqlite3.connect(service.db_path) as conn:
        conn.execute("""CREATE TRIGGER reject_deletion BEFORE UPDATE OF translated_text_path
                      ON chapters BEGIN SELECT RAISE(ABORT, 'deletion failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="deletion failed"):
        service.delete_chapter_translation(book, chapter)
    assert text.exists() and html.exists()
    assert get_chapter_by_id(service.db_path, chapter)["translated_text_path"] == str(text)


def test_empty_publication_does_not_replace_valid_text(publication):
    service, _, chapter, text, _ = publication
    with pytest.raises(ValueError, match="empty"):
        service.update_chapter_translation(chapter, " \n ")
    assert get_chapter_by_id(service.db_path, chapter)["translated_text_path"] == str(text)
    assert text.read_text(encoding="utf-8") == "Bản dịch cũ."


def test_publication_keeps_legacy_artifact_still_used_by_another_chapter(publication):
    service, book, chapter, text, html = publication
    sibling = add_chapter(service.db_path, book, 2, "Sibling")
    update_chapter_paths(service.db_path, sibling, translated_text_path=text, content_html_path=html)
    service.update_chapter_translation(chapter, "Bản dịch mới.")
    assert text.exists() and html.exists()
    assert get_chapter_by_id(service.db_path, sibling)["translated_text_path"] == str(text)


def test_edit_invalidates_audio_but_preserves_file(publication):
    from app.mobile_api.services.audio_service import AudioService
    service, _, chapter, _, _ = publication
    audio = service.data_dir / "audio" / "legacy.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"legacy fixture")
    update_chapter_paths(service.db_path, chapter, audio_path=audio)
    before = get_chapter_by_id(service.db_path, chapter)
    assert before["audio_status"] == "legacy_unverified"
    service.update_chapter_translation(chapter, "Bản dịch mới.")
    after = get_chapter_by_id(service.db_path, chapter)
    assert after["content_revision"] == before["content_revision"] + 1
    assert after["audio_status"] == "stale"
    assert AudioService(service).get_audio_path(chapter) is None
    assert audio.exists()


def test_same_text_keeps_revision_and_rich_content(publication):
    service, _, chapter, text, html = publication
    before = get_chapter_by_id(service.db_path, chapter)
    service.update_chapter_translation(chapter, text.read_text(encoding="utf-8"))
    after = get_chapter_by_id(service.db_path, chapter)
    assert after["content_revision"] == before["content_revision"]
    assert after["content_html_path"] == str(html) and html.exists()


@pytest.mark.parametrize("changed_field", ["raw_text_path", "cleaned_text_path"])
def test_source_changes_invalidate_audio_and_do_not_keep_old_cleaned_text(publication, changed_field):
    service, _, chapter, _, _ = publication
    raw, cleaned, replacement = (service.data_dir / name for name in ("raw.txt", "cleaned.txt", "replacement.txt"))
    raw.write_text("源文本。", encoding="utf-8")
    cleaned.write_text("已清理文本。", encoding="utf-8")
    replacement.write_text("新文本。", encoding="utf-8")
    audio = service.data_dir / "audio" / "legacy.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")
    update_chapter_paths(service.db_path, chapter, raw_text_path=raw, cleaned_text_path=cleaned, audio_path=audio)
    before = get_chapter_by_id(service.db_path, chapter)
    update_chapter_paths(service.db_path, chapter, **{changed_field: replacement})
    after = get_chapter_by_id(service.db_path, chapter)
    assert after["content_revision"] == before["content_revision"] + 1
    assert after["audio_status"] == "stale"
    assert service.get_chapter_source(chapter) == ("新文本。" if changed_field == "raw_text_path" else "源文本。")
    assert after["cleaned_text_path"] == (None if changed_field == "raw_text_path" else str(replacement))
    assert cleaned.exists() and audio.exists()


def test_old_revision_cannot_replace_new_translation(publication):
    service, _, chapter, _, _ = publication
    old_revision = get_chapter_by_id(service.db_path, chapter)["content_revision"]
    service.update_chapter_translation(chapter, "Bản mới nhất.")
    with pytest.raises(ValueError, match="revision"):
        service.update_chapter_translation(chapter, "Kết quả đến muộn.", expected_content_revision=old_revision)
    row = get_chapter_by_id(service.db_path, chapter)
    assert Path(row["translated_text_path"]).read_text(encoding="utf-8") == "Bản mới nhất."


def test_migration_is_repeatable_and_does_not_certify_legacy(publication):
    service, _, chapter, text, _ = publication
    init_db(service.db_path)
    init_db(service.db_path)
    row = get_chapter_by_id(service.db_path, chapter)
    assert row["translated_text_path"] == str(text)
    assert row["quality_status"] in {"unreviewed", "legacy_unverified"}
