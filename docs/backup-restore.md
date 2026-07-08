# Backup and Restore

This app stores personal data under `/home/thenam176/novel_pipeline/data` by default. Backups are written to `/home/thenam176/novel_pipeline/backups` unless `BACKUP_DIR` or `--out-dir` is set.

## Create a Backup

Plain local backup:

```bash
cd /home/thenam176/novel_pipeline
scripts/backup-local.sh
```

Keep only the newest local backups:

```bash
cd /home/thenam176/novel_pipeline
BACKUP_KEEP=14 scripts/backup-local.sh
```

The archive contains `data/` plus a consistent SQLite copy of `data/pipeline.db`. It includes raw, cleaned, translated, cover, asset, audio, export, dictionary, glossary, style, provider, reader, and job metadata stored in `data/`.

`.env` is never included by default. Do not include it in routine backups because it can contain credentials.

## Optional Encrypted Backup

Use encryption for private backups that include secrets or leave the machine:

```bash
cd /home/thenam176/novel_pipeline
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 scripts/backup-local.sh
```

Encrypted backups can use the same retention policy:

```bash
cd /home/thenam176/novel_pipeline
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 BACKUP_KEEP=14 scripts/backup-local.sh
```

To include `.env`, use encryption and opt in explicitly:

```bash
cd /home/thenam176/novel_pipeline
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 INCLUDE_ENV=1 scripts/backup-local.sh
```

Encrypted backups use local `openssl enc -aes-256-cbc -salt -pbkdf2`. The passphrase is required from the environment and is not stored by the script.

## Restore Drill

Run a restore drill regularly. It unpacks or decrypts a backup into a separate drill directory, verifies SQLite integrity, and opens the restored database. It does not overwrite live `data/`.

Plain backup drill:

```bash
cd /home/thenam176/novel_pipeline
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz
```

Encrypted backup drill:

```bash
cd /home/thenam176/novel_pipeline
BACKUP_PASSPHRASE='use-a-long-passphrase' \
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.enc
```

Use `--work-dir /path/to/drill-dir` if you want the restored drill files in a known location for inspection.

Schedule recommendation for serious personal use:

```text
Daily:    BACKUP_KEEP=14 scripts/backup-local.sh
Weekly:   BACKUP_PASSPHRASE=... ENCRYPT_BACKUP=1 BACKUP_KEEP=8 scripts/backup-local.sh
Monthly:  restore-drill the newest plain and encrypted backup
```

## Restore Safely

Stop the server before replacing `data/`:

```bash
cd /home/thenam176/novel_pipeline
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
