from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_backup.sh"
SERVICE = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.service"
TIMER = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.timer"
RUNBOOK = ROOT / "docs" / "production-backup-restore-runbook.md"
PINNED_IMAGE = "novel-pipeline-api@sha256:" + "a" * 64


def _validate_config(
    data_dir: Path,
    *,
    prepare_receipt: bool = True,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    if prepare_receipt:
        (data_dir / "logs" / "runtime").mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "BACKUP_DATA_DIR": str(data_dir),
        "BACKUP_LOCAL_DIR": str(data_dir.parent / "backups"),
        "BACKUP_IMAGE": PINNED_IMAGE,
        "RECOVERY_PRODUCER_VERSION": "runtime-hardening-20260718-r1",
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


def test_backup_static_validation_defers_private_receipt_authority_to_publisher(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, prepare_receipt=False)

    assert result.returncode == 0, result.stderr
    content = RUNNER.read_text(encoding="utf-8")
    assert '[[ -d "$RECOVERY_RECEIPT_DIR"' not in content
    assert 'realpath -e "$RECOVERY_RECEIPT_DIR"' not in content
    assert "verify_publisher_authority" in content


def test_backup_runner_rejects_mutable_image_tag(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, BACKUP_IMAGE="novel-pipeline-api:mutable-tag")

    assert result.returncode == 2
    assert "pinned by sha256 digest" in result.stderr


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
    assert "external-backup.receipt.json" in content
    assert content.index('upload_and_verify_remote "$archive_name"') < content.rindex('publish_recovery_receipt "sha256:')
    main_start = content.index("main()")
    assert content.index("rotate_remote_backups", main_start) < content.rindex('publish_recovery_receipt "sha256:')
    assert "OFFSITE_SFTP" not in content


def test_backup_checksum_metadata_must_name_the_selected_archive(tmp_path: Path) -> None:
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


def test_production_backup_runbook_describes_current_multipart_and_resume_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "uses an R2 single-object upload" not in runbook
    assert "R2 multipart protocol" in runbook
    assert "10,000-part limit" in runbook
    assert "--upload-existing ARCHIVE_BASENAME" in runbook


@pytest.mark.parametrize(
    "scenario",
    ["success", "upload_existing", "rotation_failure", "release_mismatch", "remote_archive_corrupt"],
)
def test_backup_runner_creates_and_verifies_an_encrypted_r2_copy(tmp_path: Path, scenario: str) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "external-backup.receipt.json"
    previous_receipt = b"previous-receipt\n"
    receipt_path.write_bytes(previous_receipt)
    (data_dir / "chapter.txt").write_text("backup fixture", encoding="utf-8")
    local_dir = tmp_path / "local"
    upload_existing_name = ""
    if scenario == "upload_existing":
        import hashlib

        from scripts.ops import create_encrypted_backup

        local_dir.mkdir()
        archive = create_encrypted_backup(
            data_dir=data_dir,
            out_dir=local_dir,
            passphrase="test-only-passphrase",
            keep=14,
            record_event=False,
        )
        upload_existing_name = archive.name
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (local_dir / f"{archive.name}.sha256").write_text(
            f"{digest}  {archive.name}\n",
            encoding="ascii",
        )
    remote_dir = tmp_path / "remote"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    remote_prefix = remote_dir / "novel-tnn-production"
    old_archive = "novel-pipeline-backup-20200101-010101.tar.gz.enc"
    remote_prefix.mkdir(parents=True)
    for suffix in ("", ".manifest.json", ".sha256"):
        (remote_prefix / f"{old_archive}{suffix}").write_text("old backup", encoding="utf-8")

    (fake_bin / "docker").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
.venv/bin/python - "$MOCK_DOCKER_LOG" "$@" <<'PY'
import json
from pathlib import Path
import sys

with Path(sys.argv[1]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[2:]) + "\\n")
PY
if [[ "$*" == *NOVEL_RELEASE_ID* ]]; then
  printf '%s\\n' "$MOCK_IMAGE_RELEASE"
  exit 0
fi
if [[ "$*" == *publisher-authority-preflight* ]]; then
  exit 0
