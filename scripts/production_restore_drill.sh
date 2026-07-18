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
  require_absolute_path BACKUP_LOCAL_DIR
  require_absolute_path BACKUP_DRILL_ROOT
  require_absolute_path PRODUCTION_ENV
  require_absolute_path RESTORE_ARTIFACT_SOURCE_ROOT
  [[ -d "$BACKUP_LOCAL_DIR" ]] || fail "BACKUP_LOCAL_DIR does not exist"
  [[ "$BACKUP_IMAGE" != *[[:space:]]* ]] || fail "BACKUP_IMAGE must not contain whitespace"
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

  local attempt
  for attempt in $(seq 1 40); do
    if docker exec "$container_name" curl --fail --silent --show-error http://127.0.0.1:7860/api/health >/dev/null 2>&1 \
      && docker exec "$container_name" curl --fail --silent --show-error http://127.0.0.1:7860/api/ready >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  ((attempt <= 40)) || fail "restored API did not become healthy and ready"

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

  validate_config
  if [[ "${1:-}" == "--validate-config" ]]; then
    printf 'restore drill configuration validated\n'
    return 0
  fi
  [[ $# -le 1 ]] || fail "usage: $0 [archive-basename]"
  [[ -f "$PRODUCTION_ENV" ]] || fail "PRODUCTION_ENV does not exist"
  command -v docker >/dev/null || fail "docker is required"
  command -v sha256sum >/dev/null || fail "sha256sum is required"

  umask 077
  local archive_name restored_dir report_path
  archive_name="$(select_archive "${1:-}")"
  verify_backup_input "$archive_name"
  restored_dir="$(restore_into_new_drill "$archive_name")"
  report_path="${BACKUP_DRILL_ROOT}/$(basename "$(dirname "$restored_dir")")-validation.json"
  validate_restored_db_and_artifacts "$restored_dir" "$report_path"
  validate_restored_api "$restored_dir"
  printf 'restore drill complete: %s\n' "$restored_dir"
  printf 'validation report: %s\n' "$report_path"
}

main "$@"
