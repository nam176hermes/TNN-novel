from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import requests

from app.database.db import (
    add_book,
    add_chapter,
    get_connection,
    init_db,
    put_glossary_term,
    put_model_provider,
)
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.services import glossary_service as glossary_module
from app.mobile_api.services.glossary_service import GlossaryService
from app.database.glossary_repository import GlossaryRepository
from app.translation.self_improve import add_correction, harvest_corrections


MAX_HYBRID_TEXT_CHARS = 12_000


def _service(db_path: Path) -> GlossaryService:
    return GlossaryService.from_db_path(db_path)


def _chapter(
    db_path: Path,
    tmp_path: Path,
    book_id: int,
    number: int,
    title: str,
    text: str,
) -> int:
    raw_path = tmp_path / f"book-{book_id}-chapter-{number}.txt"
    raw_path.write_text(text, encoding="utf-8")
    return add_chapter(db_path, book_id, number, title, raw_text_path=raw_path)


def _configure_hybrid(db_path: Path, book_id: int) -> GlossaryService:
    put_model_provider(
        db_path,
        provider_id="fake",
        label="Fake",
        base_url="http://fake.invalid/v1",
        model="fake-model",
        enabled=1,
        timeout_seconds=1,
    )
    service = _service(db_path)
    service.update_extraction_settings(book_id, mode="hybrid", provider_id="fake")
    return service


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/login",
        json={
            "username": mobile_settings.admin_username,
            "password": mobile_settings.admin_password,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_phase5_schema_and_settings_migration_are_idempotent(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        term_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)")}
        settings_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(book_glossary_settings)")
        }
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(glossary_term_evidence)")}

    assert "chapter_count" in term_columns
    assert {"book_id", "extraction_mode", "provider_id", "updated_at"}.issubset(settings_columns)
    assert "idx_glossary_evidence_phase5_unique" in indexes


def test_deterministic_extraction_uses_title_repetition_suffixes_and_real_idempotent_counts(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    first_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章 太虚道君",
        "然后然后。玄天圣典现世，弟子研读玄天圣典。李青云返回青云宗。",
    )
    service = _service(temp_db_path)

    first = service.extract_chapter_terms(book_id, first_id)
    retry = service.extract_chapter_terms(book_id, first_id)

    with get_connection(temp_db_path) as conn:
        repeated = conn.execute(
            "SELECT id, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '玄天圣典'",
            (book_id,),
        ).fetchone()
        title = conn.execute(
            "SELECT occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '太虚道君'",
            (book_id,),
        ).fetchone()
        stopword = conn.execute(
            "SELECT id FROM glossary_terms WHERE book_id = ? AND source_key = '然后'",
            (book_id,),
        ).fetchone()
        evidence = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ?",
            (repeated["id"],),
        ).fetchall()

    assert first["created"] >= 4
    assert retry["created"] == 0
    assert tuple(repeated)[1:] == (2, 1)
    assert tuple(title) == (1, 1)
    assert stopword is None
    assert len(evidence) == 1
    assert "玄天圣典现世" not in evidence[0]["evidence_json"]

    second_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        2,
        "第二章 再读圣典",
        "玄天圣典、玄天圣典与玄天圣典皆在此处。",
    )
    service.extract_chapter_terms(book_id, second_id)
    with get_connection(temp_db_path) as conn:
        repeated = conn.execute(
            "SELECT occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '玄天圣典'",
            (book_id,),
        ).fetchone()
        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence e JOIN glossary_terms g ON g.id = e.term_id "
            "WHERE g.book_id = ? AND g.source_key = '玄天圣典'",
            (book_id,),
        ).fetchone()[0]

    assert tuple(repeated) == (5, 2)
    assert evidence_count == 2


