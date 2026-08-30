from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

import httpx
import pytest
import requests

from app.database import glossary_repository as repository_module
from app.database import glossary_resolver as resolver_module
from app.database.db import (
    add_book,
    add_chapter,
    get_connection,
    init_db,
    put_glossary_term,
    put_model_provider,
)
from app.mobile_api.services import glossary_service as glossary_module
from app.mobile_api.services import operational_metrics_service as operations_module
from app.mobile_api.services import qa_service as qa_module
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.operational_metrics_service import OperationalMetricsService
from app.mobile_api.services.qa_service import QAService
from app.mobile_api.config import mobile_settings
from app.observability import InMemoryMetrics, Observability, StructuredEventLogger
from scripts.prepare_glossary_phase6_fixture import prepare_fixture


def _metric_names(snapshot: dict, kind: str) -> set[str]:
    return {str(item["name"]) for item in snapshot["metrics"][kind]}


def test_glossary_runtime_observability_covers_required_categories_without_private_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    book_id = add_book(db_path, "Synthetic phase 6")
    raw_path = data_dir / "raw" / "phase6-private.txt"
    raw_path.parent.mkdir()
    private_body = "PRIVATE-CHAPTER-BODY-SENTINEL"
    raw_path.write_text(
        f"玄天圣典玄天圣典。{'界' * 80}{private_body}{'域' * 80}",
        encoding="utf-8",
    )
    chapter_id = add_chapter(db_path, book_id, 1, "PRIVATE-TITLE-SENTINEL", raw_text_path=raw_path)
    term_id = put_glossary_term(
        db_path,
        book_id,
        "玄天圣典",
        "PRIVATE-TARGET-SENTINEL",
        approved=0,
        review_status="NEEDS_REVIEW",
    )
    put_glossary_term(
        db_path,
        book_id,
        "冲突术语",
        "冲突译文",
        approved=0,
        review_status="CONFLICT",
    )
    put_model_provider(
        db_path,
        provider_id="phase6-fake",
        label="Phase 6 fake",
        base_url="http://fake.invalid/v1",
        model="fake-model",
        api_key_env="PHASE6_FAKE_API_KEY",
        enabled=1,
        timeout_seconds=1,
    )
    monkeypatch.setenv("PHASE6_FAKE_API_KEY", "PRIVATE-PROVIDER-SECRET-SENTINEL")

    logger_name = "tests.glossary.phase6"
    observability = Observability(
        metrics=InMemoryMetrics(max_series=128),
        events=StructuredEventLogger(logging.getLogger(logger_name)),
    )
    for module in (
        glossary_module,
        operations_module,
        qa_module,
        repository_module,
        resolver_module,
    ):
        monkeypatch.setattr(module, "default_observability", observability, raising=False)

    service = GlossaryService.from_db_path(db_path)
    with caplog.at_level(logging.INFO, logger=logger_name):
        queue = service.query_terms(
            book_id=book_id,
            review_status="NEEDS_REVIEW,CONFLICT",
            scope="book",
        )
        assert queue["total"] == 2
        assert service.approve_term(term_id)
        assert service.set_term_locked(term_id, True)
        resolved = resolver_module.resolve_effective_glossary(db_path, book_id)
        assert any(int(term["id"]) == term_id for term in resolved.dictionary_terms)

        service.update_extraction_settings(book_id, mode="hybrid", provider_id="phase6-fake")
        monkeypatch.setattr(
            glossary_module,
            "call_openai_compatible_chat",
            lambda **_kwargs: (_ for _ in ()).throw(requests.Timeout("private provider failure")),
        )
        extraction = service.extract_chapter_terms(book_id, chapter_id)
        assert extraction["warnings"] == [
            {"code": "provider_unavailable", "message": "Hybrid glossary extraction was skipped."}
        ]

        class ChapterReader:
            @staticmethod
            def get_chapter_source(_chapter_id: int) -> str:
                return "玄天圣典"

            @staticmethod
            def get_chapter_translation(_chapter_id: int) -> str:
                return "Bản dịch cố ý thiếu thuật ngữ khóa."

        reader = ChapterReader()
        reader.db_path = db_path
        report = QAService(reader).run_deterministic_qa(book_id, chapter_id)
        assert len(report["glossary_violations"]) == 1

    runtime = observability.snapshot()
    assert {
        "glossary_extractions_total",
        "glossary_provider_failures_total",
        "glossary_qa_violations_total",
        "glossary_queries_total",
        "glossary_state_transitions_total",
    }.issubset(_metric_names(runtime, "counters"))
    assert {"glossary_active_conflicts", "glossary_effective_terms"}.issubset(
        _metric_names(runtime, "gauges")
    )
    assert "glossary_query_latency_ms" in _metric_names(runtime, "latencies")
    for event in (
        "glossary_extraction",
        "glossary_qa",
        "glossary_query",
        "glossary_resolution",
        "glossary_state_transition",
    ):
        assert f'"event":"{event}"' in caplog.text

    snapshot = OperationalMetricsService(db_path, data_dir).snapshot(use_cache=False)
    assert snapshot["observability"] == runtime
    rendered_runtime = json.dumps({"logs": caplog.text, "runtime": runtime, "ops": snapshot})
    with get_connection(db_path) as conn:
        persisted = json.dumps(
            {
                "events": [dict(row) for row in conn.execute("SELECT * FROM operational_events")],
                "evidence": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT evidence_type, evidence_json FROM glossary_term_evidence"
                    )
                ],
                "history": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT action, before_json, after_json FROM glossary_history"
                    )
                ],
            }
        )
    for forbidden in (
        "PRIVATE-CHAPTER-BODY-SENTINEL",
        "PRIVATE-PROVIDER-SECRET-SENTINEL",
        "PRIVATE-TARGET-SENTINEL",
        "PRIVATE-TITLE-SENTINEL",
        str(raw_path),
    ):
        assert forbidden not in rendered_runtime
    for forbidden in (private_body, "PRIVATE-PROVIDER-SECRET-SENTINEL", str(raw_path)):
        assert forbidden not in persisted


