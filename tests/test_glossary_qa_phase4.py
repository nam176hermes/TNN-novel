from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.database.db import (
    add_book,
    add_chapter,
    get_connection,
    init_db,
    load_glossary,
    put_glossary_term,
    update_chapter_paths,
)
import app.database.db as db
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.routers import glossary as glossary_router
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService


def make_glossary_service(db_path: Path) -> GlossaryService:
    service = object.__new__(GlossaryService)
    service.db_path = db_path
    return service


def make_pipeline(db_path: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = db_path
    return pipeline


async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={"username": mobile_settings.admin_username, "password": mobile_settings.admin_password},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_phase4_glossary_and_qa_columns_exist(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        glossary_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)")}
        qa_columns = {row["name"] for row in conn.execute("PRAGMA table_info(qa_reports)")}

    assert {
        "alternatives",
        "gender",
        "first_seen_chapter_id",
        "first_seen_chapter_number",
        "review_status",
        "source_context",
        "updated_at",
    }.issubset(glossary_columns)
    assert {
        "job_id",
        "overall_status",
        "missing_paragraph_warning",
        "chinese_leakage_count",
        "name_consistency_status",
        "term_consistency_status",
        "length_ratio",
        "repetition_warning",
        "style_warnings",
        "glossary_violations",
        "suggested_fixes",
        "updated_at",
    }.issubset(qa_columns)


def test_rejected_term_is_retained_and_not_injected(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân Tông", approved=0)

    with get_connection(temp_db_path) as conn:
        term_id = conn.execute("SELECT id FROM glossary_terms WHERE source_term = ?", ("青云宗",)).fetchone()["id"]

    service = make_glossary_service(temp_db_path)

    assert service.reject_term(term_id) is True
    with get_connection(temp_db_path) as conn:
        term = conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()

    assert term is not None
    assert term["review_status"] == "REJECTED"
    assert term["approved"] == -1
    assert "青云宗" not in load_glossary(temp_db_path, book_id)


def test_extract_chapter_terms_creates_reviewable_candidates(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    raw_path = tmp_path / "chapter.txt"
    raw_path.write_text("李青云来到青云宗，取出筑基丹。随后李青云进入练气境。", encoding="utf-8")
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 3, "第三章 青云宗", raw_text_path=raw_path)

    service = make_glossary_service(temp_db_path)
    result = service.extract_chapter_terms(book_id, chapter_id)

    assert result["created"] >= 3
    with get_connection(temp_db_path) as conn:
        rows = conn.execute(
            """SELECT source_term, review_status, first_seen_chapter_id,
                      first_seen_chapter_number, source_context
               FROM glossary_terms
               WHERE book_id = ?
               ORDER BY source_term""",
            (book_id,),
        ).fetchall()
    terms = {row["source_term"]: dict(row) for row in rows}

    assert "李青云" in terms
    assert "青云宗" in terms
    assert "筑基丹" in terms
    assert terms["青云宗"]["review_status"] == "NEEDS_REVIEW"
    assert terms["青云宗"]["first_seen_chapter_id"] == chapter_id
    assert terms["青云宗"]["first_seen_chapter_number"] == 3
    assert "青云宗" in terms["青云宗"]["source_context"]


def test_extraction_does_not_overwrite_approved_glossary_translation(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    raw_path = tmp_path / "chapter.txt"
    raw_path.write_text("青云宗弟子再次来到青云宗。", encoding="utf-8")
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 4, "第四章 青云宗", raw_text_path=raw_path)
    put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân Tông", approved=1, locked=0)

    service = make_glossary_service(temp_db_path)
    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            "SELECT target_term, approved, review_status FROM glossary_terms WHERE book_id = ? AND source_term = ?",
            (book_id, "青云宗"),
        ).fetchone()

    assert term["target_term"] == "Thanh Vân Tông"
    assert term["approved"] == 1
    assert term["review_status"] == "APPROVED"


def test_candidate_insert_does_not_overwrite_approved_glossary_translation(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân Tông", approved=1, locked=0)

    put_glossary_term(
        temp_db_path,
        book_id,
        "青云宗",
        "",
        approved=0,
        review_status="NEEDS_REVIEW",
        source_context="青云宗 candidate context",
    )

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            "SELECT target_term, approved, review_status, source_context FROM glossary_terms WHERE book_id = ? AND source_term = ?",
            (book_id, "青云宗"),
        ).fetchone()

    assert term["target_term"] == "Thanh Vân Tông"
    assert term["approved"] == 1
    assert term["review_status"] == "APPROVED"
    assert term["source_context"] == "青云宗 candidate context"


def test_prompt_glossary_selection_prioritizes_locked_and_excludes_rejected(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân Tông", approved=1, locked=1, priority=10)
    put_glossary_term(temp_db_path, book_id, "筑基", "Trúc Cơ", approved=1, locked=0, priority=5)
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", approved=0)
    with get_connection(temp_db_path) as conn:
        conn.execute(
            "UPDATE glossary_terms SET review_status = 'REJECTED', approved = -1 WHERE source_term = '灵石'",
        )
        conn.commit()

    selected = db.select_prompt_glossary_terms(
        temp_db_path,
        book_id,
        "青云宗弟子取出灵石后开始筑基。",
        max_terms=5,
        max_chars=200,
    )

    assert [term["source_term"] for term in selected] == ["青云宗", "筑基"]
    assert selected[0]["locked"] == 1


def test_deterministic_qa_detects_core_chapter_warnings(temp_db_path: Path, tmp_path: Path) -> None:
    init_db(temp_db_path)
    raw_path = tmp_path / "raw.txt"
    translated_path = tmp_path / "translated.txt"
    raw_path.write_text("青云宗弟子取出灵石。\n\n他进入筑基境。", encoding="utf-8")
    translated_path.write_text("Đệ tử lấy ra 灵石.\n\nĐệ tử lấy ra 灵石.\n\nĐệ tử lấy ra 灵石.", encoding="utf-8")
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter", raw_text_path=raw_path)
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translated_path)
    put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân Tông", approved=1, locked=1)
    put_glossary_term(temp_db_path, book_id, "灵石", "linh thạch", approved=1, locked=1)

    service = QAService(make_pipeline(temp_db_path))
    report = service.run_deterministic_qa(book_id, chapter_id, job_id="job-1")

    assert report["overall_status"] == "FAIL"
    assert report["chinese_leakage_count"] >= 1
    assert report["repetition_warning"]
    assert report["term_consistency_status"] == "FAIL"
    assert any(item["source_term"] == "灵石" for item in report["glossary_violations"])

    saved = service.get_qa_report(book_id, chapter_id)
    assert saved is not None
    assert saved["overall_status"] == "FAIL"
    saved_json = saved["report_json"]
    assert isinstance(saved_json, dict)
    assert saved_json["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_glossary_conflicts_api_reports_target_reuse_and_requires_auth(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path)
    service = make_glossary_service(temp_db_path)
    app.dependency_overrides[glossary_router.get_glossary_service] = lambda: service
    try:
        book_id = add_book(temp_db_path, "Book")
        put_glossary_term(temp_db_path, book_id, "李青云", "Thanh Vân", approved=1, term_type="character")
        put_glossary_term(temp_db_path, book_id, "青云宗", "Thanh Vân", approved=1, term_type="sect")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.get(f"/api/glossary/conflicts?book_id={book_id}")
            headers = await auth_headers(client)
            response = await client.get(f"/api/glossary/conflicts?book_id={book_id}", headers=headers)

        assert denied.status_code == 401
        assert response.status_code == 200
        conflicts = response.json()["conflicts"]
        assert any(conflict["type"] == "target_reuse" for conflict in conflicts)
    finally:
        app.dependency_overrides.pop(glossary_router.get_glossary_service, None)
