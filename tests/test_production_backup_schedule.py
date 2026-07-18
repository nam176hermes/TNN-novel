from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_backup.sh"
SERVICE = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.service"
TIMER = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.timer"


def _validate_config(data_dir: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "BACKUP_DATA_DIR": str(data_dir),
        "BACKUP_LOCAL_DIR": str(data_dir.parent / "backups"),
        "BACKUP_IMAGE": "novel-pipeline-api:runtime-hardening-20260718-r1",
        "BACKUP_PASSPHRASE": "test-only-passphrase",
        "OFFSITE_SFTP_HOST": "backup.example.test",
        "OFFSITE_SFTP_DIR": "/novel-tnn",
        "BACKUP_KEEP_LOCAL": "14",
        "BACKUP_KEEP_OFFSITE": "35",
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


def test_backup_runner_rejects_missing_offsite_configuration_before_running_docker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, OFFSITE_SFTP_HOST="")

    assert result.returncode == 2
    assert "OFFSITE_SFTP_HOST" in result.stderr


def test_backup_runner_accepts_complete_safe_configuration(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir)

    assert result.returncode == 0, result.stderr
    assert "backup configuration validated" in result.stdout


def test_user_timer_keeps_backup_owner_and_retention_contract_in_external_config() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "EnvironmentFile=%h/.config/novel-tnn/backup.env" in service
    assert "ExecStart=%h/Novel-TNN/scripts/production_backup.sh" in service
    assert "User=" not in service
    assert "OnCalendar=*-*-* 03:15:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_backup_runner_creates_encrypted_archive_and_remote_checksum_contract() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert "create_encrypted_backup" in content
    assert "sha256sum" in content
    assert "OFFSITE_SFTP_HOST" in content
    assert "OFFSITE_SFTP_DIR" in content
    assert "BACKUP_KEEP_LOCAL" in content
    assert "BACKUP_KEEP_OFFSITE" in content
    assert "StrictHostKeyChecking=yes" in content


def test_backup_runner_creates_and_verifies_an_encrypted_offsite_copy(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "chapter.txt").write_text("backup fixture", encoding="utf-8")
    local_dir = tmp_path / "local"
    remote_dir = tmp_path / "remote"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"

    (fake_bin / "docker").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' \"$*\" >> \"$MOCK_DOCKER_LOG\"
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from scripts.ops import create_encrypted_backup

archive = create_encrypted_backup(
    data_dir=Path(os.environ[\"BACKUP_DATA_DIR\"]),
    out_dir=Path(os.environ[\"BACKUP_LOCAL_DIR\"]),
    passphrase=os.environ[\"BACKUP_PASSPHRASE\"],
    keep=int(os.environ[\"BACKUP_KEEP_LOCAL\"]),
    record_event=False,
)
print(archive.name)
PY
""",
        encoding="utf-8",
    )
    (fake_bin / "sftp").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
while (($#)); do
  case \"$1\" in
    -b) shift 2 ;;
    *) shift ;;
  esac
done
while read -r operation first second; do
  case \"$operation\" in
    put)
      target=\"$MOCK_REMOTE_ROOT$second\"
      mkdir -p \"$(dirname \"$target\")\"
      cp \"$first\" \"$target\"
      ;;
    get)
      cp \"$MOCK_REMOTE_ROOT$first\" \"$second\"
      ;;
    ls)
      for item in $MOCK_REMOTE_ROOT$second; do
        [[ -e \"$item\" ]] && printf '%s\\n' \"${item#\"$MOCK_REMOTE_ROOT\"}\"
      done
      ;;
    rm)
      rm -f \"$MOCK_REMOTE_ROOT$first\"
      ;;
  esac
done
""",
        encoding="utf-8",
    )
    for executable in (fake_bin / "docker", fake_bin / "sftp"):
        executable.chmod(0o755)

    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MOCK_DOCKER_LOG": str(docker_log),
            "MOCK_REMOTE_ROOT": str(remote_dir),
            "BACKUP_DATA_DIR": str(data_dir),
            "BACKUP_LOCAL_DIR": str(local_dir),
            "BACKUP_IMAGE": "novel-pipeline-api:runtime-hardening-20260718-r1",
            "BACKUP_PASSPHRASE": "test-only-passphrase",
            "OFFSITE_SFTP_HOST": "backup.example.test",
            "OFFSITE_SFTP_DIR": "/novel-tnn",
            "BACKUP_KEEP_LOCAL": "14",
            "BACKUP_KEEP_OFFSITE": "35",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    archive = next(local_dir.glob("novel-pipeline-backup-*.tar.gz.enc"))
    assert not list(local_dir.glob("novel-pipeline-backup-*.tar.gz"))
    assert (remote_dir / "novel-tnn" / archive.name).is_file()
    assert (remote_dir / "novel-tnn" / f"{archive.name}.manifest.json").is_file()
    assert (remote_dir / "novel-tnn" / f"{archive.name}.sha256").is_file()
    assert "--network none" in docker_log.read_text(encoding="utf-8")
    assert "--user 0:0" in docker_log.read_text(encoding="utf-8")
