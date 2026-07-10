#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/python.sh"
PYTHON_BIN="$(resolve_python_bin "$ROOT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-"$ROOT_DIR/backups"}"

if [[ "${INCLUDE_ENV:-0}" == "1" && "${ENCRYPT_BACKUP:-0}" != "1" ]]; then
  echo "INCLUDE_ENV=1 requires ENCRYPT_BACKUP=1 so secrets are never backed up in plaintext." >&2
  exit 2
fi

"$PYTHON_BIN" - "$ROOT_DIR" "$BACKUP_DIR" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
BACKUP_DIR = Path(sys.argv[2])
sys.path.insert(0, str(ROOT))

from scripts.ops import create_backup, encrypt_backup_archive, rotate_backup_files

data_dir = None
try:
    from app.config import settings

    data_dir = settings.resolved_data_dir
except Exception:
    data_dir = ROOT / "data"

include_env = os.getenv("INCLUDE_ENV", "0") == "1"
include_audio = os.getenv("BACKUP_INCLUDE_AUDIO", "1") != "0"
include_exports = os.getenv("BACKUP_INCLUDE_EXPORTS", "0") == "1"
include_job_logs = os.getenv("BACKUP_INCLUDE_JOB_LOGS", "0") == "1"
keep_raw = os.getenv("BACKUP_KEEP", "").strip()
keep = int(keep_raw) if keep_raw else None

backup_path = create_backup(
    data_dir=data_dir,
    out_dir=BACKUP_DIR,
    include_env=include_env,
    include_audio=include_audio,
    include_exports=include_exports,
    include_job_logs=include_job_logs,
)

if os.getenv("ENCRYPT_BACKUP", "0") == "1":
    passphrase = os.getenv("BACKUP_PASSPHRASE", "").strip()
    if not passphrase:
        raise SystemExit("BACKUP_PASSPHRASE is required when ENCRYPT_BACKUP=1")
    backup_path = encrypt_backup_archive(
        backup_path,
        passphrase=passphrase,
        iterations=int(os.getenv("OPENSSL_KDF_ITERATIONS", "200000")),
    )

if keep is not None:
    rotate_backup_files(BACKUP_DIR, keep=keep)

try:
    from app.database.db import record_operational_event

    db_path = data_dir / "pipeline.db"
    if db_path.exists():
        record_operational_event(
            db_path,
            event_type="backup_success",
            severity="info",
            source="backup-local",
            message="Backup completed",
            details={
                "backup_name": backup_path.name,
                "encrypted": backup_path.name.endswith(".enc"),
                "include_audio": include_audio,
                "include_exports": include_exports,
                "include_job_logs": include_job_logs,
                "include_secrets": include_env,
            },
        )
except Exception:
    pass

try:
    backup_path.chmod(0o600)
except OSError:
    pass

print(str(backup_path))
PY
