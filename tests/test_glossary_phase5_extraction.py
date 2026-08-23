from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
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
    with get_connection(temp_db_path) as conn:
        phase5_index = next(
            row
            for row in conn.execute("PRAGMA index_list(glossary_term_evidence)")
            if row["name"] == "idx_glossary_evidence_phase5_unique"
        )
    assert phase5_index["unique"] == 1


def test_phase5_migration_coalesces_duplicate_identities_before_enforcing_uniqueness(
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    provenance_book_id = add_book(temp_db_path, "Provenance")
    term_id = put_glossary_term(temp_db_path, book_id, "玄天圣典", "", approved=0)
    with get_connection(temp_db_path) as conn:
        conn.execute("DROP INDEX idx_glossary_evidence_phase5_unique")
        conn.executemany(
            """
            INSERT INTO glossary_term_evidence
                (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
            VALUES (?, ?, 7, 'deterministic-v2', 'chapter_observation', ?)
            """,
            [
                (term_id, book_id, '{"mention_count":2,"source_fingerprint":"a"}'),
                (term_id, provenance_book_id, '{"mention_count":3,"source_fingerprint":"b"}'),
            ],
        )
        conn.commit()

    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        evidence = conn.execute(
            "SELECT book_id, evidence_json FROM glossary_term_evidence "
            "WHERE term_id = ? AND chapter_id = 7 AND extractor = 'deterministic-v2'",
            (term_id,),
        ).fetchall()
        phase5_index = next(
            row
            for row in conn.execute("PRAGMA index_list(glossary_term_evidence)")
            if row["name"] == "idx_glossary_evidence_phase5_unique"
        )
        counts = conn.execute(
            "SELECT occurrence_count, chapter_count FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()

    assert len(evidence) == 1
    assert evidence[0]["book_id"] == book_id
    assert json.loads(evidence[0]["evidence_json"]) == {
        "evidence_types": [],
        "mention_count": 3,
        "provenance_book_ids": [book_id, provenance_book_id],
        "source_fingerprints": ["a", "b"],
        "title_match": False,
    }
    assert phase5_index["unique"] == 1
    assert tuple(counts) == (3, 1)


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


def test_reextract_reconciles_stale_evidence_and_zeroes_real_counts(
    temp_db_path: Path,
    tmp_path: Path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章 圣典",
        "玄天圣典现世，弟子再次研读玄天圣典。",
    )
    service = _service(temp_db_path)
    service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        raw_path = Path(
            conn.execute("SELECT raw_text_path FROM chapters WHERE id = ?", (chapter_id,)).fetchone()[0]
        )
    raw_path.write_text("弟子静坐。", encoding="utf-8")

    result = service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            "SELECT id, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '玄天圣典'",
            (book_id,),
        ).fetchone()
        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence "
            "WHERE term_id = ? AND chapter_id = ? AND extractor = 'deterministic-v2'",
            (term["id"], chapter_id),
        ).fetchone()[0]

    assert result["created"] == 0
    assert tuple(term)[1:] == (0, 0)
    assert evidence_count == 0


