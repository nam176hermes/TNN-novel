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

The adjacent sidecar is a compact, versioned, backup-level summary used by normal API listing. The complete file-level manifest remains inside the archive for explicit validation and compatibility. Normal `GET /api/system/backups` reads sidecar/stat metadata only and never opens or decompresses an archive.

Backup creation uses a private `0700` staging directory inside the selected output directory. Files are collected and added to the archive in deterministic path order, with cooperative cancellation checks between bounded file operations. The completed archive is validated before publication. Each invocation atomically reserves a collision-resistant final basename, adding a short suffix only when the timestamped name is already reserved or present. The archive and compact sidecar then move into their established filename patterns with same-filesystem, no-clobber publication; staging and partial names are ignored by normal backup listing.

Cancellation or failure before archive publication leaves no final artifact or sidecar. For a non-secret backup, if archive publication succeeds but sidecar publication fails, the valid archive is preserved and appears as `METADATA_MISSING` so an operator can use the explicit metadata repair workflow.

Secrets-included API/background backups use a stricter flow. Plaintext archive bytes and their sidecar remain below a hidden mode-`0700` directory on the backup filesystem while encryption runs. Only the completed `.tar.gz.enc` and a matching READY sidecar are published into the live backup directory. Normal listing ignores private/partial names, and protected download rejects unsupported names, symlinks, and artifacts without valid matching sidecars. A failed encryption or normal publication failure therefore exposes neither plaintext nor a partial final encrypted artifact.

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

## Repair Legacy Sidecars

Legacy archives without metadata remain visible as `METADATA_MISSING`; malformed metadata is shown as `METADATA_INVALID`. Neither state triggers archive inspection from an API request.

Repair is an explicit operator workflow and defaults to dry-run. Rehearse against copied archives first:

```bash
REHEARSAL_DIR="$(mktemp -d /tmp/novel-tnn-backup-rehearsal-XXXXXX)"
cp --preserve=timestamps backups/SAFE_ARCHIVE_NAME.tar.gz "$REHEARSAL_DIR/"
sha256sum "$REHEARSAL_DIR"/*.tar.gz

.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "$REHEARSAL_DIR" \
  --all-missing \
  --dry-run

.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "$REHEARSAL_DIR" \
  --all-missing \
  --apply
```

Run apply a second time and require zero writes, re-check archive hashes, list the repaired copies, and run a representative restore drill. Only then apply to the configured operator backup directory:

```bash
.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "${BACKUP_DIR:-$REPO_ROOT/backups}" \
  --all-missing \
  --apply \
  --report-dir /tmp/novel-tnn-backup-metadata-report
```

The tool never rewrites the archive. Existing valid sidecars are preserved unless `--overwrite` is explicit. Encrypted archives require a passphrase from the named environment variable; never place the passphrase in command arguments or reports. See [`backup-metadata-sidecars.md`](backup-metadata-sidecars.md) for the schema and failure states.

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

`POST /api/system/backups` returns HTTP `202 Accepted` with a safe job payload:

```json
{"job_id":"...","status":"queued","message":"Backup queued"}
```

The request performs validation and scheduling only. The frontend follows the
existing authenticated job-status stream, shows queued/running progress, and
reloads the metadata-only backup list only after the job reaches `completed`.
Cancel uses the normal authenticated job-cancel route. A failed, cancelled, or
interrupted backup remains entry-specific and does not block system status or
listing other backups.

Retry always means queueing a new backup request. Plain backups may be queued
again with the same options. Encrypted or secrets-included backups require the
operator to enter the passphrase again; do not use the translation-job retry
route. Backup names are reserved without overwrite, so a retry cannot replace
an existing completed archive.

The passphrase exists only in process memory, is taken once by the worker, and
is discarded after the worker finishes. It is never part of persisted job
parameters. A process restart deliberately loses it, so an interrupted
encrypted backup cannot resume and must be submitted again.

Publication remains same-filesystem and staged. Plain/non-secret creation
validates the archive, publishes it with no-clobber semantics, then publishes
the sidecar; a sidecar failure preserves the valid archive for explicit
dry-run-first metadata repair. Secrets-included background creation instead
builds and encrypts entirely below private mode-`0700` staging, validates READY
metadata, then publishes the sidecar before the completed encrypted artifact.
An owned hidden reservation suppresses sidecar-only process-crash residue.
Normal exceptions record each final hardlink immediately and roll back every
owned link if any later source cleanup or publication step fails.

## P2C rollback boundaries

P2C was delivered as narrow commits so an operator can revert the failing seam
without changing archive/restore format:

- backup API/jobs: `b77fa38` through `04ad491`, plus terminal-audit commits
  `9d04ffe`/`de94de7` and encrypt-before-publish commits
  `3f3b83d`/`a4eac8c`;
- retention and repository foundations: `38156ce` through `56534d9`;
- Reader feature ownership: `31093ba` through `987aea0`;
- CSS layers/features: `46759eb` through `2a77755`;
- Reader database/content services: `6c2ba0a` and `9f47a41`.

Use `git revert <commit>` from newest affected commit backward. Never delete
published archives during rollback. Before deploying a rollback, stop the app,
create and verify a fresh backup through the established operator workflow,
then run the focused tests for that seam. Database schema and restore format did
not change in P2C, so no data downgrade or restore-format conversion is needed.
