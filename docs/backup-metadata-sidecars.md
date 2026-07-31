# Backup Metadata Sidecars

`GET /api/system/backups` is a metadata-only operation. It enumerates the configured backup directory, reads bounded adjacent sidecar JSON, and uses filesystem stat metadata. It never opens, decompresses, decrypts, checksums, or walks a backup archive.

## Sidecar contract

The sidecar filename is the archive filename plus `.manifest.json`, for example:

```text
novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.manifest.json
novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.enc.manifest.json
```

New sidecars use schema version `1` and contain only backup-level metadata:

- backup filename and format version;
- created time and archive size;
- encrypted and secrets-included flags;
- included and excluded module identifiers;
- file count and source byte count;
- application version when available;
- artifact state;
- archive checksum only when an explicit workflow already calculated it.

Sidecars never contain passphrases, provider keys, environment contents, command lines, absolute paths, archive member names, file-level checksums, or private content. Legacy full sidecars remain readable, but the list path allowlists and returns only the safe summary above. Sidecar input is bounded to 8 MiB and malformed values are isolated to their own entry.

Sidecars are written to a protected temporary file in the backup directory, flushed, and atomically published with `os.replace` only after the archive is a supported regular non-empty file. A failed publication removes the temporary file. Repair never changes archive bytes.

## Listing states

Every recognized backup entry has one safe state:

- `READY`: archive and sidecar are available and the sidecar is valid;
- `METADATA_MISSING`: archive exists without a sidecar;
- `METADATA_INVALID`: sidecar is malformed, oversized, unreadable, or unsafe;
- `ARTIFACT_MISSING`: sidecar exists without its archive;
- `ARTIFACT_INVALID`: archive is empty, unreadable, not a regular file, or an unsafe symlink;
- `UNSUPPORTED_FORMAT`: backup-like filename uses an unsupported extension.

Only `READY` entries receive a download URL in the list response. One bad entry does not block the rest of the list. The response contains fixed safe warnings rather than raw exceptions or host paths.

## Explicit legacy repair

Archive inspection is an operator maintenance action and is never invoked by the list API. The repair command defaults to dry-run:

```bash
cd "$REPO_ROOT"
.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "${BACKUP_DIR:-$REPO_ROOT/backups}" \
  --all-missing \
  --dry-run
```

After copying the selected archives to an isolated rehearsal directory, recording their hashes, applying repair to the copies, verifying a second apply writes zero sidecars, and running a restore drill, apply to the operator directory explicitly:

```bash
.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "${BACKUP_DIR:-$REPO_ROOT/backups}" \
  --all-missing \
  --apply \
  --report-dir /tmp/novel-tnn-backup-metadata-report
```

Use `--filename SAFE_ARCHIVE_NAME` to select one archive. A valid existing sidecar is never replaced unless `--overwrite` is also supplied.

Manifestless legacy plain archives are accepted only after the explicit inspector verifies the gzip/tar structure, rejects traversal and link members, confirms a `data/` payload, and derives minimal metadata from archive members and stat data. It does not infer private content. Corrupt or unsafe archives remain unrepaired.

Encrypted archives without sidecars require a passphrase supplied through an environment variable. Never place a passphrase directly in shell history:

```bash
read -rs BACKUP_PASSPHRASE
export BACKUP_PASSPHRASE
.venv/bin/python scripts/ops.py backup-metadata-repair \
  --backup-dir "$BACKUP_DIR" \
  --filename SAFE_ARCHIVE_NAME.tar.gz.enc \
  --passphrase-env BACKUP_PASSPHRASE \
  --dry-run
unset BACKUP_PASSPHRASE
```

The command decrypts only into a protected temporary directory, does not persist the passphrase, and reports safe filename-level outcomes.

## Benchmark

Run the isolated benchmark on a Linux filesystem:

```bash
.venv/bin/python scripts/benchmark_backup_listing.py \
  --work-dir /tmp/novel-tnn-backup-list-benchmark \
  --iterations 7
```

The benchmark creates synthetic fixtures only. It reports directory time, sidecar-read time, total service time, bytes read, response size, and archive-open count. The acceptance gate is zero archive opens and a current warm list below 250 ms.

## Compatibility and background creation

The internal `manifest.json`, backup archive format, authenticated download
route, restore command, and restore drill are unchanged. P2C moved API backup
creation behind the existing SQLite-tracked in-process job runner: the POST
returns `202`, final publication remains staged/atomic, and the listing contract
continues to read only sidecar/stat metadata.

The runner is not an external durable queue. Process loss interrupts current
work rather than resuming it. Encrypted job passphrases are intentionally
process-local and are lost on restart; the operator must submit a new request.
This limitation does not affect sidecar compatibility or explicit repair.
