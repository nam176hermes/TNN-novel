from __future__ import annotations

import json
import subprocess
import sys

import pytest

from app.database.db import (
    add_book,
    add_chapter,
    init_db,
    list_operational_events,
    save_qa_report,
    update_chapter_paths,
)
from app.mobile_api.services import qa_service as qa_service_module
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService


def make_pipeline(db_path):
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    return pipeline


def test_qa_service_import_does_not_import_pipeline_service() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.modules.pop('app.mobile_api.services.pipeline_service', None); "
                "import app.mobile_api.services.qa_service; "
                "assert 'app.mobile_api.services.pipeline_service' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_qa_service_accepts_chapter_content_reader_protocol(temp_db_path, tmp_path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")

    class RecordingContentReader:
        db_path = temp_db_path

        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def get_chapter_source(self, requested_chapter_id: int) -> str | None:
            self.calls.append(("source", requested_chapter_id))
            return "第一段。"

        def get_chapter_translation(self, requested_chapter_id: int) -> str | None:
            self.calls.append(("translation", requested_chapter_id))
            return "Đoạn thứ nhất."

    reader = RecordingContentReader()
    report = QAService(reader).run_deterministic_qa(book_id, chapter_id)

    assert report["overall_status"] == "PASS"
    assert reader.calls == [("source", chapter_id), ("translation", chapter_id)]


def test_run_qa_check_raises_safe_typed_error_and_records_safe_event_when_save_fails(
    temp_db_path,
    monkeypatch,
) -> None:
    init_db(temp_db_path)
    generated_marker = "GENERATED_QA_CONTENT_SENTINEL"
    database_error_marker = "SQLITE_WRITE_FAILURE_SENTINEL"
    steps: list[str] = []

    class GeneratedReportPipeline:
        db_path = temp_db_path

        def run_qa_check(self, book_id, chapter_id, model, host):
            steps.append("generated")
            return {
                "quality_score": 8.5,
                "fidelity_score": 9,
                "style_score": 8,
                "glossary_score": 8,
                "audiobook_score": 7,
                "verdict": "PASS",
                "issues": [],
                "provider_debug": generated_marker,
            }

        def get_chapter_source(self, chapter_id):
            return "第一段。"

        def get_chapter_translation(self, chapter_id):
            return "Đoạn thứ nhất."

    def fail_after_generation(db_path, **kwargs):
        assert db_path == temp_db_path
        assert json.loads(kwargs["report_json"])["provider_debug"] == generated_marker
        assert steps == ["generated"]
        steps.append("persistence_failed")
        raise RuntimeError(database_error_marker)

    monkeypatch.setattr(qa_service_module, "save_qa_report", fail_after_generation)

    with pytest.raises(Exception) as exc_info:
        QAService(GeneratedReportPipeline()).run_qa_check(book_id=41, chapter_id=42)

    error = exc_info.value
    assert isinstance(error, qa_service_module.QAPersistenceError)
    assert error.detail() == {
        "code": "qa_persistence_failed",
        "status": "generated_not_persisted",
        "message": "QA report was generated but could not be persisted.",
    }
    assert database_error_marker not in str(error)
    assert generated_marker not in str(error)
    assert steps == ["generated", "persistence_failed"]

    events = list_operational_events(temp_db_path, limit=10, severities=())
    assert len(events) == 1
    assert events[0]["event_type"] == "qa_persistence_failed"
    assert events[0]["severity"] == "error"
    assert events[0]["source"] == "qa"
    assert events[0]["message"] == "QA report persistence failed"
    assert events[0]["actor_user_id"] == ""
    assert events[0]["owner_user_id"] == ""
    assert events[0]["job_id"] == ""
    assert events[0]["details"] == {
        "book_id": 41,
        "chapter_id": 42,
        "outcome": "generated_not_persisted",
    }
    serialized_event = json.dumps(events[0], ensure_ascii=False)
    assert database_error_marker not in serialized_event
    assert generated_marker not in serialized_event


def test_run_qa_check_event_writer_failure_does_not_mask_persistence_error(
    temp_db_path,
    monkeypatch,
    caplog,
) -> None:
    init_db(temp_db_path)
    database_error_marker = "QA_DATABASE_ERROR_SENTINEL"
    event_error_marker = "QA_EVENT_ERROR_SENTINEL"

    class GeneratedReportPipeline:
        db_path = temp_db_path

        def run_qa_check(self, book_id, chapter_id, model, host):
            return {
                "quality_score": 8,
                "fidelity_score": 8,
                "style_score": 8,
                "glossary_score": 8,
                "audiobook_score": 8,
                "verdict": "PASS",
                "issues": [],
            }

        def get_chapter_source(self, chapter_id):
            return "第一段。"

        def get_chapter_translation(self, chapter_id):
            return "Đoạn thứ nhất."

    def fail_report_write(*args, **kwargs):
        raise RuntimeError(database_error_marker)

    def fail_event_write(*args, **kwargs):
        raise RuntimeError(event_error_marker)

    monkeypatch.setattr(qa_service_module, "save_qa_report", fail_report_write)
    monkeypatch.setattr(qa_service_module, "record_operational_event", fail_event_write)

    with pytest.raises(Exception) as exc_info:
        QAService(GeneratedReportPipeline()).run_qa_check(book_id=51, chapter_id=52)

    error = exc_info.value
    assert isinstance(error, qa_service_module.QAPersistenceError)
    assert error.detail() == {
        "code": "qa_persistence_failed",
        "status": "generated_not_persisted",
        "message": "QA report was generated but could not be persisted.",
    }
    assert database_error_marker not in str(error)
    assert event_error_marker not in str(error)
    assert database_error_marker not in caplog.text
    assert event_error_marker not in caplog.text
    assert "Failed to record QA persistence operational event" in caplog.text


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