fi
if [[ " $* " == *" scripts.record_restore_drill_status "* ]]; then
  translated=()
  while (($#)); do
    if [[ "$1" == "/receipts/"* ]]; then
      translated+=("$BACKUP_DATA_DIR/logs/runtime/${1#/receipts/}")
    elif [[ "$1" == "/data/"* ]]; then
      translated+=("$BACKUP_DATA_DIR/${1#/data/}")
    else
      translated+=("$1")
    fi
    shift
  done
  module_index=0
  for index in "${!translated[@]}"; do
    if [[ "${translated[$index]}" == "scripts.record_restore_drill_status" ]]; then
      module_index=$((index - 1))
      break
    fi
  done
  .venv/bin/python "${translated[@]:$module_index}"
  exit 0
fi
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
      [[ "${MOCK_FAIL_ROTATION:-0}" != "1" ]] || exit 55
      printf '%s' '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
      while IFS= read -r item; do
        key="${item#"$MOCK_REMOTE_ROOT/"}"
        printf '<Contents><Key>%s</Key></Contents>' "$key"
      done < <(find "$MOCK_REMOTE_ROOT" -type f -name 'novel-pipeline-backup-*.tar.gz.enc' -print | sort)
      printf '%s' '</ListBucketResult>'
    else
      cp "$target" "$output_file"
      if [[ "${MOCK_CORRUPT_REMOTE_ARCHIVE:-0}" == "1" && "$path" == *.tar.gz.enc ]]; then
        printf 'corrupt' >> "$output_file"
      fi
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

    runner_command = ["bash", str(RUNNER)]
    if upload_existing_name:
        runner_command.extend(["--upload-existing", upload_existing_name])
    result = subprocess.run(
        runner_command,
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MOCK_DOCKER_LOG": str(docker_log),
            "MOCK_REMOTE_ROOT": str(remote_dir),
            "BACKUP_DATA_DIR": str(data_dir),
            "BACKUP_LOCAL_DIR": str(local_dir),
            "BACKUP_IMAGE": PINNED_IMAGE,
            "RECOVERY_PRODUCER_VERSION": "runtime-hardening-20260718-r1",
            "BACKUP_PASSPHRASE": "test-only-passphrase",
            "R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
            "R2_BUCKET": "novel-tnn-backups",
            "R2_PREFIX": "novel-tnn-production",
            "R2_ACCESS_KEY_ID": "test-access-key-id",
            "R2_SECRET_ACCESS_KEY": "test-secret-access-key",
            "R2_MULTIPART_THRESHOLD_BYTES": "1",
            "BACKUP_KEEP_LOCAL": "14",
            "BACKUP_KEEP_OFFSITE": "1",
            "MOCK_FAIL_ROTATION": "1" if scenario == "rotation_failure" else "0",
            "MOCK_CORRUPT_REMOTE_ARCHIVE": "1" if scenario == "remote_archive_corrupt" else "0",
            "MOCK_IMAGE_RELEASE": "other-release" if scenario == "release_mismatch" else "runtime-hardening-20260718-r1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    if scenario not in {"success", "upload_existing"}:
        assert result.returncode != 0
        assert receipt_path.read_bytes() == previous_receipt
        if scenario == "release_mismatch":
            assert "BACKUP_IMAGE release does not match" in result.stderr
        if scenario == "remote_archive_corrupt":
            assert "remote archive does not match" in result.stderr
        return

    assert result.returncode == 0, result.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "passed"
    assert receipt["archive_hash_id"].startswith("sha256:")
    assert receipt["producer_version"] == "runtime-hardening-20260718-r1"
    assert receipt["validation_counts"] == {
        "archive_verified": 1,
        "checksum_verified": 1,
        "metadata_verified": 1,
        "remote_metadata_verified": 2,
        "remote_uploads_verified": 3,
    }
    assert "novel-pipeline-backup-" not in json.dumps(receipt)
    archive = next(local_dir.glob("novel-pipeline-backup-*.tar.gz.enc"))
    assert not list(local_dir.glob("novel-pipeline-backup-*.tar.gz"))
    assert (remote_dir / "novel-tnn-production" / archive.name).is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.manifest.json").is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.sha256").is_file()
    assert not (remote_prefix / old_archive).exists()
    assert not (remote_prefix / f"{old_archive}.manifest.json").exists()
    assert not (remote_prefix / f"{old_archive}.sha256").exists()
    assert list(remote_prefix.glob("novel-pipeline-backup-*.tar.gz.enc")) == [remote_prefix / archive.name]
    docker_invocations = [json.loads(line) for line in docker_log.read_text(encoding="utf-8").splitlines()]
    if scenario == "success":
        assert any("--user" in args and "0:0" in args for args in docker_invocations)
    else:
        assert not any("--user" in args and "0:0" in args for args in docker_invocations)
    publisher = next(args for args in docker_invocations if "scripts.record_restore_drill_status" in args)
    assert publisher[:2] == ["run", "--rm"]
    assert publisher[publisher.index("--network") + 1] == "none"
    assert publisher[publisher.index("--user") + 1] == "10001:10001"
    assert [publisher[index + 1] for index, arg in enumerate(publisher) if arg == "--mount"] == [
        f"type=bind,src={receipt_dir},dst=/receipts"
    ]
    assert "--env" not in publisher
    assert "--env-file" not in publisher
    assert PINNED_IMAGE in publisher
    assert publisher[publisher.index("--output") + 1] == "/receipts/external-backup.receipt.json"
    serialized_publisher = json.dumps(publisher)
    for forbidden in (
        "test-only-passphrase",
        "test-access-key-id",
        "test-secret-access-key",
        "0123456789abcdef0123456789abcdef",
        "novel-tnn-backups",
        "novel-tnn-production",
        str(local_dir),
        archive.name,
        ".manifest.json",
        ".sha256",
        "production.env",
    ):
        assert forbidden not in serialized_publisher