def test_operational_snapshot_adds_shared_metrics_without_changing_existing_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    observability = Observability()
    observability.metrics.increment("glossary_queries_total", labels={"operation": "queue"})
    monkeypatch.setattr(operations_module, "default_observability", observability, raising=False)
    monkeypatch.setattr(operations_module.mobile_settings, "import_job_run_in_api", True)
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    snapshot = OperationalMetricsService(db_path, data_dir).snapshot(use_cache=False)

    assert {
        "alerts",
        "api",
        "artifacts",
        "auth_sessions",
        "backup",
        "container",
        "generated_at",
        "jobs",
        "observability",
        "queue",
        "release",
        "restore_drill",
        "storage",
        "tts",
        "worker",
    } == set(snapshot)
    assert snapshot["observability"]["metrics"]["counters"] == [
        {
            "labels": {"operation": "queue"},
            "name": "glossary_queries_total",
            "value": 1.0,
        }
    ]


def test_filtered_query_does_not_overwrite_active_conflict_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    book_id = add_book(db_path, "Conflict inventory")
    put_glossary_term(
        db_path,
        book_id,
        "冲突库存",
        "xung đột",
        approved=0,
        review_status="CONFLICT",
    )
    put_glossary_term(db_path, book_id, "已批准库存", "đã duyệt", approved=1)
    observability = Observability(metrics=InMemoryMetrics(max_series=32))
    monkeypatch.setattr(glossary_module, "default_observability", observability)

    service = GlossaryService.from_db_path(db_path)
    service.query_terms(book_id=book_id, review_status="CONFLICT", scope="book")
    approved = service.query_terms(
        book_id=book_id,
        q="已批准库存",
        review_status="APPROVED",
        scope="book",
    )

    assert approved["total"] == 1
    gauges = {
        item["name"]: item["value"]
        for item in observability.snapshot()["metrics"]["gauges"]
    }
    assert gauges["glossary_active_conflicts"] == 1.0


