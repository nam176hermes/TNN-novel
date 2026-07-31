#!/usr/bin/env python3
"""Benchmark reviewed text imports against isolated synthetic databases."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import app.database.db as db_mod
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService


def _pipeline(db_path: Path, data_dir: Path) -> PipelineService:
    service = object.__new__(PipelineService)
    service.db_path = db_path
    service.data_dir = data_dir
    return service


def _chapters(count: int, text_bytes: int = 0) -> list[dict]:
    if text_bytes:
        text = "中" * max(1, text_bytes // len("中".encode("utf-8")))
        return [{"chapter_number": 1, "chapter_title": "Large synthetic chapter", "text": text}]
    return [
        {
            "chapter_number": number,
            "chapter_title": f"Synthetic chapter {number}",
            "text": f"第{number}章\n\n" + ("少年走入山中。" * 20),
        }
        for number in range(1, count + 1)
    ]


def _timed_method(service: PipelineService, name: str, timings: dict[str, float]) -> None:
    original = getattr(service, name)

    def measured(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            timings[name] = timings.get(name, 0.0) + (time.perf_counter() - started) * 1000

    setattr(service, name, measured)


def _run_case(*, count: int, text_bytes: int, include_followups: bool, work_root: Path | None) -> dict:
    with tempfile.TemporaryDirectory(
        prefix="novel-tnn-p2b-",
        dir=str(work_root) if work_root else None,
    ) as temp_name:
        root = Path(temp_name)
        db_path = root / "pipeline.db"
        db_mod.init_db(db_path)
        service = _pipeline(db_path, root)
        timings: dict[str, float] = {}
        for name in (
            "_prepare_reviewed_import_items",
            "_classify_reviewed_import_items",
            "_stage_reviewed_import_files",
            "_finalize_reviewed_import_files",
        ):
            _timed_method(service, name, timings)

        original_connect = db_mod.sqlite3.connect
        counters = {"connections": 0, "commit_calls": 0, "sql_statements": 0, "duplicate_queries": 0}
        transaction = {"started": 0.0, "elapsed_ms": 0.0}

        class CountingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                normalized = str(sql).strip().upper()
                if normalized.startswith("BEGIN"):
                    transaction["started"] = time.perf_counter()
                return super().execute(sql, parameters)

            def commit(self) -> None:
                counters["commit_calls"] += 1
                super().commit()
                if transaction["started"]:
                    transaction["elapsed_ms"] += (time.perf_counter() - transaction["started"]) * 1000
                    transaction["started"] = 0.0

        def counted_connect(*args, **kwargs):
            counters["connections"] += 1
            kwargs["factory"] = CountingConnection
            conn = original_connect(*args, **kwargs)

            def trace(statement: str) -> None:
                counters["sql_statements"] += 1
                normalized = statement.strip().upper()
                if normalized.startswith("SELECT") and "FROM CHAPTERS" in normalized:
                    counters["duplicate_queries"] += 1

            conn.set_trace_callback(trace)
            return conn

        chapters = _chapters(count, text_bytes)
        followup_patches = []
        if not include_followups:
            followup_patches = [
                patch.object(GlossaryService, "extract_chapter_terms", return_value={"candidates": []}),
                patch.object(QAService, "run_deterministic_qa", return_value={"status": "PASS"}),
            ]

        started = time.perf_counter()
        with patch.object(db_mod.sqlite3, "connect", counted_connect):
            for active_patch in followup_patches:
                active_patch.start()
            try:
                result = service.import_reviewed_text_plan(
                    title=f"Synthetic import {count}-{text_bytes}",
                    chapters=chapters,
                    content_kind="raw",
                    duplicate_strategy="error",
                )
            finally:
                for active_patch in reversed(followup_patches):
                    active_patch.stop()
        total_ms = (time.perf_counter() - started) * 1000
        outside_transaction_ms = (
            timings.get("_prepare_reviewed_import_items", 0.0)
            + timings.get("_stage_reviewed_import_files", 0.0)
        )
        return {
            "chapters": len(chapters),
            "text_bytes": sum(len(str(item["text"]).encode("utf-8")) for item in chapters),
            "service_total_ms": round(total_ms, 3),
            "validation_ms": round(timings.get("_prepare_reviewed_import_items", 0.0), 3),
            "duplicate_detection_ms": round(timings.get("_classify_reviewed_import_items", 0.0), 3),
            "file_staging_ms": round(timings.get("_stage_reviewed_import_files", 0.0), 3),
            "file_finalization_ms": round(timings.get("_finalize_reviewed_import_files", 0.0), 3),
            "database_transaction_ms": round(transaction["elapsed_ms"], 3),
            "unattributed_and_followup_ms": round(
                max(0.0, total_ms - outside_transaction_ms - transaction["elapsed_ms"]),
                3,
            ),
            **counters,
            "imported_chapters": result["imported_chapters"],
            "warnings": len(result["warnings"]),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", default="1,10,120,500", help="Comma-separated chapter counts")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--large-bytes", type=int, default=4_900_000)
    parser.add_argument("--include-followups", action="store_true")
    parser.add_argument("--work-root", type=Path, help="Filesystem root for isolated temporary fixtures")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.work_root:
        args.work_root.mkdir(parents=True, exist_ok=True)

    cases = [(int(value), 0) for value in args.counts.split(",") if value.strip()]
    if args.large_bytes > 0:
        cases.append((1, args.large_bytes))
    samples = []
    for count, text_bytes in cases:
        runs = [
            _run_case(
                count=count,
                text_bytes=text_bytes,
                include_followups=args.include_followups,
                work_root=args.work_root,
            )
            for _ in range(max(1, args.runs))
        ]
        samples.append(
            {
                "case": {"chapters": count, "requested_text_bytes": text_bytes},
                "median_service_total_ms": round(statistics.median(run["service_total_ms"] for run in runs), 3),
                "runs": runs,
            }
        )

    payload = {
        "methodology": {
            "isolated_temporary_database": True,
            "synthetic_content": True,
            "followups_included": args.include_followups,
            "runs_per_case": max(1, args.runs),
            "work_root": str(args.work_root.resolve()) if args.work_root else "system temporary directory",
        },
        "results": samples,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
