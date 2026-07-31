#!/usr/bin/env bash
set -euo pipefail

# Restore only into a new isolated drill directory. This script deliberately
# never removes drill data; remove it only under a separate operator approval.

readonly RUNNER_NAME="novel-tnn production restore drill"
readonly BACKUP_NAME_PATTERN='^novel-pipeline-backup-[0-9]{8}-[0-9]{6}(-[A-Za-z0-9._-]+)?(-[a-f0-9]{12})?\.tar\.gz\.enc$'

fail() {
  printf '%s: %s\n' "$RUNNER_NAME" "$*" >&2
  exit 2
}

require_value() {
  local variable_name="$1"
  [[ -n "${!variable_name:-}" ]] || fail "${variable_name} is required"
}

require_absolute_path() {
  local variable_name="$1"
  [[ "${!variable_name:-}" == /* ]] || fail "${variable_name} must be an absolute path"
}

validate_config() {
  require_value BACKUP_PASSPHRASE
  require_value BACKUP_IMAGE
  require_value BACKUP_LOCAL_DIR
  require_value BACKUP_DRILL_ROOT
  require_value PRODUCTION_ENV
  require_value RESTORE_ARTIFACT_SOURCE_ROOT
  require_value RESTORE_DATA_DIR
  require_value RECOVERY_PRODUCER_VERSION
  require_value RECOVERY_RECEIPT_DIR
  require_absolute_path BACKUP_LOCAL_DIR
  require_absolute_path BACKUP_DRILL_ROOT
  require_absolute_path PRODUCTION_ENV
  require_absolute_path RESTORE_ARTIFACT_SOURCE_ROOT
  require_absolute_path RESTORE_DATA_DIR
  require_absolute_path RECOVERY_RECEIPT_DIR
  [[ -d "$BACKUP_LOCAL_DIR" ]] || fail "BACKUP_LOCAL_DIR does not exist"
  [[ -d "$RESTORE_DATA_DIR" ]] || fail "RESTORE_DATA_DIR does not exist"
  [[ "$BACKUP_IMAGE" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] \
    || fail "BACKUP_IMAGE must be pinned by sha256 digest"
  [[ "$RECOVERY_PRODUCER_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]] \
    || fail "RECOVERY_PRODUCER_VERSION must be a safe release identifier"

  local data_root receipt_root
  data_root="$(realpath -m -- "$RESTORE_DATA_DIR")"
  receipt_root="$(realpath -m -- "$RECOVERY_RECEIPT_DIR")"
  [[ "$receipt_root" == "$data_root/logs/runtime" ]] \
    || fail "RECOVERY_RECEIPT_DIR must be the fixed data/logs/runtime directory"
}

verify_publisher_image_release() {
  local image_release
  image_release="$(
    docker run --rm --network none "$BACKUP_IMAGE" \
      python -c 'import os; import scripts.record_restore_drill_status; print(os.environ.get("NOVEL_RELEASE_ID", ""))'
  )"
  [[ "$image_release" == "$RECOVERY_PRODUCER_VERSION" ]] \
    || fail "BACKUP_IMAGE release does not match RECOVERY_PRODUCER_VERSION"
}

verify_publisher_authority() {
  docker run --rm --network none --user 10001:10001 \
    --mount "type=bind,src=${RECOVERY_RECEIPT_DIR},dst=/receipts" \
    "$BACKUP_IMAGE" \
    python -c '
# publisher-authority-preflight
import os
import stat

target = "/receipts"
metadata = os.stat(target, follow_symlinks=False)
if not stat.S_ISDIR(metadata.st_mode):
    raise SystemExit("receipt publisher target is not a directory")
if (metadata.st_uid, metadata.st_gid) != (10001, 10001):
    raise SystemExit("receipt publisher target owner is invalid")
if stat.S_IMODE(metadata.st_mode) != 0o700:
    raise SystemExit("receipt publisher target mode is invalid")
if not os.access(target, os.W_OK | os.X_OK):
    raise SystemExit("receipt publisher lacks directory authority")
'
}

select_archive() {
  local requested_name="${1:-}"
  if [[ -n "$requested_name" ]]; then
    [[ "$requested_name" == "$(basename "$requested_name")" ]] || fail "archive must be a basename"
    [[ "$requested_name" =~ $BACKUP_NAME_PATTERN ]] || fail "archive name is not a supported encrypted backup"
    printf '%s\n' "$requested_name"
    return 0
  fi

  local newest
  newest="$(find "$BACKUP_LOCAL_DIR" -maxdepth 1 -type f -name 'novel-pipeline-backup-*.tar.gz.enc' -printf '%T@ %f\n' \
    | sort -nr | head -n 1 | cut -d' ' -f2-)"
  [[ -n "$newest" && "$newest" =~ $BACKUP_NAME_PATTERN ]] || fail "no encrypted backup archive is available"
  printf '%s\n' "$newest"
}

read_verified_checksum_hash() {
  local archive_name="$1"
  .venv/bin/python - "${BACKUP_LOCAL_DIR}/${archive_name}.sha256" "$archive_name" <<'PY'
from pathlib import Path
import re
import sys

raw = Path(sys.argv[1]).read_text(encoding="ascii")
match = re.fullmatch(r"([a-f0-9]{64})  ([^\r\n]+)\n", raw)
if match is None or match.group(2) != sys.argv[2]:
    raise SystemExit("checksum file must contain exactly the selected archive")
print(match.group(1))
PY
}

verify_backup_input() {
  local archive_name="$1"
  local archive_path="${BACKUP_LOCAL_DIR}/${archive_name}"
  local sidecar_path="${archive_path}.manifest.json"
  local checksum_path="${archive_path}.sha256"
  [[ -f "$archive_path" && ! -L "$archive_path" ]] || fail "backup archive is unavailable"
  [[ -f "$sidecar_path" && ! -L "$sidecar_path" ]] || fail "backup sidecar is unavailable"
  [[ -f "$checksum_path" && ! -L "$checksum_path" ]] || fail "backup checksum is unavailable"
  (
    cd "$BACKUP_LOCAL_DIR"
    sha256sum --check --status "${archive_name}.sha256"
  ) || fail "backup checksum does not match archive"
  read_verified_checksum_hash "$archive_name" >/dev/null \
    || fail "backup checksum metadata does not identify the selected archive"

  .venv/bin/python - "$archive_path" <<'PY'
from pathlib import Path
import sys

from scripts.ops import read_backup_sidecar

archive = Path(sys.argv[1])
metadata = read_backup_sidecar(archive)
if metadata.get("artifact_state") != "READY" or not metadata.get("encrypted"):
    raise SystemExit("backup metadata is not encrypted READY state")
if metadata.get("backup_filename") != archive.name:
    raise SystemExit("backup metadata filename does not match archive")
PY
}

restore_into_new_drill() {
  local archive_name="$1"
  install -d -m 0700 "$BACKUP_DRILL_ROOT"
  local drill_dir
  drill_dir="$(mktemp -d "${BACKUP_DRILL_ROOT}/restore-drill-$(date +%Y%m%dT%H%M%SZ)-XXXXXX")"
  # Let the production-image service user traverse this one random drill path
  # without exposing a directory listing to other host users.
  chmod 0711 "$drill_dir"

  local restored_name
  restored_name="$(
    docker run --rm --network none --user 0:0 \
      --mount "type=bind,src=${BACKUP_LOCAL_DIR},dst=/backups,readonly" \
      --mount "type=bind,src=${drill_dir},dst=/drill" \
      --env BACKUP_PASSPHRASE \
      --env "BACKUP_ARCHIVE_NAME=${archive_name}" \
      --env "RESTORE_OWNER_UID=10001" \
      --env "RESTORE_OWNER_GID=10001" \
      "$BACKUP_IMAGE" \
      python -c '
import json
import os
from pathlib import Path
from scripts.ops import restore_drill

drill_root = Path("/drill")
result = restore_drill(
    Path("/backups") / os.environ["BACKUP_ARCHIVE_NAME"],
    work_dir=drill_root,
    passphrase=os.environ["BACKUP_PASSPHRASE"],
)
restored = Path(result["restored_dir"])
for current in [drill_root, *drill_root.rglob("*")]:
    os.chown(current, int(os.environ["RESTORE_OWNER_UID"]), int(os.environ["RESTORE_OWNER_GID"]))
Path("/drill/restore-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
os.chown("/drill/restore-result.json", int(os.environ["RESTORE_OWNER_UID"]), int(os.environ["RESTORE_OWNER_GID"]))
print(restored.name)
'
  )"
  [[ "$restored_name" =~ ^restored-[0-9]{8}-[0-9]{6}$ ]] || fail "restore returned an unexpected directory name"
  printf '%s\n' "${drill_dir}/${restored_name}"
}

validate_restored_db_and_artifacts() {
  local restored_dir="$1"
  local report_path="$2"
  docker run --rm --network none --user 0:0 -i \
    --mount "type=bind,src=${restored_dir},dst=/data,readonly" \
    --env "RESTORE_ARTIFACT_SOURCE_ROOT=${RESTORE_ARTIFACT_SOURCE_ROOT}" \
    "$BACKUP_IMAGE" \
    python - <<'PY' >"$report_path"
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from app.storage.artifact_paths import APPROVED_PATH_FIELDS, require_artifact_file

data_root = Path("/data")
db_path = data_root / "pipeline.db"
conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
try:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_key_count:
        raise SystemExit("restored database integrity validation failed")
    available_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    scanned = 0
    errors: list[dict[str, object]] = []
    for field in APPROVED_PATH_FIELDS:
        if field.table not in available_tables:
            continue
        query = (
            f"SELECT {field.primary_key}, {field.column} FROM {field.table} "
            f"WHERE COALESCE({field.column}, '') != '' AND ({field.active_where})"
        )
        for row_id, value in conn.execute(query):
            scanned += 1
            try:
                require_artifact_file(
                    value,
                    artifact_class=field.artifact_class,
                    data_root=data_root,
                    old_root=Path(os.environ["RESTORE_ARTIFACT_SOURCE_ROOT"]),
                )
            except Exception as exc:
                errors.append({"table": field.table, "id": int(row_id), "field": field.column, "error": str(exc)})
    if errors:
        raise SystemExit(json.dumps({"artifact_errors": errors[:20], "artifact_error_count": len(errors)}))
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("books", "chapters")
        if table in available_tables
    }
finally:
    conn.close()

print(json.dumps({
    "integrity_check": "ok",
    "foreign_key_check_count": 0,
    "artifact_paths_scanned": scanned,
    "table_counts": counts,
}, sort_keys=True))
PY
  chmod 0600 "$report_path"
}

publish_recovery_receipt() {
  local archive_hash_id="$1"
  local artifact_paths_scanned="$2"
  docker run --rm --network none --user 10001:10001 \
    --mount "type=bind,src=${RECOVERY_RECEIPT_DIR},dst=/receipts" \
    "$BACKUP_IMAGE" \
    python -m scripts.record_restore_drill_status \
    --output /receipts/restore-drill.receipt.json \
    --archive-hash-id "$archive_hash_id" \
    --producer-version "$RECOVERY_PRODUCER_VERSION" \
    --validation-count checksum_verified=1 \
    --validation-count sqlite_integrity_checks=1 \
    --validation-count foreign_key_violations=0 \
    --validation-count "artifact_paths_scanned=${artifact_paths_scanned}" \
    --validation-count api_readiness_checks=1 \
    --validation-count authenticated_reader_smokes=1
}

validate_restored_api() {
  local restored_dir="$1"
  local container_name="novel-tnn-restore-drill-$(date +%s)-$$"
  docker run --detach --rm --name "$container_name" --network none \
    --env-file "$PRODUCTION_ENV" \
    --env DATA_DIR=/data \
    --env MOBILE_API_PORT=7860 \
    --env "ARTIFACT_LEGACY_ROOT=${RESTORE_ARTIFACT_SOURCE_ROOT}" \
    --mount "type=bind,src=${restored_dir},dst=/data" \
    "$BACKUP_IMAGE" >/dev/null
  trap 'docker rm -f "${container_name:-}" >/dev/null 2>&1 || true' EXIT

  local attempt readiness_succeeded=0
  for attempt in $(seq 1 40); do
    if docker exec "$container_name" curl --fail --silent --show-error http://127.0.0.1:7860/api/health >/dev/null 2>&1 \
      && docker exec "$container_name" curl --fail --silent --show-error http://127.0.0.1:7860/api/ready >/dev/null 2>&1; then
      readiness_succeeded=1
      break
    fi
    sleep 1
  done
  ((readiness_succeeded == 1)) || fail "restored API did not become healthy and ready"

  docker exec "$container_name" sh -ec '
password_file=$(mktemp)
trap "rm -f \"$password_file\"" EXIT
umask 077
printf "%s" "$MOBILE_API_ADMIN_PASSWORD" >"$password_file"
python scripts/smoke_reader_authenticated.py \
  --base-url http://127.0.0.1:7860 \
  --username "$MOBILE_API_ADMIN_USERNAME" \
  --password-file "$password_file"
'
  docker rm -f "$container_name" >/dev/null
  trap - EXIT
}

main() {
  BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-$HOME/.local/share/novel-tnn-backups}"
  BACKUP_DRILL_ROOT="${BACKUP_DRILL_ROOT:-$HOME/Novel-TNN-restore-drills}"
  BACKUP_IMAGE="${BACKUP_IMAGE:-novel-pipeline-api:runtime-hardening-20260718-r1}"
  PRODUCTION_ENV="${PRODUCTION_ENV:-$HOME/.config/novel-tnn/production.env}"
  RESTORE_ARTIFACT_SOURCE_ROOT="${RESTORE_ARTIFACT_SOURCE_ROOT:-$HOME/Novel-TNN}"
  RESTORE_DATA_DIR="${RESTORE_ARTIFACT_SOURCE_ROOT}/data"
  RECOVERY_PRODUCER_VERSION="${RECOVERY_PRODUCER_VERSION:-}"
  RECOVERY_RECEIPT_DIR="${RESTORE_DATA_DIR}/logs/runtime"

  validate_config
  if [[ "${1:-}" == "--validate-config" ]]; then
    printf 'restore drill configuration validated\n'
    return 0
  fi
  [[ $# -le 1 ]] || fail "usage: $0 [archive-basename]"
  [[ -f "$PRODUCTION_ENV" ]] || fail "PRODUCTION_ENV does not exist"
  command -v docker >/dev/null || fail "docker is required"
  command -v sha256sum >/dev/null || fail "sha256sum is required"
  verify_publisher_image_release
  verify_publisher_authority

  umask 077
  local archive_name restored_dir report_path
  archive_name="$(select_archive "${1:-}")"
  verify_backup_input "$archive_name"
  restored_dir="$(restore_into_new_drill "$archive_name")"
  report_path="${BACKUP_DRILL_ROOT}/$(basename "$(dirname "$restored_dir")")-validation.json"
  validate_restored_db_and_artifacts "$restored_dir" "$report_path"
  validate_restored_api "$restored_dir"
  local checksum_hash artifact_paths_scanned
  checksum_hash="$(read_verified_checksum_hash "$archive_name")"
  [[ "$checksum_hash" =~ ^[a-f0-9]{64}$ ]] || fail "verified checksum is not a SHA-256 identifier"
  artifact_paths_scanned="$(.venv/bin/python -c 'import json,sys; print(int(json.load(open(sys.argv[1], encoding="utf-8"))["artifact_paths_scanned"]))' "$report_path")"
  publish_recovery_receipt "sha256:${checksum_hash}" "$artifact_paths_scanned"
  printf 'restore drill complete: %s\n' "$restored_dir"
  printf 'validation report: %s\n' "$report_path"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
