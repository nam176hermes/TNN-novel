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
        "R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
        "R2_BUCKET": "novel-tnn-backups",
        "R2_PREFIX": "novel-tnn-production",
        "R2_ACCESS_KEY_ID": "test-access-key-id",
        "R2_SECRET_ACCESS_KEY": "test-secret-access-key",
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


def test_backup_runner_rejects_missing_r2_configuration_before_running_docker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, R2_ACCESS_KEY_ID="")

    assert result.returncode == 2
    assert "R2_ACCESS_KEY_ID" in result.stderr


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


def test_backup_runner_creates_encrypted_archive_and_r2_checksum_contract() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert "create_encrypted_backup" in content
    assert "sha256sum" in content
    assert "R2_ACCOUNT_ID" in content
    assert "R2_BUCKET" in content
    assert "R2_PREFIX" in content
    assert "R2_ACCESS_KEY_ID" in content
    assert "R2_SECRET_ACCESS_KEY" in content
    assert "BACKUP_KEEP_LOCAL" in content
    assert "BACKUP_KEEP_OFFSITE" in content
    assert "--aws-sigv4" in content
    assert "https://%s.r2.cloudflarestorage.com" in content
    assert "CompleteMultipartUpload" in content
    assert "R2_MULTIPART_PART_BYTES" in content
    assert "--upload-existing" in content
    assert "OFFSITE_SFTP" not in content


def test_backup_runner_creates_and_verifies_an_encrypted_r2_copy(tmp_path: Path) -> None:
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
printf '%s\\n' "$*" >> "$MOCK_DOCKER_LOG"
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from scripts.ops import create_encrypted_backup

archive = create_encrypted_backup(
    data_dir=Path(os.environ["BACKUP_DATA_DIR"]),
    out_dir=Path(os.environ["BACKUP_LOCAL_DIR"]),
    passphrase=os.environ["BACKUP_PASSPHRASE"],
    keep=int(os.environ["BACKUP_KEEP_LOCAL"]),
    record_event=False,
)
print(archive.name)
PY
""",
        encoding="utf-8",
    )
    (fake_bin / "curl").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
  printf '%s\\n' '  --aws-sigv4 <provider>'
  exit 0
fi
method=GET
upload_file=
output_file=
data_file=
header_file=
url=
while (($#)); do
  case "$1" in
    --request) method="$2"; shift 2 ;;
    --upload-file) upload_file="$2"; shift 2 ;;
    --output) output_file="$2"; shift 2 ;;
    --data-binary) data_file="${2#@}"; shift 2 ;;
    --dump-header) header_file="$2"; shift 2 ;;
    --config|--aws-sigv4|--retry|--connect-timeout) shift 2 ;;
    --fail|--silent|--show-error|--retry-all-errors|--get|all) shift ;;
    http://*|https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
[[ -n "$url" ]] || exit 2
path="${url#*r2.cloudflarestorage.com/novel-tnn-backups/}"
path="${path%%\\?*}"
target="$MOCK_REMOTE_ROOT/$path"
case "$method" in
  PUT)
    mkdir -p "$(dirname "$target")"
    if [[ "$url" == *"?partNumber="* ]]; then
      part_number="${url#*partNumber=}"
      part_number="${part_number%%&*}"
      cp "$upload_file" "${target}.part-${part_number}"
      printf 'ETag: "%08x"\\r\\n' "$part_number" > "$header_file"
    else
      cp "$upload_file" "$target"
    fi
    ;;
  GET)
    if [[ "$url" == *"?list-type=2"* ]]; then
      printf '%s' '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
      while IFS= read -r item; do
        key="${item#"$MOCK_REMOTE_ROOT/"}"
        printf '<Contents><Key>%s</Key></Contents>' "$key"
      done < <(find "$MOCK_REMOTE_ROOT" -type f -name 'novel-pipeline-backup-*.tar.gz.enc' -print | sort)
      printf '%s' '</ListBucketResult>'
    else
      cp "$target" "$output_file"
    fi
    ;;
  POST)
    if [[ "$url" == *"?uploads" ]]; then
      printf '%s' '<InitiateMultipartUploadResult><UploadId>mock-upload</UploadId></InitiateMultipartUploadResult>' > "$output_file"
    elif [[ "$url" == *"?uploadId="* ]]; then
      cat "${target}".part-* > "$target"
    fi
    ;;
  DELETE) rm -f "$target" "${target}".part-* ;;
esac
""",
        encoding="utf-8",
    )
    for executable in (fake_bin / "docker", fake_bin / "curl"):
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
            "R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
            "R2_BUCKET": "novel-tnn-backups",
            "R2_PREFIX": "novel-tnn-production",
            "R2_ACCESS_KEY_ID": "test-access-key-id",
            "R2_SECRET_ACCESS_KEY": "test-secret-access-key",
            "R2_MULTIPART_THRESHOLD_BYTES": "1",
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
    assert (remote_dir / "novel-tnn-production" / archive.name).is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.manifest.json").is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.sha256").is_file()
    assert "--network none" in docker_log.read_text(encoding="utf-8")
    assert "--user 0:0" in docker_log.read_text(encoding="utf-8")
