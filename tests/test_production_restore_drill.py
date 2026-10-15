from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "production_restore_drill.sh"
RUNBOOKS = (
    ROOT / "docs" / "production-backup-restore-runbook.md",
    ROOT / "docs" / "operations" / "runtime-alerts-and-rollback.md",
)
PINNED_IMAGE = "novel-pipeline-api@sha256:" + "a" * 64
MALICIOUS_IMAGE = "--env=IGNORED@sha256:" + "a" * 64


def _validate_config(
    backup_dir: Path,
    *,
    prepare_data_dir: bool = True,
    prepare_drill_root: bool = True,
    prepare_receipt_dir: bool = True,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    production_root = backup_dir.parent / "production"
    if prepare_data_dir:
        (production_root / "data").mkdir(parents=True, exist_ok=True)
    if prepare_receipt_dir:
        (production_root / "data" / "logs" / "runtime").mkdir(parents=True, exist_ok=True)
    drill_root = backup_dir.parent / "drills"
    if prepare_drill_root:
        drill_root.mkdir(mode=0o700, exist_ok=True)
        drill_root.chmod(0o700)
    environment = {
        **os.environ,
        "BACKUP_LOCAL_DIR": str(backup_dir),
        "BACKUP_DRILL_ROOT": str(drill_root),
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

    result = _validate_config(backup_dir, prepare_drill_root=False, BACKUP_PASSPHRASE="")

    assert result.returncode == 2
    assert "BACKUP_PASSPHRASE" in result.stderr
    assert not (tmp_path / "drills").exists()


def test_restore_static_validation_defers_private_receipt_authority_to_image_preflight(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, prepare_receipt_dir=False)

    assert result.returncode == 0, result.stderr
    content = RUNNER.read_text(encoding="utf-8")
    static_validation = content[
        content.index("validate_config()") : content.index("verify_recovery_publisher_contract()")
    ]
    publisher_preflight = content[
        content.index("verify_recovery_publisher_contract()") : content.index("select_archive()")
    ]
    assert '[[ -d "$RECOVERY_RECEIPT_DIR"' not in static_validation
    assert 'realpath -e "$RECOVERY_RECEIPT_DIR"' not in static_validation
    assert "scripts.verify_recovery_publisher" in publisher_preflight
    assert "--expected-data-root-identity" in publisher_preflight


def test_restore_runner_requires_an_explicit_pinned_image(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, BACKUP_IMAGE="")

    assert result.returncode == 2
    assert "BACKUP_IMAGE is required" in result.stderr


def test_restore_runner_rejects_a_mutable_image(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, BACKUP_IMAGE="novel-pipeline-api:mutable")

    assert result.returncode == 2
    assert "pinned by sha256 digest" in result.stderr


def test_restore_runner_rejects_an_image_option_operand(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _validate_config(backup_dir, BACKUP_IMAGE=MALICIOUS_IMAGE)

    assert result.returncode == 2
    assert "safe sha256-pinned Docker reference" in result.stderr


def test_restore_runner_rejects_missing_or_invalid_producer_version(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    missing = _validate_config(backup_dir, RECOVERY_PRODUCER_VERSION="")
    invalid = _validate_config(backup_dir, RECOVERY_PRODUCER_VERSION="../wrong release")

    assert missing.returncode == 2
    assert "RECOVERY_PRODUCER_VERSION is required" in missing.stderr
    assert invalid.returncode == 2
    assert "safe release identifier" in invalid.stderr


def test_restore_runner_rejects_path_traversal_in_production_root(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    unsafe_root = backup_dir.parent / "unused" / ".." / "production"

    result = _validate_config(
        backup_dir,
        RESTORE_ARTIFACT_SOURCE_ROOT=str(unsafe_root),
        RESTORE_DATA_DIR=str(unsafe_root / "data"),
        RECOVERY_RECEIPT_DIR=str(unsafe_root / "data" / "logs" / "runtime"),
    )

    assert result.returncode == 2
    assert "unsafe path" in result.stderr


def test_restore_runner_safely_normalizes_a_data_root_trailing_slash(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "production" / "data"

    result = _validate_config(
        backup_dir,
        RESTORE_DATA_DIR=f"{data_dir}/",
        RECOVERY_RECEIPT_DIR=str(data_dir / "logs" / "runtime"),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("symlink_kind", ["final", "intermediate"])
def test_restore_runner_rejects_data_roots_with_symlink_components(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    production_root = tmp_path / "production"
    real_parent = tmp_path / "real-parent"
    real_data = real_parent / "data"
    (real_data / "logs" / "runtime").mkdir(parents=True)
    if symlink_kind == "final":
        production_root.mkdir()
        supplied_data = production_root / "data"
        supplied_data.symlink_to(real_data, target_is_directory=True)
        supplied_root = production_root
    else:
        supplied_root = tmp_path / "production-link"
        supplied_root.symlink_to(real_parent, target_is_directory=True)
        supplied_data = supplied_root / "data"

    result = _validate_config(
        backup_dir,
        prepare_data_dir=False,
        prepare_receipt_dir=False,
        RESTORE_ARTIFACT_SOURCE_ROOT=str(supplied_root),
        RESTORE_DATA_DIR=str(supplied_data),
        RECOVERY_RECEIPT_DIR=str(supplied_data / "logs" / "runtime"),
    )

    assert result.returncode == 2
    assert "canonical real directory without symlink components" in result.stderr


@pytest.mark.parametrize("drill_location", ["equal", "descendant"])
def test_restore_runner_rejects_a_drill_root_in_the_live_data_tree(
    tmp_path: Path,
    drill_location: str,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "production" / "data"
    drill_root = data_dir if drill_location == "equal" else data_dir / "restore-drills"
    (data_dir / "logs" / "runtime").mkdir(parents=True)
    data_dir.chmod(0o700)
    if drill_location == "descendant":
        drill_root.mkdir(mode=0o700)

    result = _validate_config(backup_dir, BACKUP_DRILL_ROOT=str(drill_root))

    assert result.returncode == 2
    assert "BACKUP_DRILL_ROOT must be outside RESTORE_DATA_DIR" in result.stderr


def test_restore_runner_rejects_an_existing_drill_root_symlinked_into_live_data(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "production" / "data"
    aliased_drill_root = data_dir / "restore-drills"
    aliased_drill_root.mkdir(parents=True)
    supplied_drill_root = tmp_path / "drills-alias"
    supplied_drill_root.symlink_to(aliased_drill_root, target_is_directory=True)

    result = _validate_config(backup_dir, BACKUP_DRILL_ROOT=str(supplied_drill_root))

    assert result.returncode == 2
    assert "canonical non-symlink directory" in result.stderr


def test_restore_runner_accepts_a_canonical_sibling_drill_root(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    drill_root = tmp_path / "restore-drills"
    drill_root.mkdir(mode=0o700)

    result = _validate_config(backup_dir, BACKUP_DRILL_ROOT=str(drill_root))

    assert result.returncode == 0, result.stderr
    assert "restore drill configuration validated" in result.stdout


def test_restore_runner_rejects_a_missing_drill_root_before_it_can_be_swapped_into_live_data(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "production" / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    drill_root = tmp_path / "missing-drills"
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' restored-20260724-120000\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    before = sorted(path.relative_to(data_dir) for path in data_dir.rglob("*"))
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))}
BACKUP_DRILL_ROOT={shlex.quote(str(drill_root))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
BACKUP_PASSPHRASE=test-passphrase
PRODUCTION_ENV={shlex.quote(str(production_env))}
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(data_dir.parent))}
RESTORE_DATA_DIR={shlex.quote(str(data_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RECOVERY_PRODUCER_VERSION=release-a
validate_config
ln -s -- "$RESTORE_DATA_DIR" "$BACKUP_DRILL_ROOT"
restore_into_new_drill novel-pipeline-backup-20260724-120000.tar.gz.enc >/dev/null
"""

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "BACKUP_DRILL_ROOT must be an existing" in result.stderr
    assert sorted(path.relative_to(data_dir) for path in data_dir.rglob("*")) == before


def test_restore_runner_rejects_existing_drill_root_substitution_without_touching_live_data(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "production" / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    drill_root = tmp_path / "drills"
    drill_root.mkdir(mode=0o700)
    held_root = tmp_path / "original-drills"
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' restored-20260724-120000\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    before = sorted(path.relative_to(data_dir) for path in data_dir.rglob("*"))
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))}
BACKUP_DRILL_ROOT={shlex.quote(str(drill_root))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
BACKUP_PASSPHRASE=test-passphrase
PRODUCTION_ENV={shlex.quote(str(production_env))}
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(data_dir.parent))}
RESTORE_DATA_DIR={shlex.quote(str(data_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RECOVERY_PRODUCER_VERSION=release-a
validate_config
mv -- "$BACKUP_DRILL_ROOT" {shlex.quote(str(held_root))}
ln -s -- "$RESTORE_DATA_DIR" "$BACKUP_DRILL_ROOT"
restore_into_new_drill novel-pipeline-backup-20260724-120000.tar.gz.enc >/dev/null
"""

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "BACKUP_DRILL_ROOT identity changed" in result.stderr
    assert sorted(path.relative_to(data_dir) for path in data_dir.rglob("*")) == before


def test_recovery_runbook_bash_blocks_are_fail_fast_and_syntax_valid() -> None:
    checked_blocks = 0
    for document in RUNBOOKS:
        content = document.read_text(encoding="utf-8")
        blocks = re.findall(r"^```bash\n(.*?)^```$", content, flags=re.MULTILINE | re.DOTALL)
        assert blocks, document
        for block_number, block in enumerate(blocks, start=1):
            checked_blocks += 1
            assert block.splitlines()[0] == "set -euo pipefail", (
                f"{document}: bash block {block_number} lacks fail-fast semantics"
            )
            result = subprocess.run(
                ["bash", "-n"],
                input=block,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, f"{document}: bash block {block_number}: {result.stderr}"
    assert checked_blocks == 13


def test_restore_static_validation_does_not_inspect_or_create_the_private_receipt_path(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    marker = tmp_path / "external-command-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for executable_name in ("docker", "sha256sum"):
        executable = fake_bin / executable_name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf ran >{shlex.quote(str(marker))}\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    result = _validate_config(
        backup_dir,
        prepare_receipt_dir=False,
        PATH=f"{fake_bin}:{os.environ['PATH']}",
    )

    assert result.returncode == 0, result.stderr
    assert "restore drill configuration validated" in result.stdout
    assert not (tmp_path / "production" / "data" / "logs").exists()
    assert list((tmp_path / "drills").iterdir()) == []
    assert not marker.exists()


def test_restore_preflight_failure_blocks_archive_processing_and_drill_creation(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "events.log"
    receipt_dir = tmp_path / "production" / "data" / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "restore-drill.receipt.json"
    previous_receipt = b"previous-restore-receipt\n"
    receipt_path.write_bytes(previous_receipt)
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
    quoted_runner = shlex.quote(str(RUNNER))
    quoted_log = shlex.quote(str(event_log))
    command = f"""
source {quoted_runner}
validate_config() {{ :; }}
docker() {{ :; }}
sha256sum() {{ :; }}
verify_recovery_publisher_contract() {{ printf '%s\\n' preflight >>{quoted_log}; return 73; }}
select_archive() {{ printf '%s\\n' select >>{quoted_log}; printf '%s\\n' novel-pipeline-backup-20260724-120000.tar.gz.enc; }}
verify_backup_input() {{ printf '%s\\n' process >>{quoted_log}; }}
restore_into_new_drill() {{ printf '%s\\n' restore >>{quoted_log}; }}
BACKUP_LOCAL_DIR={shlex.quote(str(tmp_path / "backups"))} \
BACKUP_DRILL_ROOT={shlex.quote(str(tmp_path / "drills"))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
PRODUCTION_ENV={shlex.quote(str(production_env))} \
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(tmp_path / "production"))} \
RECOVERY_PRODUCER_VERSION=release-a \
main novel-pipeline-backup-20260724-120000.tar.gz.enc
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
    assert not (tmp_path / "drills").exists()
    assert not list(receipt_dir.glob(".recovery-publisher-probe-*"))


def test_restore_rejects_an_invalid_archive_before_preflight_or_drill_creation(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "events.log"
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
    command = f"""
source {shlex.quote(str(RUNNER))}
validate_config() {{ printf '%s\\n' validate >>{shlex.quote(str(event_log))}; }}
docker() {{ printf '%s\\n' docker >>{shlex.quote(str(event_log))}; }}
sha256sum() {{ printf '%s\\n' checksum >>{shlex.quote(str(event_log))}; }}
verify_recovery_publisher_contract() {{ printf '%s\\n' preflight >>{shlex.quote(str(event_log))}; }}
select_archive() {{ printf '%s\\n' select >>{shlex.quote(str(event_log))}; }}
verify_backup_input() {{ printf '%s\\n' archive >>{shlex.quote(str(event_log))}; }}
restore_into_new_drill() {{ printf '%s\\n' restore >>{shlex.quote(str(event_log))}; }}
publish_recovery_receipt() {{ printf '%s\\n' receipt >>{shlex.quote(str(event_log))}; }}
BACKUP_LOCAL_DIR={shlex.quote(str(tmp_path / "backups"))} \
BACKUP_DRILL_ROOT={shlex.quote(str(tmp_path / "drills"))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
PRODUCTION_ENV={shlex.quote(str(production_env))} \
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(tmp_path / "production"))} \
RECOVERY_PRODUCER_VERSION=release-a \
main ../../invalid.tar.gz.enc
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
    assert "supported encrypted backup" in result.stderr
    assert not event_log.exists()
    assert not (tmp_path / "drills").exists()


def test_restore_preflight_and_publication_use_the_authoritative_dual_mount_contract(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "production" / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
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
  actual_identity="$(stat --format='%d:%i' -- "$MOCK_DATA_ROOT")"
  [[ "$expected_identity" == "$actual_identity" ]] || exit 75
  probe="$MOCK_RECEIPT_DIR/.recovery-publisher-probe-fake"
  (umask 077; printf '%s\\n' probe >"$probe")
  rm -- "$probe"
  exit 0
fi
if [[ "${1:-} ${2:-}" == "-m scripts.record_restore_drill_status" ]]; then
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
receipt_dir=
while (($#)); do
  case "$1" in
    --mount)
      mount_spec="$2"
      source_path="${mount_spec#*src=}"
      source_path="${source_path%%,dst=*}"
      destination="${mount_spec#*,dst=}"
      destination="${destination%%,*}"
      [[ "$destination" != "/data-root" ]] || data_root="$source_path"
      [[ "$destination" != "/receipts" ]] || receipt_dir="$source_path"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      shift
      ;;
  esac
done
[[ $# -gt 1 ]]
shift
MOCK_DATA_ROOT="$data_root" MOCK_RECEIPT_DIR="$receipt_dir" "$@"
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
RECOVERY_PRODUCER_VERSION=release-a
RESTORE_DATA_DIR={shlex.quote(str(data_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RESTORE_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$RESTORE_DATA_DIR")"
verify_recovery_publisher_contract
publish_recovery_receipt sha256:{'a' * 64} 7
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
    assert len(invocations) == 2
    for invocation in invocations:
        assert invocation[invocation.index("--network") + 1] == "none"
        assert invocation[invocation.index("--user") + 1] == "10001:10001"
        assert [invocation[index + 1] for index, arg in enumerate(invocation) if arg == "--mount"][:2] == [
            f"type=bind,src={data_dir},dst=/data-root,readonly",
            f"type=bind,src={receipt_dir},dst=/receipts",
        ]
        assert [invocation[index + 1] for index, arg in enumerate(invocation) if arg == "--mount"] == [
            f"type=bind,src={data_dir},dst=/data-root,readonly",
            f"type=bind,src={receipt_dir},dst=/receipts",
        ]
        image_index = invocation.index(PINNED_IMAGE)
        assert invocation[image_index - 1] == "--"
        assert "scripts.verify_recovery_publisher" in "\n".join(invocation)
        assert "/preflight/" not in "\n".join(invocation)
    publisher = invocations[1]
    assert "scripts.record_restore_drill_status" in publisher
    assert publisher[publisher.index("--output") + 1] == "/receipts/restore-drill.receipt.json"
    assert "--env" not in publisher
    assert "--env-file" not in publisher
    python_calls = python_log.read_text(encoding="utf-8").splitlines()
    assert [call.split()[1] for call in python_calls] == [
        "scripts.verify_recovery_publisher",
        "scripts.verify_recovery_publisher",
        "scripts.record_restore_drill_status",
    ]
    receipt = json.loads((receipt_dir / "restore-drill.receipt.json").read_text(encoding="utf-8"))
    assert receipt["archive_hash_id"] == "sha256:" + "a" * 64


def test_every_restore_docker_run_terminates_options_before_the_image_operand(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "production" / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    drill_root = tmp_path / "drills"
    drill_root.mkdir(mode=0o700)
    restored_dir = tmp_path / "restored-20260724-120000"
    restored_dir.mkdir()
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
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
[[ "${1:-}" == run ]] || exit 0
if [[ " $* " == *" -i "* ]]; then
  cat >/dev/null
  printf '%s\\n' '{"artifact_paths_scanned": 0}'
elif [[ "$*" == *"restore_drill"* ]]; then
  printf '%s\\n' restored-20260724-120000
fi
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    report_path = tmp_path / "report.json"
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))}
BACKUP_DRILL_ROOT={shlex.quote(str(drill_root))}
BACKUP_PASSPHRASE=test-passphrase
PRODUCTION_ENV={shlex.quote(str(production_env))}
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(tmp_path / "production"))}
RESTORE_DATA_DIR={shlex.quote(str(data_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RECOVERY_PRODUCER_VERSION=release-a
RESTORE_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$RESTORE_DATA_DIR")"
BACKUP_DRILL_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$BACKUP_DRILL_ROOT")"
verify_recovery_publisher_contract
restore_into_new_drill novel-pipeline-backup-20260724-120000.tar.gz.enc >/dev/null
validate_restored_db_and_artifacts {shlex.quote(str(restored_dir))} {shlex.quote(str(report_path))}
publish_recovery_receipt sha256:{'a' * 64} 0
validate_restored_api {shlex.quote(str(restored_dir))}
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MOCK_DOCKER_LOG": str(docker_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    all_invocations = [json.loads(line) for line in docker_log.read_text(encoding="utf-8").splitlines()]
    run_invocations = [invocation for invocation in all_invocations if invocation[0] == "run"]
    assert len(run_invocations) == 5
    for invocation in run_invocations:
        image_index = invocation.index(PINNED_IMAGE)
        assert invocation[image_index - 1] == "--"
    assert [run_invocations[0][index + 1] for index, arg in enumerate(run_invocations[0]) if arg == "--mount"] == [
        f"type=bind,src={data_dir},dst=/data-root,readonly",
        f"type=bind,src={receipt_dir},dst=/receipts",
    ]
    restore_mounts = [
        run_invocations[1][index + 1]
        for index, arg in enumerate(run_invocations[1])
        if arg == "--mount"
    ]
    assert restore_mounts[0] == f"type=bind,src={backup_dir},dst=/backups,readonly"
    assert len(restore_mounts) == 2
    assert restore_mounts[1].endswith(",dst=/drill")
    assert [run_invocations[2][index + 1] for index, arg in enumerate(run_invocations[2]) if arg == "--mount"] == [
        f"type=bind,src={restored_dir},dst=/data,readonly",
    ]
    assert [run_invocations[3][index + 1] for index, arg in enumerate(run_invocations[3]) if arg == "--mount"] == [
        f"type=bind,src={data_dir},dst=/data-root,readonly",
        f"type=bind,src={receipt_dir},dst=/receipts",
    ]
    assert [run_invocations[4][index + 1] for index, arg in enumerate(run_invocations[4]) if arg == "--mount"] == [
        f"type=bind,src={restored_dir},dst=/data",
    ]
    assert all("/preflight/" not in "\n".join(invocation) for invocation in run_invocations)


def test_restore_publication_failure_is_sanitized(tmp_path: Path) -> None:
    private_marker = "private-source-payload"
    data_dir = tmp_path / private_marker / "data"
    receipt_dir = data_dir / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nprintf 'Traceback: %s\\n' \"$*\" >&2\nexit 73\n", encoding="utf-8")
    fake_docker.chmod(0o755)
    command = f"""source {shlex.quote(str(RUNNER))}
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)}
RECOVERY_PRODUCER_VERSION=release-a
RESTORE_DATA_DIR={shlex.quote(str(data_dir))}
RECOVERY_RECEIPT_DIR={shlex.quote(str(receipt_dir))}
RESTORE_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$RESTORE_DATA_DIR")"
publish_recovery_receipt sha256:{'a' * 64} 7
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "novel-tnn production restore drill: recovery receipt publication failed\n"
    assert private_marker not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert "Traceback" not in result.stderr


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


def test_restore_validation_succeeds_before_publication_failure_and_preserves_previous_receipt(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    drill_root = tmp_path / "drills"
    production_root = tmp_path / "production"
    receipt_dir = production_root / "data" / "logs" / "runtime"
    backup_dir.mkdir()
    drill_root.mkdir(mode=0o700)
    receipt_dir.mkdir(parents=True)
    previous_receipt = b"previous-restore-receipt\n"
    receipt_path = receipt_dir / "restore-drill.receipt.json"
    receipt_path.write_bytes(previous_receipt)
    event_log = tmp_path / "events.log"
    production_env = tmp_path / "production.env"
    production_env.write_text("", encoding="utf-8")
    restored_dir = drill_root / "restore-drill-fixture" / "restored-20260725-120000"
    restored_dir.mkdir(parents=True)

    command = f"""source {shlex.quote(str(RUNNER))}
validate_config() {{ :; }}
verify_recovery_publisher_contract() {{ printf '%s\\n' preflight >>{shlex.quote(str(event_log))}; }}
select_archive() {{ printf '%s\\n' novel-pipeline-backup-20260725-120000.tar.gz.enc; }}
verify_backup_input() {{ printf '%s\\n' verify >>{shlex.quote(str(event_log))}; }}
restore_into_new_drill() {{
  printf '%s\\n' restore >>{shlex.quote(str(event_log))}
  printf '%s\\n' {shlex.quote(str(restored_dir))}
  printf '%s\\n' 1:2
}}
verify_drill_directory_identity() {{ :; }}
validate_restored_db_and_artifacts() {{
  printf '%s\\n' db >>{shlex.quote(str(event_log))}
  printf '%s\\n' '{{"artifact_paths_scanned": 0}}' >"$2"
}}
validate_restored_api() {{ printf '%s\\n' api >>{shlex.quote(str(event_log))}; }}
read_verified_checksum_hash() {{ printf '%064d\\n' 0; }}
publish_recovery_receipt() {{ printf '%s\\n' publish >>{shlex.quote(str(event_log))}; return 73; }}
docker() {{ :; }}
sha256sum() {{ :; }}
BACKUP_LOCAL_DIR={shlex.quote(str(backup_dir))} \
BACKUP_DRILL_ROOT={shlex.quote(str(drill_root))} \
BACKUP_IMAGE={shlex.quote(PINNED_IMAGE)} \
PRODUCTION_ENV={shlex.quote(str(production_env))} \
RESTORE_ARTIFACT_SOURCE_ROOT={shlex.quote(str(production_root))} \
RECOVERY_PRODUCER_VERSION=release-a \
main
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
    assert event_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "verify",
        "restore",
        "db",
        "api",
        "publish",
    ]
    assert restored_dir.is_dir()
    assert receipt_path.read_bytes() == previous_receipt
    assert not list(receipt_dir.glob(".restore-drill.receipt.json.*"))
    assert not list(receipt_dir.glob(".recovery-publisher-probe-*"))
    serialized = result.stdout + result.stderr
    assert str(tmp_path) not in serialized
    assert "PermissionError" not in serialized
    assert "Traceback" not in serialized


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


def test_restore_status_publisher_rejects_a_timestamp_beyond_allowed_clock_skew(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    from scripts.record_restore_drill_status import record_success

    status_path = tmp_path / "runtime" / "restore-drill.status.json"
    with pytest.raises(ValueError, match="completion timestamp exceeds allowed clock skew"):
        record_success(
            status_path,
            archive_hash_id="sha256:" + "a" * 64,
            validation_counts={"checksum_verified": 1},
            producer_version="release-a",
            completed_at=datetime(2999, 1, 1, tzinfo=timezone.utc),
        )

    assert not status_path.exists()
