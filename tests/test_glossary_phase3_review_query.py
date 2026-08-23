from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.database import glossary_repository as repository_mod
from app.database.connection import get_connection as real_get_connection
from app.database.db import add_book, get_connection, init_db, put_glossary_term
from app.mobile_api.config import mobile_settings
from app.mobile_api.main import app
from app.mobile_api.services.glossary_service import GlossaryService


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


@pytest.fixture
def glossary_api_db(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_db(temp_db_path)
    monkeypatch.setattr("app.mobile_api.services.glossary_service.get_db_path", lambda: temp_db_path)
    return temp_db_path


def test_sql_review_query_pages_and_edits_first_501st_and_last_of_10000(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    with get_connection(temp_db_path) as conn:
        conn.executemany(
            """
            INSERT INTO glossary_terms
                (book_id, source_term, source_key, target_term, approved, locked,
                 review_status, term_type, mode, priority, version, archived_at)
            VALUES (1, ?, ?, ?, 0, 0, 'NEEDS_REVIEW', 'term', 'translate', 0, 1, '')
            """,
            (
                (f"term-{index:05d}", f"term-{index:05d}", f"target-{index:05d}")
                for index in range(1, 10_001)
            ),
        )
        conn.commit()

    statements: list[str] = []

    def traced_connection(db_path: Path):
        conn = real_get_connection(db_path)
        conn.set_trace_callback(lambda statement: statements.append(statement.strip()))
        return conn

    monkeypatch.setattr(repository_mod, "get_connection", traced_connection)
    service = GlossaryService.from_db_path(temp_db_path)

    for page, source in ((1, "term-00001"), (11, "term-00501"), (200, "term-09951")):
        statements.clear()
        result = service.query_terms(
            book_id=1,
            page=page,
            per_page=50,
            review_status="NEEDS_REVIEW",
            scope="book",
            sort="source_asc",
        )
        assert result["items"][0]["source_term"] == source
        assert result["total"] == 10_000
        selects = [statement for statement in statements if statement.upper().startswith(("SELECT", "WITH"))]
        assert len(selects) <= 4
        assert not any("SELECT * FROM glossary_terms" in statement for statement in selects)

    last = service.query_terms(
        book_id=1,
        page=1,
        per_page=50,
        q="term-10000",
        review_status="NEEDS_REVIEW",
        scope="book",
        sort="source_asc",
    )["items"][0]
    for source in ("term-00001", "term-00501", "term-10000"):
        row = service.query_terms(
            book_id=1,
            page=1,
            per_page=1,
            q=source,
            review_status="NEEDS_REVIEW",
            scope="book",
            sort="source_asc",
        )["items"][0]
        updated = service.update_term_resource(
            row["id"],
            {"notes_vi": f"reviewed {source}", "expected_version": row["version"]},
        )
        assert updated is not None
        assert updated["notes_vi"] == f"reviewed {source}"
        assert updated["version"] == row["version"] + 1
    assert last["source_term"] == "term-10000"


@pytest.mark.asyncio
async def test_query_api_filters_facets_sorts_and_marks_effective_inheritance(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    inherited_id = put_glossary_term(
        glossary_api_db,
        0,
        "全局词",
        "toàn cục",
        approved=1,
        term_type="concept",
        mode="translate",
    )
    shadowed_global_id = put_glossary_term(
        glossary_api_db, 0, "覆盖词", "cũ", approved=1, term_type="term"
    )
    override_id = put_glossary_term(
        glossary_api_db,
        book_id,
        "覆盖词",
        "mới",
        approved=1,
        term_type="realm",
        mode="translate",
    )
    pending_id = put_glossary_term(
        glossary_api_db,
        book_id,
        "待审词",
        "chờ duyệt",
        approved=0,
        review_status="NEEDS_REVIEW",
        term_type="realm",
    )
    with get_connection(glossary_api_db) as conn:
        conn.executemany(
            """
            INSERT INTO glossary_term_evidence
                (term_id, book_id, chapter_id, extractor, evidence_type, evidence_json)
            VALUES (?, ?, 1, 'phase3-test', 'occurrence', ?)
            """,
            (
                (inherited_id, 0, json.dumps({"chapter": 1})),
                (inherited_id, 0, json.dumps({"chapter": 2})),
                (pending_id, book_id, json.dumps({"chapter": 3})),
            ),
        )
        conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        effective = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "review_status": "APPROVED,LOCKED",
                "mode": "translate",
                "sort": "source_asc",
            },
            headers=headers,
        )
        queue = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "scope": "book",
                "review_status": "NEEDS_REVIEW,CONFLICT",
                "term_type": "realm",
                "q": "待审",
                "locked": 0,
                "sort": "evidence_desc",
                "per_page": 50,
            },
            headers=headers,
        )
        all_rows = await client.get(
            "/api/glossary",
            params={"review_status": "APPROVED,LOCKED", "sort": "source_asc"},
            headers=headers,
        )

    assert effective.status_code == 200
    payload = effective.json()
    assert payload["scope"] == "effective"
    assert payload["page"] == 1
    assert payload["per_page"] == 50
    assert payload["pages"] == 1
    assert [(item["id"], item["inherited"]) for item in payload["items"]] == [
        (inherited_id, True),
        (override_id, False),
    ]
    assert payload["items"][0]["canonical_status"] == "APPROVED"
    assert payload["items"][0]["evidence_count"] == 2
    assert payload["items"][0]["version"] == 1
    assert payload["facets"]["review_status"] == {"APPROVED": 2}

    assert queue.status_code == 200
    queue_payload = queue.json()
    assert [item["id"] for item in queue_payload["items"]] == [pending_id]
    assert queue_payload["total"] == 1
    assert queue_payload["facets"]["term_type"] == {"realm": 1}

    assert all_rows.status_code == 200
    assert all_rows.json()["scope"] == "all"
    assert {item["id"] for item in all_rows.json()["items"]} == {
        inherited_id,
        shadowed_global_id,
        override_id,
    }


