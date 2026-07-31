#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import ops


def _manifest(index: int) -> dict[str, Any]:
    return {
        "backup_format_version": 2,
        "created_at": f"2026-07-12T10:{index:02d}:00",
        "encrypted": False,
        "secrets_included": False,
        "included_modules": ["database", "uploads"],
        "excluded_modules": ["secrets"],
        "file_count": index + 1,
        "total_size_bytes": (index + 1) * 1024,
        "app_version": "0.1.0",
    }


def _ready_archive(directory: Path, index: int) -> Path:
    archive = directory / f"novel-pipeline-backup-20260712-{100000 + index:06d}.tar.gz"
    archive.write_bytes(b"fixture-artifact")
    ops.write_backup_sidecar_atomic(archive, ops.build_backup_sidecar(_manifest(index), archive))
    return archive


def _prepare_scenarios(root: Path) -> dict[str, Path]:
    scenarios = {name: root / name for name in (
        "zero", "two_ready", "ten_ready", "missing", "malformed", "large_missing"
    )}
    for directory in scenarios.values():
        directory.mkdir(parents=True)
    for index in range(2):
        _ready_archive(scenarios["two_ready"], index)
    for index in range(10):
        _ready_archive(scenarios["ten_ready"], index)

    missing = scenarios["missing"] / "novel-pipeline-backup-20260712-090000.tar.gz"
    missing.write_bytes(b"metadata-is-missing")

    malformed = scenarios["malformed"] / "novel-pipeline-backup-20260712-080000.tar.gz"
    malformed.write_bytes(b"artifact")
    ops.backup_sidecar_path(malformed).write_text("{", encoding="utf-8")

    large = scenarios["large_missing"] / "novel-pipeline-backup-20260712-070000.tar.gz"
    with large.open("wb") as handle:
        handle.seek((512 * 1024 * 1024) - 1)
        handle.write(b"\0")
    return scenarios


def _measure_scenario(name: str, directory: Path, iterations: int) -> dict[str, Any]:
    enumeration_started = time.perf_counter()
    entries = list(directory.iterdir())
    directory_scan_ms = (time.perf_counter() - enumeration_started) * 1000
    sidecars = [
        path for path in entries
        if path.name.endswith(ops.BACKUP_MANIFEST_SUFFIX) and path.is_file() and not path.is_symlink()
    ]
    bytes_read = sum(path.stat().st_size for path in sidecars)
    sidecar_started = time.perf_counter()
    for sidecar in sidecars:
        archive = directory / sidecar.name.removesuffix(ops.BACKUP_MANIFEST_SUFFIX)
        try:
            ops.read_backup_sidecar(archive)
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    sidecar_read_ms = (time.perf_counter() - sidecar_started) * 1000

    archive_open_count = 0
    original_open = ops.tarfile.open

    def reject_archive_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal archive_open_count
        archive_open_count += 1
        raise AssertionError("normal backup listing opened an archive")

    try:
        ops.tarfile.open = reject_archive_open
        ops.list_backups(directory)
        timings: list[float] = []
        response: list[dict[str, Any]] = []
        for _ in range(max(1, iterations)):
            started = time.perf_counter()
            response = ops.list_backups(directory)
            timings.append((time.perf_counter() - started) * 1000)
    finally:
        ops.tarfile.open = original_open

    return {
        "scenario": name,
        "entry_count": len(response),
        "directory_scan_ms": round(directory_scan_ms, 3),
        "sidecar_read_ms": round(sidecar_read_ms, 3),
        "service_total_ms": round(statistics.median(timings), 3),
        "archive_open_count": archive_open_count,
        "bytes_read": bytes_read,
        "response_bytes": len(json.dumps(response, ensure_ascii=False).encode("utf-8")),
    }


def run_benchmark(work_dir: Path, iterations: int = 5) -> dict[str, Any]:
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p1a-listing-", dir=work_dir) as temporary:
        scenarios = _prepare_scenarios(Path(temporary))
        rows = [
            _measure_scenario(name, directory, iterations)
            for name, directory in scenarios.items()
        ]
    return {
        "benchmark": "backup-metadata-only-listing",
        "iterations": max(1, iterations),
        "scenarios": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark metadata-only backup listing")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_benchmark(args.work_dir, iterations=args.iterations)
    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 1 if any(row["archive_open_count"] for row in result["scenarios"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
