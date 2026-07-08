from __future__ import annotations

from app.database.db import add_book, add_chapter, init_db, save_qa_report, update_chapter_paths
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService


def make_pipeline(db_path):
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    return pipeline


def test_qa_summary_treats_saved_0_to_10_score_as_pass(temp_db_path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path="/tmp/translated.txt")
    save_qa_report(
        temp_db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        quality_score=8.5,
        fidelity_score=9,
        style_score=8,
        glossary_score=8,
        audiobook_score=9,
        verdict="PASS",
        report_json="{}",
    )
    service = QAService(make_pipeline(temp_db_path))

    summary = service.get_book_qa_summary(book_id)

    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 0
    assert summary["chapters"][0]["status"] == "pass"


def test_retranslate_paragraph_passes_default_provider_usage_metadata(temp_db_path, tmp_path, monkeypatch) -> None:
    init_db(temp_db_path)
    raw_path = tmp_path / "raw.txt"
    raw_path.write_text("第一段。\n\n第二段。", encoding="utf-8")
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    monkeypatch.setenv("GEMINI_API_KEY", "provider-secret")
    captured: dict[str, object] = {}

    def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return "Bản dịch đoạn hai."

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)
    service = make_pipeline(temp_db_path)

    result = service.retranslate_paragraph(book_id, chapter_id, 1)

    assert result == "Bản dịch đoạn hai."
    assert captured["provider_id"] == "gemini"
    assert captured["task_type"] == "retranslate"
    assert captured["db_path"] == temp_db_path
    assert captured["chapter_id"] == chapter_id
    assert captured["api_key"] == "provider-secret"
    assert "Không dùng \"tôi\" khi nhân vật đang gọi Lục ca" in str(captured["prompt"])
    assert "Lục ca, mấy ngày nay nhờ huynh chăm sóc" in str(captured["prompt"])


def test_polish_paragraph_uses_classical_pronoun_style_prompt(temp_db_path, tmp_path, monkeypatch) -> None:
    init_db(temp_db_path)
    translation_path = tmp_path / "translation.txt"
    translation_path.write_text(
        "Lục ca, mấy ngày nay đã phiền hắn chăm sóc nhiều rồi, tôi còn chưa biết báo đáp thế nào.",
        encoding="utf-8",
    )
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translation_path)
    monkeypatch.setenv("GEMINI_API_KEY", "provider-secret")
    captured: dict[str, object] = {}

    def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return "Lục ca, mấy ngày nay nhờ huynh chăm sóc, ta còn chưa biết báo đáp thế nào."

    monkeypatch.setattr("app.mobile_api.services.pipeline_service.call_llm", fake_call_llm)
    service = make_pipeline(temp_db_path)

    result = service.polish_paragraph(book_id, chapter_id, 0)

    assert result.startswith("Lục ca")
    assert captured["provider_id"] == "gemini"
    assert captured["task_type"] == "polish"
    assert "Không dùng \"tôi\" khi nhân vật đang gọi Lục ca" in str(captured["prompt"])
    assert "xin huynh đừng cho ta thêm đồ nữa" in str(captured["prompt"])
