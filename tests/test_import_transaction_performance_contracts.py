from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

import app.database.db as db_mod
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService
from scripts.benchmark_import_transaction import _run_case


def _pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    service = object.__new__(PipelineService)
    service.db_path = db_path
    service.data_dir = data_dir
    return service


def _chapters(count: int) -> list[dict]:
    return [
        {
            "chapter_number": number,
            "chapter_title": f"Chapter {number}",
            "text": f"第{number}章 测试章节\n\n少年走入山中。",
        }
        for number in range(1, count + 1)
    ]


def _all_import_files(data_dir: Path) -> list[Path]:
    return [
        path
        for directory in (data_dir / "raw", data_dir / "translated", data_dir / ".import-staging")
        if directory.exists()
        for path in directory.rglob("*")
        if path.is_file()
    ]


def test_import_benchmark_measures_the_extracted_commit_stages(tmp_path: Path) -> None:
    result = _run_case(count=3, text_bytes=0, include_followups=False, work_root=tmp_path)

    assert result["imported_chapters"] == 3
    assert result["connections"] == 1
    assert result["commit_calls"] == 2
    for phase in ("validation_ms", "duplicate_detection_ms", "file_staging_ms", "file_finalization_ms"):
        assert result[phase] > 0, phase


def test_reviewed_import_uses_one_connection_two_transactions_and_bounded_duplicate_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    original_connect = db_mod.sqlite3.connect
    counters = {"connections": 0, "commit_calls": 0}
    statements: list[str] = []

    class CountingConnection(sqlite3.Connection):
        def commit(self) -> None:
            counters["commit_calls"] += 1
            super().commit()

    def counted_connect(*args, **kwargs):
        counters["connections"] += 1
        kwargs["factory"] = CountingConnection
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(lambda statement: statements.append(statement.strip()))
        return conn

    monkeypatch.setattr(db_mod.sqlite3, "connect", counted_connect)
    monkeypatch.setattr(GlossaryService, "extract_chapter_terms", lambda *args, **kwargs: {"candidates": []})
    monkeypatch.setattr(QAService, "run_deterministic_qa", lambda *args, **kwargs: {"status": "PASS"})

    result = service.import_reviewed_text_plan(
        title="Transactional Import",
        chapters=_chapters(120),
        content_kind="raw",
        duplicate_strategy="error",
    )

    duplicate_queries = [
        statement
        for statement in statements
        if statement.upper().startswith("SELECT")
        and "FROM chapters" in statement
        and "chapter_number" in statement
    ]
    assert result["imported_chapters"] == 120
    assert len(result["chapter_ids"]) == 120
    assert counters == {"connections": 1, "commit_calls": 2}
    assert len([statement for statement in statements if statement.upper().startswith("BEGIN")]) == 2
    assert len([statement for statement in statements if statement.upper().startswith("COMMIT")]) == 2
    assert len(duplicate_queries) <= 2


def test_reviewed_import_validates_the_entire_plan_before_mutation(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)

    with pytest.raises(ValueError, match="Chapter 2 text is empty"):
        service.import_reviewed_text_plan(
            title="Invalid Batch",
            chapters=[
                {"chapter_number": 1, "chapter_title": "Valid", "text": "第一章\n\n有效内容。"},
                {"chapter_number": 2, "chapter_title": "Invalid", "text": "   "},
            ],
            content_kind="raw",
            duplicate_strategy="error",
        )

    assert db_mod.get_book_by_title(db_path, "Invalid Batch") is None
    assert db_mod.list_chapters(db_path) == []
    assert _all_import_files(tmp_path) == []


