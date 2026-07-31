from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_backup.sh"
SERVICE = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.service"
TIMER = ROOT / "deploy" / "systemd" / "user" / "novel-tnn-backup.timer"
RUNBOOK = ROOT / "docs" / "production-backup-restore-runbook.md"
OPERATIONS_RUNBOOK = ROOT / "docs" / "operations" / "runtime-alerts-and-rollback.md"
PINNED_IMAGE = "novel-pipeline-api@sha256:" + "a" * 64
MALICIOUS_IMAGE = "--env=IGNORED@sha256:" + "a" * 64


def _validate_config(
    data_dir: Path,
    *,
    arguments: tuple[str, ...] = ("--validate-config",),
    prepare_receipt_dir: bool = True,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    if prepare_receipt_dir:
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
        ["bash", str(RUNNER), *arguments],
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


@pytest.mark.parametrize(
    ("variable_name", "maximum"),
    [
        ("BACKUP_KEEP_LOCAL", "10000"),
        ("BACKUP_KEEP_OFFSITE", "10000"),
        ("R2_MULTIPART_THRESHOLD_BYTES", str(5 * 1024 * 1024 * 1024)),
        ("R2_MULTIPART_PART_BYTES", str(5 * 1024 * 1024 * 1024)),
    ],
)
def test_backup_runner_accepts_each_bounded_numeric_maximum(
    tmp_path: Path,
    variable_name: str,
    maximum: str,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, **{variable_name: maximum})

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("variable_name", "too_large"),
    [
        ("BACKUP_KEEP_LOCAL", "10001"),
        ("BACKUP_KEEP_OFFSITE", "10001"),
        ("R2_MULTIPART_THRESHOLD_BYTES", str(5 * 1024 * 1024 * 1024 + 1)),
        ("R2_MULTIPART_PART_BYTES", str(5 * 1024 * 1024 * 1024 + 1)),
    ],
)
def test_backup_runner_rejects_values_just_above_numeric_maximum(
    tmp_path: Path,
    variable_name: str,
    too_large: str,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, **{variable_name: too_large})

    assert result.returncode == 2
    assert "must be at most" in result.stderr


def test_backup_static_validation_defers_private_receipt_authority_to_image_preflight(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, prepare_receipt_dir=False)

    assert result.returncode == 0, result.stderr
    content = RUNNER.read_text(encoding="utf-8")
    static_validation = content[
        content.index("validate_config()") : content.index("verify_recovery_publisher_contract()")
    ]
    publisher_preflight = content[
        content.index("verify_recovery_publisher_contract()") : content.index("run_container_backup()")
    ]
    assert '[[ -d "$RECOVERY_RECEIPT_DIR"' not in static_validation
    assert 'realpath -e "$RECOVERY_RECEIPT_DIR"' not in static_validation
    assert "scripts.verify_recovery_publisher" in publisher_preflight
    assert "--expected-data-root-identity" in publisher_preflight


def test_backup_runner_rejects_mutable_image_tag(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, BACKUP_IMAGE="novel-pipeline-api:mutable-tag")

    assert result.returncode == 2
    assert "pinned by sha256 digest" in result.stderr


def test_backup_runner_rejects_an_image_option_operand(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, BACKUP_IMAGE=MALICIOUS_IMAGE)

    assert result.returncode == 2
    assert "safe sha256-pinned Docker reference" in result.stderr


def test_backup_runner_requires_an_explicit_pinned_image(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, BACKUP_IMAGE="")

    assert result.returncode == 2
    assert "BACKUP_IMAGE is required" in result.stderr


def test_backup_runner_rejects_missing_producer_version(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, RECOVERY_PRODUCER_VERSION="")

    assert result.returncode == 2
    assert "RECOVERY_PRODUCER_VERSION is required" in result.stderr