def test_phase5_evidence_remains_mergeable_without_losing_provenance(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    canonical_id = put_glossary_term(
        temp_db_path,
        book_id,
        "玄天圣典",
        "",
        approved=0,
        variants="圣典",
    )
    duplicate_id = put_glossary_term(temp_db_path, book_id, "圣典", "", approved=0)
    with get_connection(temp_db_path) as conn:
        conn.executemany(
            """
            INSERT INTO glossary_term_evidence
                (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
            VALUES (?, ?, 9, 'deterministic-v2', 'chapter_observation', ?)
            """,
            [
                (canonical_id, book_id, '{"mention_count":2}'),
                (duplicate_id, book_id, '{"mention_count":1}'),
            ],
        )
        conn.commit()
    repository = GlossaryRepository(temp_db_path)

    preview = repository.preview_merge(canonical_id, [duplicate_id])
    repository.apply_merge(canonical_id, [duplicate_id], preview["digest"])

    with get_connection(temp_db_path) as conn:
        evidence = conn.execute(
            "SELECT term_id, chapter_id, extractor FROM glossary_term_evidence ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in evidence] == [
        (canonical_id, 9, "deterministic-v2"),
        (canonical_id, 9, "deterministic-v2"),
    ]


def test_correction_harvesting_requires_and_filters_book_id(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    book_a = add_book(temp_db_path, "A")
    book_b = add_book(temp_db_path, "B")
    for _ in range(2):
        add_correction(temp_db_path, book_a, 1, "灵石", "linh thạch", "tiên thạch")
        add_correction(temp_db_path, book_b, 1, "灵石", "linh thạch", "ma thạch")

    candidates = harvest_corrections(temp_db_path, book_id=book_a, min_occurrences=2)

    assert [(item["old_term"], item["new_term"]) for item in candidates] == [
        ("linh", "tiên")
    ]
    with pytest.raises(TypeError):
        harvest_corrections(temp_db_path)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_authenticated_book_settings_default_validate_provider_and_stay_book_scoped(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_a = add_book(temp_db_path, "A")
    book_b = add_book(temp_db_path, "B")
    put_model_provider(
        temp_db_path,
        provider_id="fake",
        label="Fake",
        base_url="http://fake.invalid/v1",
        model="fake-model",
        enabled=1,
    )
    monkeypatch.setattr(glossary_module, "get_db_path", lambda: temp_db_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(f"/api/books/{book_a}/glossary-settings")).status_code == 401
        headers = await _auth_headers(client)
        default = await client.get(f"/api/books/{book_a}/glossary-settings", headers=headers)
        missing_provider = await client.patch(
            f"/api/books/{book_a}/glossary-settings",
            json={"mode": "hybrid", "provider_id": "missing"},
            headers=headers,
        )
        saved = await client.patch(
            f"/api/books/{book_a}/glossary-settings",
            json={"mode": "hybrid", "provider_id": "fake"},
            headers=headers,
        )
        other = await client.get(f"/api/books/{book_b}/glossary-settings", headers=headers)
        missing_book = await client.get("/api/books/999999/glossary-settings", headers=headers)

    assert default.status_code == 200
    assert default.json() == {
        "book_id": book_a,
        "mode": "deterministic",
        "provider_id": "",
        "max_candidates_per_chapter": 100,
    }
    assert missing_provider.status_code == 422
    assert missing_provider.json()["detail"] == {"code": "provider_not_configured"}
    assert saved.status_code == 200
    assert saved.json()["mode"] == "hybrid"
    assert other.json()["mode"] == "deterministic"
    assert missing_book.status_code == 404


def test_hybrid_extraction_is_bounded_structured_deduplicated_and_cross_book_safe(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_a = add_book(temp_db_path, "A")
    book_b = add_book(temp_db_path, "B")
    put_glossary_term(temp_db_path, book_a, "幽冥真火", "A target", approved=1)
    put_glossary_term(temp_db_path, 0, "全局真火", "Global target", approved=1)
    put_glossary_term(temp_db_path, book_b, "九幽冥火", "Reviewed target", approved=1, locked=1)
    service = _configure_hybrid(temp_db_path, book_b)
    private_tail = "PRIVATE-TAIL-MUST-NOT-LEAVE"
    body = "幽冥真火与全局真火、九幽冥火、青云宗。" + ("甲" * MAX_HYBRID_TEXT_CHARS) + private_tail
    chapter_id = _chapter(temp_db_path, tmp_path, book_b, 1, "第一章 真火", body)
    captured: dict[str, object] = {}

    def fake_provider(**kwargs):
        captured.update(kwargs)
        return {
            "text": json.dumps(
                {
                    "candidates": [
                        {"source_term": "幽冥真火", "target_term": "U Minh Chân Hỏa", "term_type": "skill"},
                        {"source_term": " 幽冥真火 ", "target_term": "duplicate", "term_type": "skill"},
                        {"source_term": "全局真火", "target_term": "duplicate effective", "term_type": "skill"},
                        {"source_term": "九幽冥火", "target_term": "must not overwrite", "term_type": "skill"},
                        {"source_term": "青云宗", "target_term": "deterministic duplicate", "term_type": "sect"},
                        {"source_term": 7, "target_term": "invalid"},
                    ]
                },
                ensure_ascii=False,
            ),
            "usage": {},
        }

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider, raising=False)
    result = service.extract_chapter_terms(book_b, chapter_id)

    assert private_tail not in str(captured["prompt"])
    assert len(str(captured["prompt"])) <= MAX_HYBRID_TEXT_CHARS + 1_500
    assert captured["response_format"] == {"type": "json_object"}
    assert any(item["code"] == "provider_duplicates_ignored" for item in result["warnings"])
    with get_connection(temp_db_path) as conn:
        book_a_target = conn.execute(
            "SELECT target_term FROM glossary_terms WHERE book_id = ? AND source_key = '幽冥真火'",
            (book_a,),
        ).fetchone()[0]
        book_b_term = conn.execute(
            "SELECT target_term, review_status, approved, locked FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '幽冥真火'",
            (book_b,),
        ).fetchone()
        reviewed = conn.execute(
            "SELECT target_term, review_status, approved, locked FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '九幽冥火'",
            (book_b,),
        ).fetchone()
        hybrid_evidence_for_deterministic = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence e JOIN glossary_terms g ON g.id = e.term_id "
            "WHERE g.book_id = ? AND g.source_key = '青云宗' AND e.extractor = 'hybrid-v1'",
            (book_b,),
        ).fetchone()[0]

    assert book_a_target == "A target"
    assert tuple(book_b_term) == ("U Minh Chân Hỏa", "NEEDS_REVIEW", 0, 0)
    assert tuple(reviewed) == ("Reviewed target", "LOCKED", 1, 1)
    assert hybrid_evidence_for_deterministic == 0


@pytest.mark.parametrize(
    ("provider_result", "warning_code"),
    [
        (requests.Timeout("provider-secret /private/path"), "provider_unavailable"),
        ({"text": "{not-json", "usage": {}}, "provider_malformed_response"),
        ([], "provider_malformed_response"),
    ],
)
def test_hybrid_provider_failures_are_sanitized_and_nonfatal(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_result: object,
    warning_code: str,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "青云宗弟子返回青云宗。")

    def fake_provider(**_kwargs):
        if isinstance(provider_result, Exception):
            raise provider_result
        return provider_result

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider, raising=False)
    result = service.extract_chapter_terms(book_id, chapter_id)

    assert result["created"] >= 1
    assert result["warnings"] == [
        {"code": warning_code, "message": "Hybrid glossary extraction was skipped."}
    ]
    assert "provider-secret" not in str(result)
    assert "/private/path" not in str(result)


def test_hybrid_output_is_capped_at_one_hundred_candidates(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    sources = [f"候{chr(0x4E00 + index)}" for index in range(105)]
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "、".join(sources))

    monkeypatch.setattr(
        glossary_module,
        "call_openai_compatible_chat",
        lambda **_kwargs: {
            "text": json.dumps(
                {"candidates": [{"source_term": source, "target_term": ""} for source in sources]},
                ensure_ascii=False,
            ),
            "usage": {},
        },
        raising=False,
    )
    result = service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM glossary_terms WHERE book_id = ? AND review_status = 'NEEDS_REVIEW'",
            (book_id,),
        ).fetchone()[0]
    assert count == 100
    assert any(item["code"] == "provider_output_truncated" for item in result["warnings"])


@pytest.mark.asyncio
async def test_reextract_chapter_endpoint_is_authenticated_and_book_scoped(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_a = add_book(temp_db_path, "A")
    book_b = add_book(temp_db_path, "B")
    chapter_id = _chapter(temp_db_path, tmp_path, book_a, 1, "第一章", "青云宗弟子返回青云宗。")
    monkeypatch.setattr(glossary_module, "get_db_path", lambda: temp_db_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    path = f"/api/books/{book_a}/chapters/{chapter_id}/glossary/re-extract"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post(path)).status_code == 401
        headers = await _auth_headers(client)
        extracted = await client.post(path, headers=headers)
        wrong_book = await client.post(
            f"/api/books/{book_b}/chapters/{chapter_id}/glossary/re-extract",
            headers=headers,
        )

    assert extracted.status_code == 200
    assert extracted.json()["created"] >= 1
    assert wrong_book.status_code == 404
