# Backup and Restore

System backup is separate from Book Export. Use book export for reader-facing EPUB/TXT/DOCX/audio files. Use system backup for operational recovery.

The configured data tree defaults to `$REPO_ROOT/data`. Backups default to `$REPO_ROOT/backups` unless `BACKUP_DIR` or `--out-dir` is set. Resolve these variables before running operator commands:

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export DATA_DIR="${DATA_DIR:-$REPO_ROOT/data}"
cd "$REPO_ROOT"
```

## Create a Backup

Plain local backup:

```bash
cd "$REPO_ROOT"
scripts/backup-local.sh
```

Keep only the newest local backups:

```bash
cd "$REPO_ROOT"
BACKUP_KEEP=14 scripts/backup-local.sh
```

The archive contains `data/` plus a consistent SQLite copy of `data/pipeline.db`.

Default system backup behavior:

- includes database
- includes raw/cleaned/translated content
- includes covers and book assets
- includes glossary/QA/job/source/settings metadata stored in SQLite
- includes audio by default
- excludes generated exports by default
- excludes secrets by default
- excludes plaintext `.env` by default

Every backup now includes:

- `manifest.json` inside the archive
- a sidecar manifest file next to the archive:
  - `novel-pipeline-backup-...tar.gz.manifest.json`
  - `novel-pipeline-backup-...tar.gz.enc.manifest.json`

The manifest records:

- app name
- backup format version
- created time
- included modules
- excluded modules
- file count
- total size
- database filename metadata
- whether secrets are included
- whether the backup is encrypted

`.env` is never included by default. Do not include it in routine backups because it can contain credentials.

## Optional Encrypted Backup

Use encryption for private backups that include secrets or leave the machine:

```bash
cd "$REPO_ROOT"
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 scripts/backup-local.sh
```

Encrypted backups can use the same retention policy:

```bash
cd "$REPO_ROOT"
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 BACKUP_KEEP=14 scripts/backup-local.sh
```

To include `.env`, use encryption and opt in explicitly:

```bash
cd "$REPO_ROOT"
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 INCLUDE_ENV=1 scripts/backup-local.sh
```

Encrypted backups use local `openssl enc -aes-256-cbc -salt -pbkdf2`. The passphrase is required from the environment and is not stored by the script.

`INCLUDE_ENV=1` without `ENCRYPT_BACKUP=1` is intentionally rejected.

Optional module selection:

```bash
BACKUP_INCLUDE_AUDIO=0 BACKUP_INCLUDE_EXPORTS=1 BACKUP_INCLUDE_JOB_LOGS=1 scripts/backup-local.sh
```

Recommended defaults for a private production app:

- keep audio in backup if audiobook regeneration is expensive
- keep exports out of routine backup unless they are operationally important
- keep logs out of routine backup unless you are preserving a debugging snapshot

## Restore Drill

Run a restore drill regularly. It unpacks or decrypts a backup into a separate drill directory, verifies SQLite integrity, and opens the restored database. It does not overwrite live `data/`.

Plain backup drill:

```bash
cd "$REPO_ROOT"
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz
```

Encrypted backup drill:

```bash
cd "$REPO_ROOT"
BACKUP_PASSPHRASE='use-a-long-passphrase' \
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.enc
```

Use `--work-dir /path/to/drill-dir` if you want the restored drill files in a known location for inspection.

The restore drill is the preferred integrity check. It does not overwrite live `data/`.

Schedule recommendation for serious personal use:

```text
Daily:    BACKUP_KEEP=14 scripts/backup-local.sh
Weekly:   BACKUP_PASSPHRASE=... ENCRYPT_BACKUP=1 BACKUP_KEEP=8 scripts/backup-local.sh
Monthly:  restore-drill the newest plain and encrypted backup
```

## Restore Safely

Stop the server before replacing `data/`:

```bash
cd "$REPO_ROOT"
scripts/stop-local.sh
```

For systemd:

```bash
sudo systemctl stop novel-pipeline
```

For Docker Compose:

```bash
docker compose stop
```

If the backup is encrypted, decrypt it to a temporary tarball first:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' \
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.enc \
  -out /tmp/novel-pipeline-restore.tar.gz \
  -pass env:BACKUP_PASSPHRASE
```

Restore into a staging directory first:

```bash
.venv/bin/python scripts/ops.py restore /tmp/novel-pipeline-restore.tar.gz --target-dir data_restored
```

For a plain backup, pass the `.tar.gz` path directly:

```bash
.venv/bin/python scripts/ops.py restore backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz --target-dir data_restored
```

Replace active data only after the staged restore succeeds:

```bash
mv data "data.before-restore.$(date +%Y%m%d-%H%M%S)"
mv data_restored data
```

Start the server again:

```bash
scripts/start-local.sh
```

## Verify After Restore

Run:

```bash
.venv/bin/python - <<'PY'
from app.config import settings
from scripts.ops import sqlite_integrity_ok

ok = sqlite_integrity_ok(settings.db_path)
print("SQLite integrity:", "ok" if ok else "failed")
raise SystemExit(0 if ok else 1)
PY
scripts/status-local.sh
scripts/smoke-local.sh
```

Then open the app and confirm the Library, Reader, Trạng thái page, covers, and book assets load.

## Web API backup flow

Authenticated operators can also create and download system backups from the app through protected routes:

- `GET /api/system/backups`
- `POST /api/system/backups`
- `GET /api/system/backups/{filename}/download`

These routes:

- require authentication
- validate filenames
- block path traversal
- never expose raw absolute filesystem paths
- exclude secrets by default
- require an encryption passphrase when secrets are included
