from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_restore_drill.sh"


def _validate_config(backup_dir: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "BACKUP_LOCAL_DIR": str(backup_dir),
        "BACKUP_DRILL_ROOT": str(backup_dir.parent / "drills"),
        "BACKUP_IMAGE": "novel-pipeline-api:runtime-hardening-20260718-r1",
        "BACKUP_PASSPHRASE": "test-only-passphrase",
        "PRODUCTION_ENV": "/tmp/novel-tnn-production.env",
        "RESTORE_ARTIFACT_SOURCE_ROOT": "/home/thenam176/Novel-TNN",
        "RESTORE_STATUS_FILE": str(backup_dir.parent / "restore-drill.status.json"),
        **overrides,
    }
    return subprocess.run(
        ["bash", str(RUNNER), "--validate-config"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_restore_runner_rejects_missing_passphrase_before_creating_a_drill(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, BACKUP_PASSPHRASE="")

    assert result.returncode == 2
    assert "BACKUP_PASSPHRASE" in result.stderr
    assert not (tmp_path / "drills").exists()


def test_restore_runner_declares_isolated_db_artifact_and_api_validation() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert "restore_drill" in content
    assert "integrity_check" in content
    assert "foreign_key_check" in content
    assert "mode=ro&immutable=1" in content
    assert "require_artifact_file" in content
    assert "docker run --rm --network none --user 0:0 -i" in content
    assert '--env "ARTIFACT_LEGACY_ROOT=${RESTORE_ARTIFACT_SOURCE_ROOT}"' in content
    assert "/api/ready" in content
    assert "smoke_reader_authenticated.py" in content
    assert "record_restore_drill_status.py --output \"$RESTORE_STATUS_FILE\"" in content
    assert "http://127.0.0.1:7860/api/health >/dev/null 2>&1" in content
    assert "trap 'docker rm -f \"${container_name:-}\"" in content
    assert "2>&1 || true' EXIT" in content
    assert "rm -rf" not in content


def test_restore_status_publisher_writes_only_bounded_operational_metadata(tmp_path: Path) -> None:
    from scripts.record_restore_drill_status import record_success

    status_path = tmp_path / "runtime" / "restore-drill.status.json"
    record_success(status_path)

    payload = status_path.read_text(encoding="utf-8")
    assert '"status": "passed"' in payload
    assert '"completed_at":' in payload
    assert "archive" not in payload
    assert "path" not in payload
    assert status_path.stat().st_mode & 0o777 == 0o600