def test_bulk_rollback_emits_no_transition_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    init_db(db_path)
    book_id = add_book(db_path, "Forced rollback")
    first_id = put_glossary_term(
        db_path, book_id, "回滚一", "một", approved=0, review_status="NEEDS_REVIEW"
    )
    second_id = put_glossary_term(
        db_path, book_id, "回滚二", "hai", approved=0, review_status="NEEDS_REVIEW"
    )
    with get_connection(db_path) as conn:
        versions = {
            int(row["id"]): int(row["version"])
            for row in conn.execute(
                "SELECT id, version FROM glossary_terms WHERE id IN (?, ?)",
                (first_id, second_id),
            )
        }
        conn.execute(
            f"""
            CREATE TRIGGER phase6_force_transition_rollback
            BEFORE INSERT ON glossary_history
            WHEN NEW.term_id = {second_id}
            BEGIN
                SELECT RAISE(ABORT, 'forced_transition_rollback');
            END
            """
        )
        conn.commit()

    logger_name = "tests.glossary.phase6.rollback"
    observability = Observability(
        metrics=InMemoryMetrics(max_series=32),
        events=StructuredEventLogger(logging.getLogger(logger_name)),
    )
    monkeypatch.setattr(repository_module, "default_observability", observability)

    with caplog.at_level(logging.INFO, logger=logger_name):
        with pytest.raises(sqlite3.IntegrityError, match="forced_transition_rollback"):
            repository_module.GlossaryRepository(db_path).bulk(
                "approve",
                [
                    {"id": first_id, "expected_version": versions[first_id]},
                    {"id": second_id, "expected_version": versions[second_id]},
                ],
                actor="phase6-test",
            )

    with get_connection(db_path) as conn:
        states = [
            tuple(row)
            for row in conn.execute(
                "SELECT review_status, approved, locked FROM glossary_terms "
                "WHERE id IN (?, ?) ORDER BY id",
                (first_id, second_id),
            )
        ]
    assert states == [("NEEDS_REVIEW", 0, 0), ("NEEDS_REVIEW", 0, 0)]
    assert "glossary_state_transitions_total" not in _metric_names(
        observability.snapshot(), "counters"
    )
    assert '"event":"glossary_state_transition"' not in caplog.text


def test_extraction_observe_transition_uses_a_fixed_action_label() -> None:
    observability = Observability(metrics=InMemoryMetrics(max_series=8))

    observability.record_glossary_transition(
        action="observe",
        before_state="NEEDS_REVIEW",
        after_state="CONFLICT",
        term_id=7,
        book_id=3,
        version=2,
    )

    transition = next(
        item
        for item in observability.snapshot()["metrics"]["counters"]
        if item["name"] == "glossary_state_transitions_total"
    )
    assert transition["labels"] == {"operation": "observe", "state": "CONFLICT"}


