from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from scripts import benchmark_backup_listing


def test_benchmark_opens_zero_archives(tmp_path: Path) -> None:
    result = benchmark_backup_listing.run_benchmark(tmp_path, iterations=2)

    scenarios = {row["scenario"]: row for row in result["scenarios"]}
    assert {
        "zero",
        "two_ready",
        "ten_ready",
        "missing",
        "malformed",
        "large_missing",
    } <= scenarios.keys()
    assert all(row["archive_open_count"] == 0 for row in scenarios.values())
    assert scenarios["large_missing"]["entry_count"] == 1
    assert scenarios["large_missing"]["bytes_read"] == 0
    assert scenarios["ten_ready"]["response_bytes"] > scenarios["two_ready"]["response_bytes"]


def test_benchmark_cli_runs_from_repository_root(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_backup_listing.py",
            "--work-dir",
            str(tmp_path / "work"),
            "--iterations",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert all(row["archive_open_count"] == 0 for row in payload["scenarios"])