@pytest.mark.asyncio
async def test_create_patch_and_detail_return_resources_and_reject_stale_version(
    glossary_api_db: Path,
) -> None:
    book_id = add_book(glossary_api_db, "Book")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        headers["X-Request-ID"] = "phase3-resource"
        created = await client.post(
            "/api/glossary/terms",
            json={
                "book_id": book_id,
                "source_term": "新词",
                "target_term": "từ mới",
                "approved": 0,
                "review_status": "NEEDS_REVIEW",
            },
            headers=headers,
        )
        assert created.status_code == 201
        created_term = created.json()

        updated = await client.patch(
            f"/api/glossary/terms/{created_term['id']}",
            json={"notes_vi": "checked", "expected_version": created_term["version"]},
            headers=headers,
        )
        stale = await client.patch(
            f"/api/glossary/terms/{created_term['id']}",
            json={"notes_vi": "stale", "expected_version": created_term["version"]},
            headers=headers,
        )
        legacy = await client.patch(
            f"/api/glossary/terms/{created_term['id']}",
            json={"notes_vi": "legacy accepted"},
            headers=headers,
        )
        detail = await client.get(f"/api/glossary/terms/{created_term['id']}", headers=headers)

    assert created_term["canonical_status"] == "NEEDS_REVIEW"
    assert created_term["version"] == 1
    assert updated.status_code == 200
    assert updated.json()["notes_vi"] == "checked"
    assert updated.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json() == {"detail": {"code": "stale_version"}}
    assert "checked" not in stale.text
    assert legacy.status_code == 200
    assert legacy.json()["notes_vi"] == "legacy accepted"
    assert detail.status_code == 200
    assert detail.json()["id"] == created_term["id"]
    assert detail.json()["history"][-1]["request_id"] == "phase3-resource"
    assert detail.json()["evidence"] == []


@pytest.mark.asyncio
async def test_query_api_rejects_unknown_filters_and_clamps_legacy_page_size(
    glossary_api_db: Path,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _auth_headers(client)
        bad_status = await client.get("/api/glossary?review_status=APPROVED,BOGUS", headers=headers)
        bad_sort = await client.get("/api/glossary?sort=DROP_TABLE", headers=headers)
        bad_scope = await client.get("/api/glossary?scope=book", headers=headers)
        legacy_page = await client.get("/api/glossary?per_page=500&include_weak=1", headers=headers)

    assert bad_status.status_code == 422
    assert bad_sort.status_code == 422
    assert bad_scope.status_code == 422
    assert legacy_page.status_code == 200
    assert legacy_page.json()["per_page"] == 200
