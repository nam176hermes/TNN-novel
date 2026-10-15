import json

import pytest

from app.database.db import add_book, add_chapter, get_qa_report, init_db
from app.mobile_api.services import pipeline_service as pipeline_module
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService
from app.translation import qa_reviewer


def semantic(verdict="PASS", score=9):
    return dict(verdict=verdict, fidelity_score=score, style_score=score,
                glossary_score=score, audiobook_score=score, quality_score=score,
                critical_issues=[], paragraph_alignment_issues=[], term_issues=[], style_rewrites=[],
                issues=[] if verdict == "PASS" else [{"type": "missing_meaning", "severity": "high"}])


@pytest.mark.parametrize("text", ["Người anh hùng đến núi.", "Sư huynh, hắn đã đến núi."])
def test_ambiguous_pronouns_do_not_override_semantic_pass(monkeypatch, text):
    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat",
                        lambda **_: {"text": json.dumps(semantic()), "usage": {}})
    report = qa_reviewer.run_qa_check("他来到山。", text)
    assert report["verdict"] == "PASS"


def test_semantic_qa_receives_end_of_long_chapter(monkeypatch):
    captured = {}
    def chat(**options):
        captured.update(options)
        return {"text": json.dumps(semantic()), "usage": {}}
    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", chat)
    qa_reviewer.run_qa_check("长" * 4000 + "SOURCE_TAIL", "Dài " * 2000 + "TARGET_TAIL")
    assert "SOURCE_TAIL" in captured["prompt"] and "TARGET_TAIL" in captured["prompt"]


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    db = tmp_path / "pipeline.db"
    init_db(db)
    book = add_book(db, "QA fixture")
    raw = tmp_path / "raw" / "chapter.txt"
    raw.parent.mkdir()
    raw.write_text("他来到山。", encoding="utf-8")
    chapter = add_chapter(db, book, 1, "Chapter", raw_text_path=raw)
    service = object.__new__(PipelineService)
    service.db_path, service.data_dir, service.legacy_artifact_root = db, tmp_path, None
    monkeypatch.setattr(service, "_provider_options_for_preset_task", lambda *args: dict(
        model="fixture", host="https://provider.invalid/v1", api_key="", provider_id=None))
    monkeypatch.setattr(pipeline_module, "translate_chapter", lambda **_: "Người ấy đến núi.")
    return service, book, chapter


def test_rule_followup_cannot_overwrite_semantic_failure(pipeline, monkeypatch):
    service, book, chapter = pipeline
    monkeypatch.setattr(pipeline_module, "call_llm", lambda **_: "Người ấy đến núi.")
    monkeypatch.setattr(pipeline_module, "run_qa_check", lambda **_: semantic("FAIL", 1))
    service.translate_chapter_with_pipeline(book, chapter, preset_id="balanced")
    QAService(service).run_deterministic_qa(book, chapter)
    report = get_qa_report(service.db_path, book, chapter)
    payload = json.loads(report["report_json"])
    assert report["verdict"] == "FAIL" and report["quality_score"] == 1
    assert payload["semantic"]["verdict"] == "FAIL"
    assert payload["rule_based"]["overall_status"] == "PASS"
    assert report["content_revision"] == service.get_chapter(chapter)["content_revision"]


def test_rewrite_is_reviewed_on_final_text(pipeline, monkeypatch):
    service, book, chapter = pipeline
    inspected = []
    monkeypatch.setattr(pipeline_module, "call_llm", lambda **options:
                        "Người ấy lên núi." if options["task_type"] == "rewrite" else "Người ấy đến núi.")
    def qa(**options):
        inspected.append(options["translated_text"])
        return semantic("PASS" if "lên" in inspected[-1] else "FAIL", 9)
    monkeypatch.setattr(pipeline_module, "run_qa_check", qa)
    result = service.translate_chapter_with_pipeline(book, chapter, preset_id="quality_high")
    assert inspected == ["Người ấy đến núi.", "Người ấy lên núi."]
    assert result["qa_report"]["verdict"] == "PASS"


def test_high_score_cannot_hide_fail_and_edit_invalidates_summary(pipeline, monkeypatch):
    service, book, chapter = pipeline
    monkeypatch.setattr(pipeline_module, "call_llm", lambda **_: "Người ấy đến núi.")
    monkeypatch.setattr(pipeline_module, "run_qa_check", lambda **_: semantic("FAIL", 9))
    service.translate_chapter_with_pipeline(book, chapter, preset_id="balanced")
    qa = QAService(service)
    summary = qa.get_book_qa_summary(book)
    assert (summary["pass_count"], summary["fail_count"]) == (0, 1)
    service.update_chapter_translation(chapter, "Người ấy lên núi.")
    summary = qa.get_book_qa_summary(book)
    assert (summary["qa_done"], summary["pass_count"], summary["fail_count"]) == (0, 0, 0)
    assert summary["chapters"][0]["status"] == "stale"
    assert qa.get_qa_report(book, chapter)["verdict"] == "STALE"


def test_qa_revision_conflict_is_not_reported_as_success(pipeline, monkeypatch):
    from app.database.chapter_repository import ContentRevisionConflict
    service, book, chapter = pipeline
    service.update_chapter_translation(chapter, "Người ấy đến núi.")
    def concurrent_edit(*_):
        service.update_chapter_translation(chapter, "Người ấy lên núi.")
        return semantic()
    monkeypatch.setattr(service, "run_qa_check", concurrent_edit)
    with pytest.raises(ContentRevisionConflict):
        QAService(service).run_qa_check(book, chapter)
    assert get_qa_report(service.db_path, book, chapter) is None


def test_multi_chapter_job_keeps_initial_provider_snapshot(pipeline, monkeypatch):
    service, book, chapter = pipeline
    providers = []
    monkeypatch.setattr(pipeline_module, "call_llm", lambda **_: "Người ấy đến núi.")
    monkeypatch.setattr(pipeline_module, "run_qa_check", lambda **_: semantic())
    def translate(**options):
        providers.append(options["model"])
        return "Người ấy đến núi."
    monkeypatch.setattr(pipeline_module, "translate_chapter", translate)
    snapshot = {}
    service.translate_chapter_with_pipeline(book, chapter, provider_snapshot=snapshot)
    monkeypatch.setattr(service, "_provider_options_for_preset_task", lambda *_: pytest.fail("job options must stay frozen"))
    service.translate_chapter_with_pipeline(book, chapter, provider_snapshot=snapshot)
    assert providers == ["fixture", "fixture"]
