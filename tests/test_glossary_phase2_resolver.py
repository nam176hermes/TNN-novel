from __future__ import annotations

from pathlib import Path

import pytest

from app.database import db as db_mod
from app.database.db import (
    add_book,
    add_chapter,
    delete_glossary_term,
    get_connection,
    get_mobile_job,
    glossary_coverage,
    init_db,
    load_glossary,
    load_glossary_names,
    load_locked_glossary_terms,
    put_glossary_term,
    select_prompt_glossary_terms,
    update_glossary_term,
)
from app.mobile_api.services.job_service import JobService, JobTracker
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService
from app.translation import styleguide_config
from app.translation.cache import get_cached_translation, set_cached_translation


@pytest.fixture(autouse=True)
def no_styleguide_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(styleguide_config, "get_locked_terms", lambda: [])


def test_effective_resolution_applies_scope_variant_state_and_ambiguity_rules(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(
        styleguide_config,
        "get_locked_terms",
        lambda: [
            {"source": "玄门", "target": "văn phong cũ", "mode": "translate"},
            {"source": "样式词", "target": "văn phong", "mode": "translate"},
        ],
    )
    book_id = add_book(temp_db_path, "Resolver")
    other_book_id = add_book(temp_db_path, "Other")

    put_glossary_term(temp_db_path, 0, "玄门", "toàn cục", variants="玄宗")
    put_glossary_term(temp_db_path, book_id, "玄门", "trong sách")
    put_glossary_term(temp_db_path, 0, "旧剑", "kiếm toàn cục")
    put_glossary_term(temp_db_path, book_id, "古剑", "cổ kiếm", variants="旧剑")
    put_glossary_term(temp_db_path, 0, "甲门", "một", variants="歧义词")
    put_glossary_term(temp_db_path, 0, "乙门", "hai", variants="歧义词")
    put_glossary_term(temp_db_path, 0, "全局变体", "biến thể", variants="样式词")
    put_glossary_term(temp_db_path, other_book_id, "他书词", "sách khác")
    put_glossary_term(temp_db_path, book_id, "待审词", "chờ", approved=0, review_status="NEEDS_REVIEW")
    put_glossary_term(temp_db_path, book_id, "拒绝词", "bỏ", approved=-1, review_status="REJECTED")
    put_glossary_term(temp_db_path, book_id, "冲突词", "xung đột", review_status="CONFLICT")
    archived_id = put_glossary_term(temp_db_path, book_id, "归档词", "lưu trữ")
    assert delete_glossary_term(temp_db_path, archived_id)

    glossary = load_glossary(temp_db_path, book_id)

    assert glossary["玄门"] == "trong sách"
    assert glossary["样式词"] == "văn phong"
    assert "玄宗" not in glossary
    assert glossary["旧剑"] == "cổ kiếm"
    assert "歧义词" not in glossary
    assert not {"他书词", "待审词", "拒绝词", "冲突词", "归档词"} & glossary.keys()


def test_context_is_prompt_only_while_exact_modes_drive_qa_names_and_coverage(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Modes")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    put_glossary_term(temp_db_path, book_id, "玄机", "huyền cơ", mode="context", locked=1)
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", mode="translate", locked=1)
    put_glossary_term(temp_db_path, book_id, "韩立", "Hàn Lập", mode="transliterate", locked=1)

    prompt_terms = select_prompt_glossary_terms(temp_db_path, book_id, "玄机 灵石 韩立")
    assert {term["source_term"] for term in prompt_terms} == {"玄机", "灵石", "韩立"}
    assert "玄机" not in load_glossary(temp_db_path, book_id)
    assert load_glossary_names(temp_db_path, book_id)["韩立"] == "Hàn Lập"
    assert {term["source_term"] for term in load_locked_glossary_terms(temp_db_path, book_id)} == {
        "灵石",
        "韩立",
    }
    assert ("玄机", "huyền cơ") in glossary_coverage(temp_db_path, book_id, "玄机")["hits"]

    class Content:
        db_path = temp_db_path

        def get_chapter_source(self, _chapter_id: int) -> str:
            return "玄机 灵石 韩立"

        def get_chapter_translation(self, _chapter_id: int) -> str:
            return "Một đoạn không dùng thuật ngữ."

    report = QAService(Content()).run_deterministic_qa(book_id, chapter_id)
    assert {item["source_term"] for item in report["glossary_violations"]} == {"灵石", "韩立"}


def test_fingerprint_changes_only_for_effective_terms_or_style_revision_and_keys_cache(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    assert hasattr(db_mod, "resolve_effective_glossary")
    resolver = db_mod.resolve_effective_glossary
    book_id = add_book(temp_db_path, "Fingerprint")
    other_book_id = add_book(temp_db_path, "Unrelated")
    term_id = put_glossary_term(temp_db_path, book_id, "道心", "đạo tâm", mode="translate")

    first = resolver(temp_db_path, book_id, style_profile_id="tien_hiep")
    put_glossary_term(temp_db_path, book_id, "待审", "chờ", approved=0, review_status="NEEDS_REVIEW")
    put_glossary_term(temp_db_path, other_book_id, "别书", "sách khác")
    unchanged = resolver(temp_db_path, book_id, style_profile_id="tien_hiep")
    assert unchanged.fingerprint == first.fingerprint

    assert update_glossary_term(temp_db_path, term_id, target_term="đạo tâm mới")
    changed_term = resolver(temp_db_path, book_id, style_profile_id="tien_hiep")
    assert changed_term.fingerprint != first.fingerprint

    with get_connection(temp_db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(style_profiles)")}
        assert "revision" in columns
        conn.execute("UPDATE style_profiles SET revision = revision + 1 WHERE id = 'tien_hiep'")
        conn.commit()
    changed_style = resolver(temp_db_path, book_id, style_profile_id="tien_hiep")
    assert changed_style.fingerprint != changed_term.fingerprint

    set_cached_translation(
        temp_db_path,
        "原文",
        "zh",
        "vi",
        "model",
        "bản dịch",
        glossary_fingerprint=changed_term.fingerprint,
    )
    assert get_cached_translation(
        temp_db_path,
        "原文",
        "zh",
        "vi",
        "model",
        glossary_fingerprint=changed_term.fingerprint,
    ) == "bản dịch"
    assert get_cached_translation(
        temp_db_path,
        "原文",
        "zh",
        "vi",
        "model",
        glossary_fingerprint=changed_style.fingerprint,
    ) is None


def test_reader_dictionary_uses_only_effective_rows_and_book_override(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Reader")
    put_glossary_term(temp_db_path, 0, "丹田", "đan điền cũ", locked=1)
    put_glossary_term(temp_db_path, book_id, "丹田", "đan điền sách", approved=1)
    put_glossary_term(temp_db_path, book_id, "未审", "không hiện", approved=0, review_status="NEEDS_REVIEW")
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path

    pack = pipeline.get_reader_dictionary_pack(book_id)
    lookup = pipeline.lookup_reader_dictionary(book_id, query="丹田", include_online=False)

    assert pack is not None
    assert lookup is not None
    assert [
        (item["source"], item["target"])
        for item in pack["sources"]
        if item["term"] == "丹田"
    ] == [("glossary", "đan điền sách")]
    assert [
        (item["source"], item["target"])
        for item in lookup["sources"]
        if item["term"] == "丹田"
    ] == [("glossary", "đan điền sách")]


def test_reader_dictionary_includes_styleguide_only_effective_survivor(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(
        styleguide_config,
        "get_locked_terms",
        lambda: [
            {
                "source": "仙侠",
                "target": "tiên hiệp",
                "genre": "tien_hiep",
                "term_type": "genre",
                "priority": 80,
                "mode": "translate",
            }
        ],
    )
    book_id = add_book(temp_db_path, "Reader styleguide")
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path

    pack = pipeline.get_reader_dictionary_pack(book_id)
    lookup = pipeline.lookup_reader_dictionary(book_id, query="仙侠", include_online=False)

    assert pack is not None
    assert lookup is not None
    assert [
        (item["source"], item["term"], item["target"])
        for item in pack["sources"]
        if item["term"] == "仙侠"
    ] == [("glossary", "仙侠", "tiên hiệp")]
    assert [
        (item["source"], item["term"], item["target"])
        for item in lookup["sources"]
        if item["term"] == "仙侠"
    ] == [("glossary", "仙侠", "tiên hiệp")]


def test_reader_dictionary_keeps_styleguide_winner_over_losing_database_variant(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(
        styleguide_config,
        "get_locked_terms",
        lambda: [
            {
                "source": "丹田",
                "target": "đan điền",
                "term_type": "body",
                "priority": 80,
                "mode": "translate",
            }
        ],
    )
    put_glossary_term(temp_db_path, 0, "旁词", "khác", variants="丹田")
    book_id = add_book(temp_db_path, "Reader losing variant")
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path

    pack = pipeline.get_reader_dictionary_pack(book_id)
    lookup = pipeline.lookup_reader_dictionary(book_id, query="丹田", include_online=False)

    assert pack is not None
    assert lookup is not None
    assert [
        (item["source"], item["term"], item["target"])
        for item in pack["sources"]
        if item["term"] == "丹田"
    ] == [("glossary", "丹田", "đan điền")]
    assert [
        (item["source"], item["term"], item["target"])
        for item in lookup["sources"]
        if item["term"] == "丹田"
    ] == [("glossary", "丹田", "đan điền")]


@pytest.mark.parametrize("mutation_target", ["mapping", "term_row"])
def test_effective_snapshot_rejects_nested_mutation(
    temp_db_path: Path,
    mutation_target: str,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Immutable snapshot")
    put_glossary_term(temp_db_path, book_id, "秘词", "mục tiêu", mode="translate")
    snapshot = db_mod.resolve_effective_glossary(temp_db_path, book_id)

    with pytest.raises(TypeError):
        if mutation_target == "mapping":
            snapshot.prompt_mapping["秘词"] = "mutated"
        else:
            snapshot.prompt_terms[0]["target_term"] = "mutated"

    assert snapshot.prompt_mapping["秘词"] == "mục tiêu"
    assert snapshot.prompt_terms[0]["target_term"] == "mục tiêu"


@pytest.mark.asyncio
async def test_translation_job_persists_only_fingerprint_and_keeps_start_snapshot(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    assert hasattr(db_mod, "resolve_effective_glossary")
    book_id = add_book(temp_db_path, "Stable job")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    term_id = put_glossary_term(temp_db_path, book_id, "秘词", "mục tiêu cũ", mode="translate")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        GlossaryService,
        "extract_chapter_terms",
        lambda *_args, **_kwargs: {"created": 0, "updated": 0},
    )

    def capture_qa_snapshot(
        _service: QAService,
        _book_id: int,
        _chapter_id: int,
        _job_id: str = "",
        effective_glossary=None,
    ) -> dict:
        captured["qa_snapshot"] = effective_glossary
        return {"overall_status": "PASS", "issues": []}

    monkeypatch.setattr(QAService, "run_deterministic_qa", capture_qa_snapshot)

    class DeferredTracker(JobTracker):
        def __init__(self) -> None:
            super().__init__(db_path=temp_db_path)
            self.pending = None

        def start_background_task(self, _job_id: str, coroutine) -> None:
            self.pending = coroutine

    class Pipeline:
        db_path = temp_db_path

        def get_chapter(self, requested_chapter_id: int) -> dict:
            return {"id": requested_chapter_id, "book_id": book_id}

        def translate_chapter(self, **kwargs) -> str:
            captured.update(kwargs)
            return "translated"

        def get_chapter_source(self, _chapter_id: int) -> str:
            return "秘词"

        def get_chapter_translation(self, _chapter_id: int) -> str:
            return "mục tiêu cũ"

    tracker = DeferredTracker()
    service = JobService(Pipeline(), tracker=tracker)  # type: ignore[arg-type]
    job_id = service.start_translate_job(chapter_ids=[chapter_id], style_profile_id="tien_hiep")
    created = get_mobile_job(temp_db_path, job_id)
    assert created is not None
    original = db_mod.resolve_effective_glossary(temp_db_path, book_id, style_profile_id="tien_hiep")
    assert created["params"]["glossary_fingerprint"] == original.fingerprint
    assert service.get_job_status(job_id)["glossary_fingerprint"] == original.fingerprint
    with get_connection(temp_db_path) as conn:
        params_json = conn.execute(
            "SELECT params_json FROM mobile_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0]
    assert "秘词" not in params_json
    assert "mục tiêu cũ" not in params_json

    assert update_glossary_term(temp_db_path, term_id, target_term="mục tiêu mới")
    assert tracker.pending is not None
    await tracker.pending

    snapshot = captured["effective_glossary"]
    assert captured["qa_snapshot"] is snapshot
    assert snapshot.fingerprint == original.fingerprint
    assert snapshot.translate_mapping["秘词"] == "mục tiêu cũ"