@pytest.mark.parametrize(
    ("mode", "expected_extractors", "expected_provider_calls"),
    [
        ("deterministic", {"deterministic-v2"}, 0),
        ("hybrid", {"deterministic-v2", "hybrid-v1"}, 1),
    ],
)
def test_empty_raw_file_authoritatively_clears_mode_evidence_without_provider_call(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_extractors: set[str],
    expected_provider_calls: int,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, f"Book {mode}")
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章",
        "玄天圣典现世，弟子再次研读玄天圣典。罕词也在此处。",
    )
    service = _service(temp_db_path)
    provider_calls = 0
    if mode == "hybrid":
        service = _configure_hybrid(temp_db_path, book_id)

    def fake_provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {
            "text": json.dumps({
                "candidates": [{"source_term": "罕词", "target_term": "Rare"}]
            }),
            "usage": {},
        }

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        before_extractors = {
            str(row["extractor"])
            for row in conn.execute(
                "SELECT extractor FROM glossary_term_evidence WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchall()
        }
        raw_path = Path(
            conn.execute(
                "SELECT raw_text_path FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()[0]
        )
    raw_path.write_text("", encoding="utf-8")

    result = service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        remaining_evidence = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence WHERE chapter_id = ? "
            "AND extractor IN ('deterministic-v2', 'hybrid-v1')",
            (chapter_id,),
        ).fetchone()[0]
        counts = conn.execute(
            "SELECT source_key, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key IN ('玄天圣典', '罕词') ORDER BY source_key",
            (book_id,),
        ).fetchall()

    assert before_extractors == expected_extractors
    assert provider_calls == expected_provider_calls
    assert result["warnings"] == []
    assert remaining_evidence == 0
    assert all(tuple(row)[1:] == (0, 0) for row in counts)


def test_missing_raw_artifact_is_non_authoritative_and_preserves_evidence(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章",
        "玄天圣典现世，众人再次研读玄天圣典。罕词也在此处。",
    )
    provider_calls = 0

    def fake_provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {
            "text": json.dumps({
                "candidates": [{"source_term": "罕词", "target_term": "Rare"}]
            }),
            "usage": {},
        }

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        raw_path = Path(
            conn.execute(
                "SELECT raw_text_path FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()[0]
        )
        before_evidence = [
            tuple(row)
            for row in conn.execute(
                "SELECT term_id, extractor, evidence_json FROM glossary_term_evidence "
                "WHERE chapter_id = ? ORDER BY term_id, extractor",
                (chapter_id,),
            ).fetchall()
        ]
        before_counts = [
            tuple(row)
            for row in conn.execute(
                "SELECT source_key, occurrence_count, chapter_count, version "
                "FROM glossary_terms WHERE book_id = ? ORDER BY source_key",
                (book_id,),
            ).fetchall()
        ]
    raw_path.unlink()

    result = service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        after_evidence = [
            tuple(row)
            for row in conn.execute(
                "SELECT term_id, extractor, evidence_json FROM glossary_term_evidence "
                "WHERE chapter_id = ? ORDER BY term_id, extractor",
                (chapter_id,),
            ).fetchall()
        ]
        after_counts = [
            tuple(row)
            for row in conn.execute(
                "SELECT source_key, occurrence_count, chapter_count, version "
                "FROM glossary_terms WHERE book_id = ? ORDER BY source_key",
                (book_id,),
            ).fetchall()
        ]

    assert provider_calls == 1
    assert result == {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "candidates": [],
        "warnings": [],
    }
    assert after_evidence == before_evidence
    assert after_counts == before_counts


def test_phase5_evidence_remains_mergeable_without_losing_provenance(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    provenance_book_id = add_book(temp_db_path, "Provenance")
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
            VALUES (?, ?, ?, 'deterministic-v2', 'chapter_observation', ?)
            """,
            [
                (canonical_id, book_id, 9, '{"mention_count":2,"source_fingerprint":"canonical"}'),
                (duplicate_id, provenance_book_id, 9, '{"mention_count":1,"source_fingerprint":"alias"}'),
                (duplicate_id, provenance_book_id, 10, '{"mention_count":4,"source_fingerprint":"alias-2"}'),
            ],
        )
        conn.commit()
    repository = GlossaryRepository(temp_db_path)

    preview = repository.preview_merge(canonical_id, [duplicate_id])
    repository.apply_merge(canonical_id, [duplicate_id], preview["digest"])
    future = repository.record_extraction_candidates(
        book_id=book_id,
        chapter_id=11,
        chapter_number=11,
        extractor="deterministic-v2",
        candidates=[{
            "source_term": "圣典",
            "mention_count": 3,
            "evidence_types": ["repeated_ngram"],
        }],
    )
    retry = repository.record_extraction_candidates(
        book_id=book_id,
        chapter_id=11,
        chapter_number=11,
        extractor="deterministic-v2",
        candidates=[{
            "source_term": "圣典",
            "mention_count": 3,
            "evidence_types": ["repeated_ngram"],
        }],
    )

    with get_connection(temp_db_path) as conn:
        evidence = conn.execute(
            "SELECT term_id, book_id, chapter_id, extractor, evidence_json "
            "FROM glossary_term_evidence WHERE extractor = 'deterministic-v2' ORDER BY chapter_id"
        ).fetchall()
        canonical = conn.execute(
            "SELECT occurrence_count, chapter_count FROM glossary_terms WHERE id = ?",
            (canonical_id,),
        ).fetchone()
        duplicate = conn.execute(
            "SELECT archived_at FROM glossary_terms WHERE id = ?", (duplicate_id,)
        ).fetchone()
        merge_relation = conn.execute(
            "SELECT book_id, evidence_json FROM glossary_term_evidence "
            "WHERE term_id = ? AND extractor = 'merge-v1' AND evidence_type = 'merge_alias'",
            (canonical_id,),
        ).fetchone()

    assert [(row["term_id"], row["chapter_id"]) for row in evidence] == [
        (canonical_id, 9),
        (canonical_id, 10),
        (canonical_id, 11),
    ]
    assert evidence[0]["book_id"] == book_id
    assert json.loads(evidence[0]["evidence_json"])["provenance_book_ids"] == [
        book_id,
        provenance_book_id,
    ]
    assert tuple(canonical) == (9, 3)
    assert duplicate["archived_at"]
    assert merge_relation["book_id"] == book_id
    assert json.loads(merge_relation["evidence_json"])["canonical_term_id"] == canonical_id
    assert json.loads(merge_relation["evidence_json"])["merged_term_id"] == duplicate_id
    assert future["updated"] == 1
    assert retry["skipped"] == 1


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


@pytest.mark.asyncio
async def test_glossary_settings_and_reextract_hide_cross_owner_books_before_provider_access(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Private Book")
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章",
        "幽冥真火现世。",
    )
    _configure_hybrid(temp_db_path, book_id)
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE books SET owner_user_id = 'external-owner' WHERE id = ?", (book_id,))
        conn.commit()
    monkeypatch.setattr(glossary_module, "get_db_path", lambda: temp_db_path)
    provider_calls = 0

    def forbidden_provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not be called for a cross-owner request")

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", forbidden_provider)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        get_response = await client.get(
            f"/api/books/{book_id}/glossary-settings", headers=headers
        )
        patch_response = await client.patch(
            f"/api/books/{book_id}/glossary-settings",
            json={"mode": "hybrid", "provider_id": "fake"},
            headers=headers,
        )
        extract_response = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/glossary/re-extract",
            headers=headers,
        )

    assert [get_response.status_code, patch_response.status_code, extract_response.status_code] == [
        404,
        404,
        404,
    ]
    assert get_response.json() == patch_response.json() == extract_response.json() == {
        "detail": {"code": "book_not_found"}
    }
    assert provider_calls == 0
    assert _service(temp_db_path).get_extraction_settings(book_id)["mode"] == "hybrid"


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
        reviewed_hybrid_evidence = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence e JOIN glossary_terms g ON g.id = e.term_id "
            "WHERE g.book_id = ? AND g.source_key = '九幽冥火' AND e.extractor = 'hybrid-v1'",
            (book_b,),
        ).fetchone()

    assert book_a_target == "A target"
    assert tuple(book_b_term) == ("U Minh Chân Hỏa", "NEEDS_REVIEW", 0, 0)
    assert tuple(reviewed) == ("Reviewed target", "LOCKED", 1, 1)
    assert hybrid_evidence_for_deterministic == 0
    assert "proposed_targets" not in json.loads(reviewed_hybrid_evidence["evidence_json"])


def test_hybrid_success_reconciles_stale_output_but_provider_failure_preserves_last_observation(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章 真火",
        "幽冥真火与九幽冥火同时现世。",
    )
    responses: list[object] = [
        {"text": json.dumps({"candidates": [{"source_term": "幽冥真火", "target_term": "A"}]}), "usage": {}},
        {"text": json.dumps({"candidates": [{"source_term": "九幽冥火", "target_term": "B"}]}), "usage": {}},
        requests.Timeout("private-provider-timeout"),
        {"text": json.dumps({"candidates": []}), "usage": {}},
    ]

    def fake_provider(**_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)
    service.extract_chapter_terms(book_id, chapter_id)
    failed = service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        after_failure = conn.execute(
            "SELECT source_key, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key IN ('幽冥真火', '九幽冥火') ORDER BY source_key",
            (book_id,),
        ).fetchall()
    service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        after_empty = conn.execute(
            "SELECT source_key, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key IN ('幽冥真火', '九幽冥火') ORDER BY source_key",
            (book_id,),
        ).fetchall()

    assert failed["warnings"] == [
        {"code": "provider_unavailable", "message": "Hybrid glossary extraction was skipped."}
    ]
    assert [tuple(row) for row in after_failure] == [
        ("九幽冥火", 1, 1),
        ("幽冥真火", 0, 0),
    ]
    assert [tuple(row) for row in after_empty] == [
        ("九幽冥火", 0, 0),
        ("幽冥真火", 0, 0),
    ]


def test_hybrid_retains_pending_proposals_and_conflicts_without_overwriting_reviewed_metadata(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    blank_id = put_glossary_term(
        temp_db_path,
        book_id,
        "幽冥真火",
        "",
        approved=0,
        notes_vi="blank note",
        variants="blank variant",
    )
    conflict_id = put_glossary_term(
        temp_db_path,
        book_id,
        "九幽冥火",
        "Old Conflict",
        approved=0,
        notes_vi="conflict note",
        variants="conflict variant",
        alternatives="legacy proposal",
    )
    approved_id = put_glossary_term(
        temp_db_path,
        book_id,
        "天外神火",
        "Reviewed",
        approved=1,
        locked=1,
        notes_vi="reviewed note",
        alternatives="reviewed alternative",
    )
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章 真火",
        "幽冥真火、九幽冥火与天外神火同时现世。",
    )
    monkeypatch.setattr(
        glossary_module,
        "call_openai_compatible_chat",
        lambda **_kwargs: {
            "text": json.dumps({
                "candidates": [
                    {"source_term": "幽冥真火", "target_term": "New Blank"},
                    {"source_term": "九幽冥火", "target_term": "New Conflict"},
                    {"source_term": "天外神火", "target_term": "Must Not Replace"},
                ]
            }),
            "usage": {},
        },
    )

    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        blank = conn.execute(
            "SELECT target_term, review_status, notes_vi, variants, alternatives FROM glossary_terms WHERE id = ?",
            (blank_id,),
        ).fetchone()
        conflict = conn.execute(
            "SELECT target_term, review_status, notes_vi, variants, alternatives FROM glossary_terms WHERE id = ?",
            (conflict_id,),
        ).fetchone()
        approved = conn.execute(
            "SELECT target_term, review_status, approved, locked, notes_vi, alternatives "
            "FROM glossary_terms WHERE id = ?",
            (approved_id,),
        ).fetchone()
        evidence = {
            row["term_id"]: json.loads(row["evidence_json"])
            for row in conn.execute(
                "SELECT term_id, evidence_json FROM glossary_term_evidence "
                "WHERE extractor = 'hybrid-v1' AND chapter_id = ?",
                (chapter_id,),
            ).fetchall()
        }

    assert tuple(blank) == ("New Blank", "NEEDS_REVIEW", "blank note", "blank variant", "")
    assert tuple(conflict) == (
        "Old Conflict",
        "CONFLICT",
        "conflict note",
        "conflict variant",
        "legacy proposal|New Conflict",
    )
    assert tuple(approved) == (
        "Reviewed",
        "LOCKED",
        1,
        1,
        "reviewed note",
        "reviewed alternative",
    )
    assert evidence[blank_id]["proposed_targets"] == ["New Blank"]
    assert evidence[conflict_id]["proposed_targets"] == ["New Conflict"]
    assert "proposed_targets" not in evidence[approved_id]


@pytest.mark.parametrize(
    ("review_action", "expected_state"),
    [
        ("approve", ("APPROVED", 1, 0)),
        ("lock", ("LOCKED", 1, 1)),
        ("reject", ("REJECTED", -1, 0)),
    ],
)
def test_reviewed_hybrid_source_is_observed_without_proposal_mutation_until_it_disappears(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_action: str,
    expected_state: tuple[str, int, int],
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, f"Book {review_action}")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "罕词也在此处。")
    responses: list[object] = [
        {"text": json.dumps({"candidates": [{"source_term": "罕词", "target_term": "Rare"}]}), "usage": {}},
        {
            "text": json.dumps({
                "candidates": [{"source_term": "罕词", "target_term": "Must Not Replace"}]
            }),
            "usage": {},
        },
        requests.Timeout("private-provider-timeout"),
        {"text": json.dumps({"candidates": []}), "usage": {}},
    ]

    def fake_provider(**_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)
    repository = GlossaryRepository(temp_db_path)
    with get_connection(temp_db_path) as conn:
        term_id = int(
            conn.execute(
                "SELECT id FROM glossary_terms WHERE book_id = ? AND source_key = '罕词'",
                (book_id,),
            ).fetchone()[0]
        )
    repository.update(
        term_id,
        notes_vi="reviewed note",
        alternatives="reviewed alternative",
    )
    if review_action == "approve":
        repository.approve(term_id)
    elif review_action == "lock":
        repository.set_locked(term_id, True)
    else:
        repository.reject(term_id)

    with get_connection(temp_db_path) as conn:
        before = conn.execute(
            "SELECT target_term, review_status, approved, locked, notes_vi, alternatives, "
            "occurrence_count, chapter_count, version FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        before_evidence = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ? "
            "AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (term_id, chapter_id),
        ).fetchone()[0]

    service.extract_chapter_terms(book_id, chapter_id)
    failed = service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        after_failure = conn.execute(
            "SELECT target_term, review_status, approved, locked, notes_vi, alternatives, "
            "occurrence_count, chapter_count, version FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        stable_evidence = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ? "
            "AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (term_id, chapter_id),
        ).fetchall()

    service.extract_chapter_terms(book_id, chapter_id)
    with get_connection(temp_db_path) as conn:
        after_disappearance = conn.execute(
            "SELECT target_term, review_status, approved, locked, notes_vi, alternatives, "
            "occurrence_count, chapter_count, version FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        remaining_evidence = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence WHERE term_id = ? "
            "AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (term_id, chapter_id),
        ).fetchone()[0]

    assert tuple(before)[1:4] == expected_state
    assert tuple(before)[:6] == (
        "Rare", *expected_state, "reviewed note", "reviewed alternative",
    )
    assert tuple(before)[6:8] == (1, 1)
    assert tuple(after_failure) == tuple(before)
    assert failed["warnings"] == [
        {"code": "provider_unavailable", "message": "Hybrid glossary extraction was skipped."}
    ]
    assert [row["evidence_json"] for row in stable_evidence] == [before_evidence]
    assert tuple(after_disappearance)[:6] == tuple(before)[:6]
    assert tuple(after_disappearance)[6:8] == (0, 0)
    assert after_disappearance["version"] == before["version"] + 1
    assert remaining_evidence == 0


def test_reviewed_hybrid_alias_observation_routes_to_canonical_without_reactivation(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    canonical_id = put_glossary_term(
        temp_db_path,
        book_id,
        "玄天圣典",
        "Canonical",
        approved=1,
        variants="圣典",
    )
    duplicate_id = put_glossary_term(temp_db_path, book_id, "圣典", "Alias", approved=0)
    repository = GlossaryRepository(temp_db_path)
    preview = repository.preview_merge(canonical_id, [duplicate_id])
    repository.apply_merge(canonical_id, [duplicate_id], preview["digest"])
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "圣典再次现世。")
    monkeypatch.setattr(
        glossary_module,
        "call_openai_compatible_chat",
        lambda **_kwargs: {
            "text": json.dumps({
                "candidates": [{"source_term": "圣典", "target_term": "Must Not Replace"}]
            }),
            "usage": {},
        },
    )

    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        canonical = conn.execute(
            "SELECT target_term, review_status, occurrence_count, chapter_count "
            "FROM glossary_terms WHERE id = ?",
            (canonical_id,),
        ).fetchone()
        duplicate = conn.execute(
            "SELECT archived_at FROM glossary_terms WHERE id = ?", (duplicate_id,)
        ).fetchone()
        evidence_term_ids = {
            int(row["term_id"])
            for row in conn.execute(
                "SELECT term_id FROM glossary_term_evidence WHERE chapter_id = ? "
                "AND extractor = 'hybrid-v1'",
                (chapter_id,),
            ).fetchall()
        }

    assert tuple(canonical) == ("Canonical", "APPROVED", 1, 1)
    assert duplicate["archived_at"]
    assert evidence_term_ids == {canonical_id}


def test_rejected_hybrid_source_with_deterministic_evidence_remains_observed(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "罕词也在此处。")
    proposed_targets = iter(("Rare", "Must Not Replace"))
    monkeypatch.setattr(
        glossary_module,
        "call_openai_compatible_chat",
        lambda **_kwargs: {
            "text": json.dumps({
                "candidates": [
                    {"source_term": "罕词", "target_term": next(proposed_targets)}
                ]
            }),
            "usage": {},
        },
    )
    service.extract_chapter_terms(book_id, chapter_id)
    repository = GlossaryRepository(temp_db_path)
    with get_connection(temp_db_path) as conn:
        term_id = int(
            conn.execute(
                "SELECT id FROM glossary_terms WHERE book_id = ? AND source_key = '罕词'",
                (book_id,),
            ).fetchone()[0]
        )
        raw_path = Path(
            conn.execute(
                "SELECT raw_text_path FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()[0]
        )
    repository.reject(term_id)
    raw_path.write_text("罕词出现，罕词再次出现。", encoding="utf-8")
    repository.record_extraction_candidates(
        book_id=book_id,
        chapter_id=chapter_id,
        chapter_number=1,
        extractor="deterministic-v2",
        candidates=[{
            "source_term": "罕词",
            "mention_count": 2,
            "evidence_types": ["repeated_token"],
        }],
    )
    with get_connection(temp_db_path) as conn:
        before = conn.execute(
            "SELECT target_term, review_status, occurrence_count, chapter_count, version "
            "FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        before_hybrid = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ? "
            "AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (term_id, chapter_id),
        ).fetchone()[0]

    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        after = conn.execute(
            "SELECT target_term, review_status, occurrence_count, chapter_count, version "
            "FROM glossary_terms WHERE id = ?",
            (term_id,),
        ).fetchone()
        after_hybrid = conn.execute(
            "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ? "
            "AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (term_id, chapter_id),
        ).fetchone()

    assert tuple(before)[:4] == ("Rare", "REJECTED", 2, 1)
    assert tuple(after) == tuple(before)
    assert after_hybrid is not None
    assert json.loads(before_hybrid)["proposed_targets"] == ["Rare"]
    assert json.loads(after_hybrid["evidence_json"]) == {
        **json.loads(before_hybrid),
        "mention_count": 2,
    }


def test_hybrid_retry_and_concurrent_repository_runs_keep_one_identity_without_count_inflation(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    chapter_id = _chapter(temp_db_path, tmp_path, book_id, 1, "第一章", "幽冥真火现世。")
    provider_response = {
        "text": json.dumps({"candidates": [{"source_term": "幽冥真火", "target_term": "Proposal"}]}),
        "usage": {},
    }
    monkeypatch.setattr(
        glossary_module,
        "call_openai_compatible_chat",
        lambda **_kwargs: provider_response,
    )

    service.extract_chapter_terms(book_id, chapter_id)
    retry = service.extract_chapter_terms(book_id, chapter_id)
    repository = GlossaryRepository(temp_db_path)
    concurrent_candidate = [{
        "source_term": "并发圣典",
        "mention_count": 2,
        "evidence_types": ["repeated_ngram"],
    }]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(
            lambda _index: repository.record_extraction_candidates(
                book_id=book_id,
                chapter_id=99,
                chapter_number=99,
                extractor="deterministic-v2",
                candidates=concurrent_candidate,
            ),
            range(8),
        ))

    with get_connection(temp_db_path) as conn:
        hybrid = conn.execute(
            "SELECT id, occurrence_count, chapter_count, version FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '幽冥真火'",
            (book_id,),
        ).fetchone()
        hybrid_evidence = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence "
            "WHERE term_id = ? AND chapter_id = ? AND extractor = 'hybrid-v1'",
            (hybrid["id"], chapter_id),
        ).fetchone()[0]
        concurrent = conn.execute(
            "SELECT id, occurrence_count, chapter_count FROM glossary_terms "
            "WHERE book_id = ? AND source_key = '并发圣典'",
            (book_id,),
        ).fetchone()
        concurrent_evidence = conn.execute(
            "SELECT COUNT(*) FROM glossary_term_evidence "
            "WHERE term_id = ? AND chapter_id = 99 AND extractor = 'deterministic-v2'",
            (concurrent["id"],),
        ).fetchone()[0]

    assert retry["skipped"] >= 1
    assert tuple(hybrid)[1:] == (1, 1, 1)
    assert hybrid_evidence == 1
    assert sum(result["created"] for result in results) == 1
    assert tuple(concurrent)[1:] == (2, 1)
    assert concurrent_evidence == 1


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


def test_hybrid_nfkc_matches_compatibility_surface_and_keeps_bounded_original_context(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    private_tail = "PRIVATE-NFKC-TAIL"
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        "第一章 ＡＢＣ神器",
        "众人发现ＡＢＣ神器。" + ("甲" * MAX_HYBRID_TEXT_CHARS) + private_tail,
    )
    captured: dict[str, object] = {}

    def fake_provider(**kwargs):
        captured.update(kwargs)
        return {
            "text": json.dumps({
                "candidates": [{"source_term": "ＡＢＣ神器", "target_term": "Thần khí ABC"}]
            }),
            "usage": {},
        }

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            "SELECT source_term, source_context, occurrence_count, chapter_count "
            "FROM glossary_terms WHERE book_id = ? AND source_key = 'abc神器'",
            (book_id,),
        ).fetchone()

    assert tuple(term) == ("ABC神器", "众人发现ＡＢＣ神器。" + ("甲" * 27), 2, 1)
    assert private_tail not in str(captured["prompt"])


def test_hybrid_nfkc_maps_combining_sequence_to_original_bounded_context(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    service = _configure_hybrid(temp_db_path, book_id)
    original_surface = "A\u030A神器"
    private_tail = "PRIVATE-COMBINING-TAIL"
    chapter_id = _chapter(
        temp_db_path,
        tmp_path,
        book_id,
        1,
        f"第一章 {original_surface}",
        f"众人发现{original_surface}。" + ("甲" * MAX_HYBRID_TEXT_CHARS) + private_tail,
    )
    captured: dict[str, object] = {}

    def fake_provider(**kwargs):
        captured.update(kwargs)
        return {
            "text": json.dumps({
                "candidates": [{"source_term": original_surface, "target_term": "Thần khí Å"}]
            }),
            "usage": {},
        }

    monkeypatch.setattr(glossary_module, "call_openai_compatible_chat", fake_provider)
    service.extract_chapter_terms(book_id, chapter_id)

    with get_connection(temp_db_path) as conn:
        term = conn.execute(
            "SELECT id, source_term, source_context, occurrence_count, chapter_count "
            "FROM glossary_terms WHERE book_id = ? AND source_key = 'å神器'",
            (book_id,),
        ).fetchone()
        evidence = json.loads(
            conn.execute(
                "SELECT evidence_json FROM glossary_term_evidence WHERE term_id = ? "
                "AND chapter_id = ? AND extractor = 'hybrid-v1'",
                (term["id"], chapter_id),
            ).fetchone()[0]
        )

    assert tuple(term)[1:] == (
        "Å神器",
        f"众人发现{original_surface}。" + ("甲" * 27),
        2,
        1,
    )
    assert evidence["title_match"] is True
    assert private_tail not in str(captured["prompt"])


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
