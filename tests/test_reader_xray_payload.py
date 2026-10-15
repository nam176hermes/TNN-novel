import pytest

from app.database.db import add_book, add_chapter, init_db, list_reader_xray_entities
from app.mobile_api.services.pipeline_service import PipelineService


def test_malformed_late_xray_event_does_not_publish_partial_graph(tmp_path):
    db = tmp_path / "pipeline.db"
    init_db(db)
    book = add_book(db, "Graph fixture")
    chapter = add_chapter(db, book, 1, "Chapter")
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db
    with pytest.raises(ValueError):
        pipeline._apply_reader_xray_ai_payload(book, {
            "entities": [{"name": "Nhân vật A", "chapter_number": 1}],
            "timeline": [{"title": "Sự kiện", "chapter_number": 1, "event_order": "invalid"}],
        }, default_chapter_id=chapter, default_chapter_number=1)
    assert list_reader_xray_entities(db, book) == []


def test_chapter_removed_before_graph_commit_leaves_no_entities(tmp_path, monkeypatch):
    from app.database.db import get_connection
    from app.mobile_api.services import reader_xray_payload as xray
    db = tmp_path / "pipeline.db"
    init_db(db)
    book = add_book(db, "Graph fixture")
    chapter = add_chapter(db, book, 1, "Chapter")
    normalize = xray.normalize_reader_xray_payload
    def remove_chapter(*args, **kwargs):
        graph = normalize(*args, **kwargs)
        with get_connection(db) as conn:
            conn.execute("UPDATE chapters SET deleted_at = 'removed' WHERE id = ?", (chapter,))
            conn.commit()
        return graph
    monkeypatch.setattr(xray, "normalize_reader_xray_payload", remove_chapter)
    with pytest.raises(ValueError, match="chapter has changed"):
        xray.apply_reader_xray_payload(db, book, {"entities": [{"name": "Nhân vật A", "chapter_number": 1}]},
            default_chapter_id=chapter, default_chapter_number=1, entity_type_for_name=lambda _: "character")
    assert list_reader_xray_entities(db, book) == []