def test_reviewed_import_rolls_back_database_and_files_on_constraint_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_second_import_chapter
            BEFORE INSERT ON chapters
            WHEN NEW.chapter_number = 2
            BEGIN
                SELECT RAISE(ABORT, 'synthetic import failure');
            END
            """
        )
        conn.commit()
    service = _pipeline(db_path, tmp_path)

    with pytest.raises(sqlite3.IntegrityError, match="synthetic import failure"):
        service.import_reviewed_text_plan(
            title="Rollback Batch",
            chapters=_chapters(3),
            content_kind="raw",
            duplicate_strategy="error",
        )

    assert db_mod.get_book_by_title(db_path, "Rollback Batch") is None
    assert db_mod.list_chapters(db_path) == []
    assert _all_import_files(tmp_path) == []


def test_reviewed_import_revalidates_duplicates_and_preserves_existing_content(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    first = service.import_reviewed_text_plan(
        title="Existing Batch",
        chapters=_chapters(2),
        content_kind="raw",
        duplicate_strategy="error",
    )
    original = db_mod.get_chapter(db_path, first["book_id"], 1)
    assert original is not None
    original_path = Path(original["raw_text_path"])
    original_text = original_path.read_text(encoding="utf-8")

    result = service.import_reviewed_text_plan(
        title="Existing Batch",
        target_book_id=first["book_id"],
        chapters=[
            {"chapter_number": 1, "chapter_title": "Changed", "text": "不得覆盖。"},
            {"chapter_number": 3, "chapter_title": "New", "text": "第三章 新内容。"},
        ],
        content_kind="raw",
        duplicate_strategy="skip",
    )

    preserved = db_mod.get_chapter(db_path, first["book_id"], 1)
    assert preserved is not None
    assert preserved["raw_text_path"] == str(original_path)
    assert original_path.read_text(encoding="utf-8") == original_text
    assert result["skipped_chapters"] == 1
    assert result["imported_chapters"] == 1


def test_post_commit_followup_failure_returns_warning_without_rolling_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    monkeypatch.setattr(
        GlossaryService,
        "extract_chapter_terms",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic glossary failure")),
    )

    result = service.import_reviewed_text_plan(
        title="Follow-up Warning",
        chapters=_chapters(3),
        content_kind="raw",
        duplicate_strategy="error",
    )

    assert result["imported_chapters"] == 3
    assert len(db_mod.list_chapters(db_path, result["book_id"])) == 3
    assert len(result["warnings"]) == 3
    assert all(warning["type"] == "post_import_qa_warning" for warning in result["warnings"])


def test_reviewed_import_rejects_stale_overwrite_after_server_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    initial = service.import_reviewed_text_plan(
        title="Stale Target",
        chapters=_chapters(1),
        content_kind="raw",
        duplicate_strategy="error",
    )
    original_stage = service._stage_reviewed_import_files

    def stage_then_change_target(**kwargs):
        staged = original_stage(**kwargs)
        with db_mod.get_connection(db_path) as conn:
            conn.execute(
                "UPDATE chapters SET title = ? WHERE book_id = ? AND chapter_number = 1",
                ("Concurrent manual edit", initial["book_id"]),
            )
            conn.commit()
        return staged

    monkeypatch.setattr(service, "_stage_reviewed_import_files", stage_then_change_target)

    with pytest.raises(ValueError, match="changed after review"):
        service.import_reviewed_text_plan(
            title="Stale Target",
            target_book_id=initial["book_id"],
            chapters=[{"chapter_number": 1, "chapter_title": "Replacement", "text": "替换内容。"}],
            content_kind="raw",
            duplicate_strategy="overwrite",
        )

    current = db_mod.get_chapter(db_path, initial["book_id"], 1)
    assert current is not None
    assert current["title"] == "Concurrent manual edit"
    assert _all_import_files(tmp_path) == [Path(current["raw_text_path"])]


def test_reviewed_import_cleans_finalized_files_when_file_move_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    original_replace = Path.replace
    calls = 0

    def fail_second_replace(path: Path, target: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic finalization failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)

    with pytest.raises(OSError, match="synthetic finalization failure"):
        service.import_reviewed_text_plan(
            title="File Rollback",
            chapters=_chapters(2),
            content_kind="raw",
            duplicate_strategy="error",
        )

    assert db_mod.get_book_by_title(db_path, "File Rollback") is None
    assert db_mod.list_chapters(db_path) == []
    assert _all_import_files(tmp_path) == []


def test_post_commit_warning_does_not_expose_internal_error_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)
    monkeypatch.setattr(
        GlossaryService,
        "extract_chapter_terms",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed at /private/operator/books/a.txt")),
    )

    result = service.import_reviewed_text_plan(
        title="Safe Warning",
        chapters=_chapters(1),
        content_kind="raw",
        duplicate_strategy="error",
    )

    warning = result["warnings"][0]
    assert warning["type"] == "post_import_qa_warning"
    assert "/private/" not in str(warning)
    assert "operator" not in str(warning)


def test_reviewed_import_preserves_in_batch_overwrite_semantics(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    db_mod.init_db(db_path)
    service = _pipeline(db_path, tmp_path)

    result = service.import_reviewed_text_plan(
        title="Repeated Chapter",
        chapters=[
            {"chapter_number": 1, "chapter_title": "First", "text": "第一版内容。"},
            {"chapter_number": 1, "chapter_title": "Second", "text": "第二版内容。"},
        ],
        content_kind="raw",
        duplicate_strategy="overwrite",
    )

    chapters = db_mod.list_chapters(db_path, result["book_id"])
    assert result["imported_chapters"] == 1
    assert result["overwritten_chapters"] == 1
    assert len(chapters) == 1
    assert result["chapter_ids"] == [chapters[0]["id"], chapters[0]["id"]]
    assert chapters[0]["title"] == "Second"
    assert Path(chapters[0]["raw_text_path"]).read_text(encoding="utf-8") == "第二版内容。"
