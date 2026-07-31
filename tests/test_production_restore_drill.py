from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_restore_drill.sh"
PINNED_IMAGE = "novel-pipeline-api@sha256:" + "a" * 64


def _validate_config(
    backup_dir: Path,
    *,
    prepare_receipt: bool = True,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    production_root = backup_dir.parent / "production"
    (production_root / "data").mkdir(parents=True)
    if prepare_receipt:
        (production_root / "data" / "logs" / "runtime").mkdir(parents=True)
    environment = {
        **os.environ,
        "BACKUP_LOCAL_DIR": str(backup_dir),
        "BACKUP_DRILL_ROOT": str(backup_dir.parent / "drills"),
        "BACKUP_IMAGE": PINNED_IMAGE,
        "RECOVERY_PRODUCER_VERSION": "runtime-hardening-20260718-r1",
        "BACKUP_PASSPHRASE": "test-only-passphrase",
        "PRODUCTION_ENV": "/tmp/novel-tnn-production.env",
        "RESTORE_ARTIFACT_SOURCE_ROOT": str(production_root),
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


def test_restore_static_validation_defers_private_receipt_authority_to_publisher(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, prepare_receipt=False)

    assert result.returncode == 0, result.stderr
    content = RUNNER.read_text(encoding="utf-8")
    assert '[[ -d "$RECOVERY_RECEIPT_DIR"' not in content
    assert 'realpath -e "$RECOVERY_RECEIPT_DIR"' not in content
    assert "verify_publisher_authority" in content


def test_restore_checksum_metadata_must_name_the_selected_archive(tmp_path: Path) -> None:
    archive_name = "novel-pipeline-backup-20260724-120000.tar.gz.enc"
    (tmp_path / f"{archive_name}.sha256").write_text(
        f"{'a' * 64}  another-archive.tar.gz.enc\n",
        encoding="ascii",
    )
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; read_verified_checksum_hash "$2"', "_", str(RUNNER), archive_name],
        cwd=ROOT,
        env={**os.environ, "BACKUP_LOCAL_DIR": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "exactly the selected archive" in result.stderr


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
    assert "-m scripts.record_restore_drill_status" in content
    assert "restore-drill.receipt.json" in content
    assert content.index('validate_restored_api "$restored_dir"') < content.rindex('publish_recovery_receipt "sha256:')
    assert "http://127.0.0.1:7860/api/health >/dev/null 2>&1" in content
    assert "trap 'docker rm -f \"${container_name:-}\"" in content
    assert "2>&1 || true' EXIT" in content
    assert "rm -rf" not in content


def test_restore_receipt_publisher_has_fixed_isolated_container_contract() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    publisher = content[content.index("publish_recovery_receipt()") : content.index("validate_restored_api()")]
    assert "docker run --rm --network none --user 10001:10001" in publisher
    assert '--mount "type=bind,src=${RECOVERY_RECEIPT_DIR},dst=/receipts"' in publisher
    assert "--output /receipts/restore-drill.receipt.json" in publisher
    assert "--env " not in publisher
    assert "--env-file" not in publisher
    for forbidden in (
        "BACKUP_PASSPHRASE",
        "R2_",
        "BACKUP_LOCAL_DIR",
        "archive_name",
        "report_path",
        "PRODUCTION_ENV",
        "RESTORE_STATUS_FILE",
    ):
        assert forbidden not in publisher


def test_restore_readiness_exhaustion_fails_before_receipt_publication(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  run) printf '%s\n' fake-container ;;
  exec) exit 1 ;;
  rm) exit 0 ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in (fake_bin / "docker", fake_bin / "sleep"):
        executable.chmod(0o755)

    command = f'''source "{RUNNER}"
BACKUP_IMAGE=test-image
PRODUCTION_ENV=/tmp/test-production.env
RESTORE_ARTIFACT_SOURCE_ROOT=/tmp/test-root
validate_restored_api /tmp/restored
'''
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "restored API did not become healthy and ready" in result.stderr
    content = RUNNER.read_text(encoding="utf-8")
    assert content.index('validate_restored_api "$restored_dir"') < content.rindex('publish_recovery_receipt "sha256:')


def test_restore_status_publisher_writes_only_bounded_operational_metadata(tmp_path: Path) -> None:
    from scripts.record_restore_drill_status import record_success

    status_path = tmp_path / "runtime" / "restore-drill.status.json"
    record_success(
        status_path,
        archive_hash_id="sha256:" + "a" * 64,
        validation_counts={"checksum_verified": 1},
        producer_version="release-a",
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert set(payload) == {"status", "completed_at", "archive_hash_id", "validation_counts", "producer_version"}
    assert payload["status"] == "passed"
    serialized = json.dumps(payload)
    assert str(tmp_path) not in serialized
    assert "passphrase" not in serialized
    assert "exception" not in serialized
    assert status_path.stat().st_mode & 0o777 == 0o600


def test_restore_status_publisher_requires_real_receipt_metadata(tmp_path: Path) -> None:
    import pytest

    from scripts.record_restore_drill_status import record_success

    with pytest.raises(TypeError):
        record_success(tmp_path / "receipt.json")