def test_backup_runner_rejects_invalid_producer_version(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(data_dir, RECOVERY_PRODUCER_VERSION="../wrong release")

    assert result.returncode == 2
    assert "safe release identifier" in result.stderr


def test_backup_runner_rejects_path_traversal_in_data_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    actual_data_dir = tmp_path / "actual-data"
    (actual_data_dir / "logs" / "runtime").mkdir(parents=True)
    unsafe_data_dir = data_dir / ".." / actual_data_dir.name

    result = _validate_config(
        data_dir,
        prepare_receipt_dir=False,
        BACKUP_DATA_DIR=str(unsafe_data_dir),
        RECOVERY_RECEIPT_DIR=str(unsafe_data_dir / "logs" / "runtime"),
    )

    assert result.returncode == 2
    assert "unsafe path" in result.stderr


def test_backup_runner_safely_normalizes_a_data_root_trailing_slash(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = _validate_config(
        data_dir,
        BACKUP_DATA_DIR=f"{data_dir}/",
        RECOVERY_RECEIPT_DIR=str(data_dir / "logs" / "runtime"),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("symlink_kind", ["final", "intermediate"])
def test_backup_runner_rejects_data_roots_with_symlink_components(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_data = real_parent / "data"
    (real_data / "logs" / "runtime").mkdir(parents=True)
    if symlink_kind == "final":
        supplied_data = tmp_path / "data-link"
        supplied_data.symlink_to(real_data, target_is_directory=True)
    else:
        alias_parent = tmp_path / "parent-link"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        supplied_data = alias_parent / "data"

    result = _validate_config(
        supplied_data,
        prepare_receipt_dir=False,
        RECOVERY_RECEIPT_DIR=str(supplied_data / "logs" / "runtime"),
    )

    assert result.returncode == 2
    assert "canonical real directory without symlink components" in result.stderr


@pytest.mark.parametrize(
    ("variable_name", "malformed_value"),
    [
        ("BACKUP_KEEP_LOCAL", "18446744073709551615"),
        ("BACKUP_KEEP_OFFSITE", "18446744073709551615"),
        ("BACKUP_KEEP_OFFSITE", "9" * 80),
        ("R2_MULTIPART_THRESHOLD_BYTES", "18446744073709551617"),
        ("R2_MULTIPART_PART_BYTES", "18446744073714794496"),
    ],
)
def test_backup_runner_rejects_unbounded_numeric_config_before_any_side_effect(
    tmp_path: Path,
    variable_name: str,
    malformed_value: str,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    marker = tmp_path / "side-effect"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for executable_name in ("curl", "docker", "sha256sum", "install"):
        executable = fake_bin / executable_name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' {shlex.quote(executable_name)} >>{shlex.quote(str(marker))}\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    environment = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        variable_name: malformed_value,
    }
    result = _validate_config(data_dir, arguments=(), **environment)

    assert result.returncode == 2
    assert "must be at most" in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "backups").exists()
    assert not list(tmp_path.rglob("*.receipt.json"))


def test_backup_static_validation_does_not_inspect_or_create_the_private_receipt_path(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    marker = tmp_path / "external-command-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for executable_name in ("docker", "curl"):
        executable = fake_bin / executable_name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf ran >{shlex.quote(str(marker))}\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    result = _validate_config(
        data_dir,
        prepare_receipt_dir=False,
        PATH=f"{fake_bin}:{os.environ['PATH']}",
    )

    assert result.returncode == 0, result.stderr
    assert "backup configuration validated" in result.stdout
    assert not (data_dir / "logs").exists()
    assert not (tmp_path / "backups").exists()
    assert not marker.exists()


def test_backup_rejects_an_invalid_existing_archive_before_preflight_or_directory_creation(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "events.log"
    command = f"""
source {shlex.quote(str(RUNNER))}
validate_config() {{ printf '%s\\n' validate >>{shlex.quote(str(event_log))}; }}
curl() {{ printf '%s\\n' curl >>{shlex.quote(str(event_log))}; }}
docker() {{ printf '%s\\n' docker >>{shlex.quote(str(event_log))}; }}
sha256sum() {{ printf '%s\\n' checksum >>{shlex.quote(str(event_log))}; }}
verify_recovery_publisher_contract() {{ printf '%s\\n' preflight >>{shlex.quote(str(event_log))}; }}
install() {{ printf '%s\\n' install >>{shlex.quote(str(event_log))}; }}
run_container_backup() {{ printf '%s\\n' archive >>{shlex.quote(str(event_log))}; }}
upload_and_verify_remote() {{ printf '%s\\n' upload >>{shlex.quote(str(event_log))}; }}
rotate_remote_backups() {{ printf '%s\\n' delete >>{shlex.quote(str(event_log))}; }}
publish_recovery_receipt() {{ printf '%s\\n' receipt >>{shlex.quote(str(event_log))}; }}
BACKUP_DATA_DIR={shlex.quote(str(tmp_path / "data"))} \
BACKUP_LOCAL_DIR={shlex.quote(str(tmp_path / "backups"))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
RECOVERY_PRODUCER_VERSION=release-a \
main --upload-existing ../../invalid.tar.gz.enc
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "supported encrypted backup basename" in result.stderr
    assert not event_log.exists()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    "archive_name",
    [
        "novel-pipeline-backup-20200230-120000.tar.gz.enc",
        "novel-pipeline-backup-29990101-000000.tar.gz.enc",
    ],
)
def test_backup_rejects_invalid_or_future_archive_timestamps_before_upload(
    tmp_path: Path,
    archive_name: str,
) -> None:
    side_effects = tmp_path / "side-effects"
    command = f"""
source {shlex.quote(str(RUNNER))}
validate_config() {{ :; }}
curl() {{ [[ "${{1:-}}" == "--help" ]] && printf '%s\n' '  --aws-sigv4 <provider>'; }}
docker() {{ :; }}
sha256sum() {{ :; }}
verify_recovery_publisher_contract() {{ :; }}
install() {{ :; }}
verify_local_backup() {{ :; }}
verify_existing_checksum() {{ printf '%s\n' checksum; }}
upload_and_verify_remote() {{ printf '%s\n' upload >>{shlex.quote(str(side_effects))}; }}
read_verified_checksum_hash() {{ printf '%064d\n' 0; }}
rotate_remote_backups() {{ :; }}
publish_recovery_receipt() {{ printf '%s\n' receipt >>{shlex.quote(str(side_effects))}; }}
BACKUP_DATA_DIR={shlex.quote(str(tmp_path / "data"))} \
BACKUP_LOCAL_DIR={shlex.quote(str(tmp_path / "backups"))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
RECOVERY_PRODUCER_VERSION=release-a \
main --upload-existing {shlex.quote(archive_name)}
"""

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "archive timestamp is invalid or exceeds allowed clock skew" in result.stderr
    assert not side_effects.exists()


@pytest.mark.parametrize("arguments", [[], ["--upload-existing", "novel-pipeline-backup-20260724-120000.tar.gz.enc"]])
def test_backup_preflight_failure_blocks_normal_and_existing_upload_side_effects(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    event_log = tmp_path / "events.log"
    receipt_dir = tmp_path / "data" / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "external-backup.receipt.json"
    previous_receipt = b"previous-receipt\n"
    receipt_path.write_bytes(previous_receipt)
    quoted_runner = shlex.quote(str(RUNNER))
    quoted_log = shlex.quote(str(event_log))
    quoted_args = " ".join(shlex.quote(argument) for argument in arguments)
    command = f"""
source {quoted_runner}
validate_config() {{ :; }}
curl() {{ [[ "${{1:-}}" == "--help" ]] && printf '%s\\n' '  --aws-sigv4 <provider>'; }}
docker() {{ :; }}
sha256sum() {{ :; }}
verify_recovery_publisher_contract() {{ printf '%s\\n' preflight >>{quoted_log}; return 73; }}
install() {{ printf '%s\\n' install >>{quoted_log}; }}
run_container_backup() {{ printf '%s\\n' create >>{quoted_log}; printf '%s\\n' novel-pipeline-backup-20260724-120000.tar.gz.enc; }}
verify_local_backup() {{ printf '%s\\n' process >>{quoted_log}; }}
verify_existing_checksum() {{ printf '%s\\n' process >>{quoted_log}; printf '%s\\n' checksum; }}
write_and_verify_checksum() {{ printf '%s\\n' process >>{quoted_log}; printf '%s\\n' checksum; }}
upload_and_verify_remote() {{ printf '%s\\n' upload >>{quoted_log}; }}
read_verified_checksum_hash() {{ printf '%064d\\n' 0; }}
rotate_remote_backups() {{ printf '%s\\n' rotate >>{quoted_log}; }}
publish_recovery_receipt() {{ printf '%s\\n' publish >>{quoted_log}; }}
BACKUP_DATA_DIR={shlex.quote(str(tmp_path / "data"))} \
BACKUP_LOCAL_DIR={shlex.quote(str(tmp_path / "backups"))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
RECOVERY_PRODUCER_VERSION=release-a \
main {quoted_args}
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=os.environ,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 73
    assert event_log.read_text(encoding="utf-8").splitlines() == ["preflight"]
    assert receipt_path.read_bytes() == previous_receipt
    assert not (tmp_path / "backups").exists()
    assert not list(receipt_dir.glob(".recovery-publisher-probe-*"))


def test_backup_docker_calls_use_image_owned_preflight_and_terminated_image_operand(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    python_log = tmp_path / "python.log"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$MOCK_PYTHON_LOG"
if [[ "${1:-} ${2:-}" == "-m scripts.verify_recovery_publisher" ]]; then
  shift 2
  expected_release=
  expected_identity=
  while (($#)); do
    case "$1" in
      --data-root|--receipt-dir) shift 2 ;;
      --expected-release) expected_release="$2"; shift 2 ;;
      --expected-data-root-identity) expected_identity="$2"; shift 2 ;;
      *) exit 90 ;;
    esac
  done
  [[ "$expected_release" == "$MOCK_IMAGE_RELEASE" ]] || exit 74
  [[ "$expected_identity" == "$(stat --format='%d:%i' -- "$MOCK_DATA_ROOT")" ]] || exit 75
  exit 0
fi
if [[ "${1:-} ${2:-}" == "-m scripts.record_restore_drill_status" ]]; then
  exit 0
fi
exit 91
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
.venv/bin/python - "$MOCK_DOCKER_LOG" "$@" <<'PY'
import json
from pathlib import Path
import sys

with Path(sys.argv[1]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[2:]) + "\\n")
PY
data_root=
while (($#)); do
  case "$1" in
    --mount)
      mount_spec="$2"
      source_path="${mount_spec#*src=}"
      source_path="${source_path%%,dst=*}"
      destination="${mount_spec#*,dst=}"
      destination="${destination%%,*}"
      [[ "$destination" != "/data-root" && "$destination" != "/data" ]] || data_root="$source_path"
      shift 2
      ;;
    --) shift; break ;;
    *) shift ;;
  esac
done
[[ $# -gt 1 ]]
shift
if [[ "${1:-} ${2:-}" == "python -c" ]]; then
  printf '%s\\n' novel-pipeline-backup-20260724-120000.tar.gz.enc
  exit 0
fi
MOCK_DATA_ROOT="$data_root" "$@"
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
BACKUP_DATA_DIR={shlex.quote(str(data_dir))}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RECOVERY_PRODUCER_VERSION=release-a
BACKUP_KEEP_LOCAL=14
BACKUP_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$BACKUP_DATA_DIR")"
verify_recovery_publisher_contract
run_container_backup >/dev/null
publish_recovery_receipt sha256:{'a' * 64} 2020-01-02T03:04:05+00:00
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MOCK_DOCKER_LOG": str(docker_log),
            "MOCK_PYTHON_LOG": str(python_log),
            "MOCK_IMAGE_RELEASE": "release-a",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in docker_log.read_text(encoding="utf-8").splitlines()]
    assert len(invocations) == 3
    for invocation in invocations:
        image_index = invocation.index(PINNED_IMAGE)
        assert invocation[image_index - 1] == "--"
        assert "/preflight/" not in "\n".join(invocation)
    preflight, archive, publisher = invocations
    expected_receipt_mounts = [
        f"type=bind,src={data_dir},dst=/data-root,readonly",
        f"type=bind,src={receipt_dir},dst=/receipts",
    ]
    assert [preflight[index + 1] for index, arg in enumerate(preflight) if arg == "--mount"] == expected_receipt_mounts
    assert [publisher[index + 1] for index, arg in enumerate(publisher) if arg == "--mount"] == expected_receipt_mounts
    assert [archive[index + 1] for index, arg in enumerate(archive) if arg == "--mount"] == [
        f"type=bind,src={data_dir},dst=/data,readonly",
        f"type=bind,src={backup_dir},dst=/backups",
    ]
    archive_script = archive[archive.index("-c") + 1]
    assert "checkpoint_database=False" in archive_script
    assert "record_event=False" in archive_script
    assert "scripts.verify_recovery_publisher" in "\n".join(preflight)
    assert "scripts.verify_recovery_publisher" in "\n".join(publisher)
    assert "scripts.record_restore_drill_status" in publisher
    python_calls = python_log.read_text(encoding="utf-8").splitlines()
    assert [call.split()[1] for call in python_calls] == [
        "scripts.verify_recovery_publisher",
        "scripts.verify_recovery_publisher",
        "scripts.record_restore_drill_status",
    ]


@pytest.mark.parametrize(
    ("switch_before", "expected_docker_calls"),
    [("archive", 2), ("publication", 3)],
)
def test_backup_fails_closed_when_data_root_identity_changes_between_critical_containers(
    tmp_path: Path,
    switch_before: str,
    expected_docker_calls: int,
) -> None:
    data_dir = tmp_path / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "external-backup.receipt.json"
    previous_receipt = b"previous-receipt\n"
    receipt_path.write_bytes(previous_receipt)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    original_data_dir = tmp_path / "original-data"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
.venv/bin/python - "$MOCK_DOCKER_LOG" "$@" <<'PY'
import json
from pathlib import Path
import sys

with Path(sys.argv[1]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[2:]) + "\\n")
PY
mount_source=
identity_argument=0
all_arguments=("$@")
for argument in "${all_arguments[@]}"; do
  [[ "$argument" != "$MOCK_EXPECTED_IDENTITY" ]] || identity_argument=1
done
while (($#)); do
  case "$1" in
    --mount)
      source_path="${2#*src=}"
      source_path="${source_path%%,dst=*}"
      destination="${2#*,dst=}"
      destination="${destination%%,*}"
      [[ "$destination" != "/data-root" && "$destination" != "/data" ]] || mount_source="$source_path"
      shift 2
      ;;
    *) shift ;;
  esac
done
[[ "$identity_argument" == "1" ]] || exit 76
[[ "$(stat --format='%d:%i' -- "$mount_source")" == "$MOCK_EXPECTED_IDENTITY" ]] || exit 75
if [[ " ${all_arguments[*]} " == *" python -c "* ]]; then
  printf '%s\\n' novel-pipeline-backup-20260724-120000.tar.gz.enc
fi
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
BACKUP_DATA_DIR={shlex.quote(str(data_dir))}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RECOVERY_PRODUCER_VERSION=release-a
BACKUP_KEEP_LOCAL=14
BACKUP_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$BACKUP_DATA_DIR")"
switch_root() {{
  mv -- "$BACKUP_DATA_DIR" {shlex.quote(str(original_data_dir))}
  mkdir -p -- "$BACKUP_DATA_DIR/logs/runtime"
}}
verify_recovery_publisher_contract
if [[ {shlex.quote(switch_before)} == archive ]]; then
  switch_root
fi
run_container_backup >/dev/null
if [[ {shlex.quote(switch_before)} == publication ]]; then
  switch_root
fi
publish_recovery_receipt sha256:{'a' * 64} 2020-01-02T03:04:05+00:00
"""
    expected_identity = f"{data_dir.stat().st_dev}:{data_dir.stat().st_ino}"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MOCK_DOCKER_LOG": str(docker_log),
            "MOCK_EXPECTED_IDENTITY": expected_identity,
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    invocations = docker_log.read_text(encoding="utf-8").splitlines()
    assert len(invocations) == expected_docker_calls
    assert (original_data_dir / "logs" / "runtime" / receipt_path.name).read_bytes() == previous_receipt
    assert not (data_dir / "logs" / "runtime" / receipt_path.name).exists()
    assert not list(backup_dir.glob("novel-pipeline-backup-*.tar.gz.enc"))


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
    operations_runbook = OPERATIONS_RUNBOOK.read_text(encoding="utf-8")

    assert "uses an R2 single-object upload" not in runbook
    assert "R2 multipart protocol" in runbook
    assert "10,000-part limit" in runbook
    assert "--upload-existing ARCHIVE_BASENAME" in runbook
    assert "helper from that exact image" in runbook
    assert "must remain stopped" in runbook
    for document in (runbook, operations_runbook):
        assert "full data root read-only" in document
        assert "only writable recovery metadata mount" in document
        assert "clean committed runner bytes" in document


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "upload_existing",
        "upload_existing_old",
        "rotation_failure",
        "release_mismatch",
        "remote_archive_corrupt",
        "publication_failure",
    ],
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
    if scenario in {"upload_existing", "upload_existing_old"}:
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
        if scenario == "upload_existing_old":
            existing_sidecar = Path(f"{archive}.manifest.json")
            old_archive = local_dir / "novel-pipeline-backup-20200102-030405.tar.gz.enc"
            old_sidecar = Path(f"{old_archive}.manifest.json")
            archive.rename(old_archive)
            metadata = json.loads(existing_sidecar.read_text(encoding="utf-8"))
            metadata["backup_filename"] = old_archive.name
            existing_sidecar.rename(old_sidecar)
            old_sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            archive = old_archive
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

    (fake_bin / "python").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-} ${2:-}" == "-m scripts.verify_recovery_publisher" ]]; then
  shift 2
  expected_release=
  expected_identity=
  while (($#)); do
    case "$1" in
      --data-root|--receipt-dir) shift 2 ;;
      --expected-release) expected_release="$2"; shift 2 ;;
      --expected-data-root-identity) expected_identity="$2"; shift 2 ;;
      *) exit 90 ;;
    esac
  done
  [[ "$expected_release" == "$MOCK_IMAGE_RELEASE" ]] || exit 74
  [[ "$expected_identity" == "$(stat --format='%d:%i' -- "$MOCK_DATA_ROOT")" ]] || exit 75
  [[ "$MOCK_RECEIPT_DIR" == "$MOCK_DATA_ROOT/logs/runtime" ]] || exit 76
  probe="$MOCK_RECEIPT_DIR/.recovery-publisher-probe-fake"
  (umask 077; printf '%s\\n' probe >"$probe")
  rm -- "$probe"
  .venv/bin/python -c 'import scripts.record_restore_drill_status'
  exit 0
fi
if [[ "${1:-} ${2:-}" == "-m scripts.record_restore_drill_status" ]]; then
  [[ "${MOCK_FAIL_PUBLICATION:-0}" != "1" ]] || exit 73
  translated=()
  while (($#)); do
    if [[ "$1" == /receipts/* ]]; then
      translated+=("$MOCK_RECEIPT_DIR/${1#/receipts/}")
    else
      translated+=("$1")
    fi
    shift
  done
  exec .venv/bin/python "${translated[@]}"
fi
exit 91
""",
        encoding="utf-8",
    )
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
data_root=
receipt_dir=
while (($#)); do
  case "$1" in
    --mount)
      mount_spec="$2"
      source_path="${mount_spec#*src=}"
      source_path="${source_path%%,dst=*}"
      destination="${mount_spec#*,dst=}"
      destination="${destination%%,*}"
      [[ "$destination" != "/data-root" && "$destination" != "/data" ]] || data_root="$source_path"
      [[ "$destination" != "/receipts" ]] || receipt_dir="$source_path"
      shift 2
      ;;
    --) shift; break ;;
    *) shift ;;
  esac
done
[[ $# -gt 1 ]]
shift
if [[ "${1:-} ${2:-}" == "python -c" ]]; then
  expected_identity="${@: -1}"
  [[ "$expected_identity" == "$(stat --format='%d:%i' -- "$data_root")" ]] || exit 75
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
  exit 0
fi
MOCK_DATA_ROOT="$data_root" MOCK_RECEIPT_DIR="$receipt_dir" "$@"
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
    for executable in (fake_bin / "docker", fake_bin / "curl", fake_bin / "python"):
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
            "MOCK_FAIL_PUBLICATION": "1" if scenario == "publication_failure" else "0",
            "MOCK_IMAGE_RELEASE": "other-release" if scenario == "release_mismatch" else "runtime-hardening-20260718-r1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    if scenario not in {"success", "upload_existing", "upload_existing_old"}:
        assert result.returncode != 0
        assert receipt_path.read_bytes() == previous_receipt
        if scenario == "release_mismatch":
            assert "recovery publisher preflight failed" in result.stderr
        if scenario == "remote_archive_corrupt":
            assert "remote archive does not match" in result.stderr
        if scenario == "publication_failure":
            assert list(local_dir.glob("novel-pipeline-backup-*.tar.gz.enc"))
            assert "recovery receipt publication failed" in result.stderr
        assert not list(receipt_dir.glob(".external-backup.receipt.json.*"))
        assert not list(receipt_dir.glob(".recovery-publisher-probe-*"))
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
    archive = next(local_dir.glob("novel-pipeline-backup-*.tar.gz.enc"))
    archive_timestamp = datetime.strptime(archive.name[22:37], "%Y%m%d-%H%M%S").replace(
        tzinfo=timezone.utc
    )
    assert receipt["completed_at"] == archive_timestamp.isoformat()
    assert "novel-pipeline-backup-" not in json.dumps(receipt)
    assert not list(local_dir.glob("novel-pipeline-backup-*.tar.gz"))
    assert (remote_dir / "novel-tnn-production" / archive.name).is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.manifest.json").is_file()
    assert (remote_dir / "novel-tnn-production" / f"{archive.name}.sha256").is_file()
    assert not (remote_prefix / old_archive).exists()
    assert not (remote_prefix / f"{old_archive}.manifest.json").exists()
    assert not (remote_prefix / f"{old_archive}.sha256").exists()
    assert list(remote_prefix.glob("novel-pipeline-backup-*.tar.gz.enc")) == [remote_prefix / archive.name]
    docker_invocations = [json.loads(line) for line in docker_log.read_text(encoding="utf-8").splitlines()]
    preflight = next(
        args
        for args in docker_invocations
        if "scripts.verify_recovery_publisher" in args and "scripts.record_restore_drill_status" not in args
    )
    assert preflight[preflight.index("--network") + 1] == "none"
    assert preflight[preflight.index("--user") + 1] == "10001:10001"
    assert [preflight[index + 1] for index, arg in enumerate(preflight) if arg == "--mount"] == [
        f"type=bind,src={data_dir},dst=/data-root,readonly",
        f"type=bind,src={receipt_dir},dst=/receipts",
    ]
    assert preflight[preflight.index(PINNED_IMAGE) - 1] == "--"
    assert "/preflight/" not in "\n".join(preflight)
    if scenario == "success":
        archive_invocation = next(
            args
            for args in docker_invocations
            if "--user" in args and "0:0" in args
        )
        assert archive_invocation[archive_invocation.index(PINNED_IMAGE) - 1] == "--"
        assert [archive_invocation[index + 1] for index, arg in enumerate(archive_invocation) if arg == "--mount"] == [
            f"type=bind,src={data_dir},dst=/data,readonly",
            f"type=bind,src={local_dir},dst=/backups",
        ]
    else:
        assert not any("--user" in args and "0:0" in args for args in docker_invocations)
    publisher = next(args for args in docker_invocations if "scripts.record_restore_drill_status" in args)
    assert publisher[:2] == ["run", "--rm"]
    assert publisher[publisher.index("--network") + 1] == "none"
    assert publisher[publisher.index("--user") + 1] == "10001:10001"
    assert [publisher[index + 1] for index, arg in enumerate(publisher) if arg == "--mount"] == [
        f"type=bind,src={data_dir},dst=/data-root,readonly",
        f"type=bind,src={receipt_dir},dst=/receipts",
    ]
    assert "--env" not in publisher
    assert "--env-file" not in publisher
    assert PINNED_IMAGE in publisher
    assert publisher[publisher.index(PINNED_IMAGE) - 1] == "--"
    assert "scripts.verify_recovery_publisher" in "\n".join(publisher)
    assert "/preflight/" not in "\n".join(publisher)
    assert publisher[publisher.index("--output") + 1] == "/receipts/external-backup.receipt.json"
    assert publisher[publisher.index("--completed-at") + 1] == archive_timestamp.isoformat()
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
