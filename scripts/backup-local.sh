#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-"$ROOT_DIR/backups"}"
PYTHON_BIN="${PYTHON_BIN:-"$ROOT_DIR/.venv/bin/python"}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_NAME="${BACKUP_NAME:-"novel-pipeline-backup-$TIMESTAMP.tar.gz"}"
OUTPUT_PATH="$BACKUP_DIR/$BACKUP_NAME"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

mkdir -p "$BACKUP_DIR"
TMP_DIR="$(mktemp -d)"
cleanup() {
  local status=$?
  if [[ $status -ne 0 && -n "${DB_PATH:-}" && -f "${DB_PATH:-}" ]]; then
    "$PYTHON_BIN" - "$DB_PATH" <<'PY' || true
from pathlib import Path
import sys

db_path = Path(sys.argv[1])
if db_path.exists():
    from app.database.db import record_operational_event

    record_operational_event(
        db_path,
        event_type="backup_failure",
        severity="error",
        source="backup-local",
        message="Backup failed. Check server logs.",
    )
PY
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

readarray -t PATHS < <("$PYTHON_BIN" - <<'PY'
from app.config import PROJECT_ROOT, settings

print(PROJECT_ROOT)
print(settings.resolved_data_dir)
print(settings.db_path)
PY
)

PROJECT_ROOT="${PATHS[0]}"
DATA_DIR="${PATHS[1]}"
DB_PATH="${PATHS[2]}"
DATA_PARENT="$(dirname "$DATA_DIR")"
DATA_BASENAME="$(basename "$DATA_DIR")"

if [[ -d "$DATA_DIR" ]]; then
  mkdir -p "$TMP_DIR/data"
  tar \
    --exclude="$DATA_BASENAME/pipeline.db" \
    --exclude="$DATA_BASENAME/pipeline.db-wal" \
    --exclude="$DATA_BASENAME/pipeline.db-shm" \
    --exclude="$DATA_BASENAME/logs/runtime/*.pid" \
    --exclude="$DATA_BASENAME/logs/runtime/*.log.*" \
    --transform "s|^$DATA_BASENAME|data|" \
    -C "$DATA_PARENT" \
    -cf - "$DATA_BASENAME" | tar -C "$TMP_DIR" -xf -
fi

if [[ -f "$DB_PATH" ]]; then
  "$PYTHON_BIN" - "$DB_PATH" "$TMP_DIR/data/pipeline.db" <<'PY'
from pathlib import Path
import sqlite3
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
    src.backup(dst)
PY
fi

TAR_ARGS=()

pushd "$PROJECT_ROOT" >/dev/null
if [[ -d "$TMP_DIR/data" ]]; then
  TAR_ARGS+=("-C" "$TMP_DIR" "data")
fi
if [[ "${INCLUDE_ENV:-0}" == "1" && -f ".env" ]]; then
  TAR_ARGS+=("-C" "$PROJECT_ROOT" ".env")
fi
if [[ "${#TAR_ARGS[@]}" -eq 0 ]]; then
  echo "Nothing to back up: data directory is missing and INCLUDE_ENV is not set" >&2
  exit 2
fi
tar -czf "$OUTPUT_PATH" "${TAR_ARGS[@]}"
popd >/dev/null

if [[ "${ENCRYPT_BACKUP:-0}" == "1" ]]; then
  if [[ -z "${BACKUP_PASSPHRASE:-}" ]]; then
    echo "BACKUP_PASSPHRASE is required when ENCRYPT_BACKUP=1" >&2
    exit 2
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required when ENCRYPT_BACKUP=1" >&2
    exit 2
  fi

  ENCRYPTED_OUTPUT_PATH="${OUTPUT_PATH}.enc"
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter "${OPENSSL_KDF_ITERATIONS:-200000}" \
    -in "$OUTPUT_PATH" \
    -out "$ENCRYPTED_OUTPUT_PATH" \
    -pass env:BACKUP_PASSPHRASE
  rm -f "$OUTPUT_PATH"
  chmod 600 "$ENCRYPTED_OUTPUT_PATH"
  if [[ -n "${BACKUP_KEEP:-}" ]]; then
    "$PYTHON_BIN" - "$BACKUP_DIR" "$BACKUP_KEEP" <<'PY'
from pathlib import Path
import sys
from scripts.ops import rotate_backup_files

rotate_backup_files(Path(sys.argv[1]), keep=int(sys.argv[2]))
PY
  fi
  "$PYTHON_BIN" - "$DB_PATH" "$(basename "$ENCRYPTED_OUTPUT_PATH")" <<'PY' || true
from pathlib import Path
import sys

db_path = Path(sys.argv[1])
if db_path.exists():
    from app.database.db import record_operational_event

    record_operational_event(
        db_path,
        event_type="backup_success",
        severity="info",
        source="backup-local",
        message="Backup completed",
        details={"backup_name": sys.argv[2], "encrypted": True},
    )
PY
  echo "$ENCRYPTED_OUTPUT_PATH"
else
  chmod 600 "$OUTPUT_PATH"
  if [[ -n "${BACKUP_KEEP:-}" ]]; then
    "$PYTHON_BIN" - "$BACKUP_DIR" "$BACKUP_KEEP" <<'PY'
from pathlib import Path
import sys
from scripts.ops import rotate_backup_files

rotate_backup_files(Path(sys.argv[1]), keep=int(sys.argv[2]))
PY
  fi
  "$PYTHON_BIN" - "$DB_PATH" "$(basename "$OUTPUT_PATH")" <<'PY' || true
from pathlib import Path
import sys

db_path = Path(sys.argv[1])
if db_path.exists():
    from app.database.db import record_operational_event

    record_operational_event(
        db_path,
        event_type="backup_success",
        severity="info",
        source="backup-local",
        message="Backup completed",
        details={"backup_name": sys.argv[2], "encrypted": False},
    )
PY
  echo "$OUTPUT_PATH"
fi