@pytest.mark.asyncio
async def test_synthetic_ten_thousand_row_api_operator_journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import config as app_config
    from app.mobile_api import dependencies as dependencies_module
    from app.mobile_api.main import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fixture = prepare_fixture(data_dir)
    book_id = fixture["book_id"]
    chapter_id = fixture["chapter_id"]

    observability = Observability(metrics=InMemoryMetrics(max_series=128))
    for module in (
        glossary_module,
        operations_module,
        qa_module,
        repository_module,
        resolver_module,
    ):
        monkeypatch.setattr(module, "default_observability", observability)
    monkeypatch.setattr(app_config.settings, "data_dir", data_dir)
    monkeypatch.setattr(dependencies_module.settings, "data_dir", data_dir)
    monkeypatch.setattr(operations_module.mobile_settings, "import_job_run_in_api", True)
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={
                "username": mobile_settings.admin_username,
                "password": mobile_settings.admin_password,
            },
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        queue = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "review_status": "NEEDS_REVIEW,CONFLICT",
                "scope": "book",
            },
            headers=headers,
        )
        assert queue.status_code == 200
        assert queue.json()["total"] == 4

        searched = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "q": "synthetic-source-09999",
                "review_status": "APPROVED",
                "scope": "book",
            },
            headers=headers,
        )
        assert searched.status_code == 200
        assert [item["source_term"] for item in searched.json()["items"]] == [
            "synthetic-source-09999"
        ]

        final_page = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "page": 200,
                "per_page": 50,
                "review_status": "APPROVED",
                "scope": "book",
                "sort": "source_asc",
            },
            headers=headers,
        )
        assert final_page.status_code == 200
        assert final_page.json()["page"] == final_page.json()["pages"]
        assert final_page.json()["items"][-1]["source_term"] == "synthetic-source-09999"

        created = await client.post(
            "/api/glossary/terms",
            json={
                "book_id": book_id,
                "source_term": "phase6-created",
                "target_term": "Created",
                "approved": 0,
                "locked": 0,
                "review_status": "NEEDS_REVIEW",
            },
            headers=headers,
        )
        assert created.status_code == 201
        created_term = created.json()
        edited = await client.patch(
            f"/api/glossary/terms/{created_term['id']}",
            json={
                "approved": 1,
                "expected_version": created_term["version"],
                "locked": 0,
                "priority": 17,
                "target_term": "Edited",
            },
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["target_term"] == "Edited"
        assert edited.json()["review_status"] == "APPROVED"
        locked = await client.post(
            f"/api/glossary/terms/{created_term['id']}/lock", headers=headers
        )
        assert locked.status_code == 200

        pending_items = {item["id"]: item for item in queue.json()["items"]}
        bulk = await client.post(
            "/api/glossary/terms/bulk",
            json={
                "action": "approve",
                "terms": [
                    {"id": term_id, "expected_version": pending_items[term_id]["version"]}
                    for term_id in (1, 2)
                ],
            },
            headers=headers,
        )
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == 2

        conflicts = await client.get(
            "/api/glossary/conflicts",
            params={"book_id": book_id, "include_legacy": "false"},
            headers=headers,
        )
        assert conflicts.status_code == 200
        conflict = next(
            item
            for item in conflicts.json()["items"]
            if {member["id"] for member in item["members"]} == {3, 4}
        )
        preview_merge = await client.post(
            "/api/glossary/conflicts/merge/preview",
            json={"canonical_id": 3, "duplicate_ids": [4]},
            headers=headers,
        )
        assert preview_merge.status_code == 200
        applied_merge = await client.post(
            "/api/glossary/conflicts/merge/apply",
            json={
                "canonical_id": 3,
                "duplicate_ids": [4],
                "digest": preview_merge.json()["digest"],
            },
            headers=headers,
        )
        assert applied_merge.status_code == 200
        assert applied_merge.json()["merged"] == 1
        assert conflict["canonical_id"] == 3

        import_items = [
            {
                "book_id": book_id,
                "source_term": "phase6-imported",
                "target_term": "Imported",
                "approved": 0,
                "locked": 0,
                "review_status": "NEEDS_REVIEW",
            }
        ]
        preview_import = await client.post(
            "/api/glossary/import/preview",
            json={"items": import_items, "conflict_policy": "skip_conflicts"},
            headers=headers,
        )
        assert preview_import.status_code == 200
        applied_import = await client.post(
            "/api/glossary/import/apply",
            json={
                "items": import_items,
                "conflict_policy": "skip_conflicts",
                "digest": preview_import.json()["digest"],
            },
            headers=headers,
        )
        assert applied_import.status_code == 200
        assert applied_import.json()["added"] == 1

        exported = await client.get(
            "/api/glossary/export",
            params={"book_id": book_id, "format": "json", "scope": "book"},
            headers=headers,
        )
        assert exported.status_code == 200
        assert exported.json()["total"] >= 10_002

        archived = await client.delete(
            f"/api/glossary/terms/{created_term['id']}", headers=headers
        )
        assert archived.status_code == 200
        archived_page = await client.get(
            "/api/glossary",
            params={
                "book_id": book_id,
                "archived": "true",
                "q": "phase6-created",
                "scope": "book",
            },
            headers=headers,
        )
        assert archived_page.status_code == 200
        assert [item["id"] for item in archived_page.json()["items"]] == [created_term["id"]]
        restored = await client.post(
            f"/api/glossary/terms/{created_term['id']}/restore", headers=headers
        )
        assert restored.status_code == 200

        reextracted = await client.post(
            f"/api/books/{book_id}/chapters/{chapter_id}/glossary/re-extract",
            headers=headers,
        )
        assert reextracted.status_code == 200
        assert reextracted.json()["warnings"] == []

        metrics = await client.get("/api/ops/metrics", headers=headers)
        assert metrics.status_code == 200
        assert "observability" in metrics.json()

    counters = _metric_names(observability.snapshot(), "counters")
    assert {
        "glossary_extractions_total",
        "glossary_queries_total",
        "glossary_state_transitions_total",
    }.issubset(counters)
