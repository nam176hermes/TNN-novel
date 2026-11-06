# Backup and recovery


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Existing backup inventory

Eleven encrypted backup sets were present. Every sampled archive, checksum, and sidecar was mode `0600`. The newest archive was about 77,822 seconds old at capture, 5,630,391,072 bytes, `READY`, encrypted, and checksum-valid. The previous scheduled service completed with exit 0. [Source: evidence/production-backup-inventory.json] [Source: evidence/backup-systemd-status.txt]

## Current continuity failure

The current script requires a digest-pinned `BACKUP_IMAGE`, `RECOVERY_PRODUCER_VERSION`, and a receipt directory that the host runner can validate and UID 10001 can secure and write. Current configuration has no producer version and uses a non-digest image. The live data root and runtime directory are correctly owned by UID/GID 10001, but the host runner cannot traverse the mode `0750` data root to satisfy its preflight. [Source: evidence/backup-config-validation.log] [Source: evidence/backup-live-data-root-comparison.json]

The configured backup root, live Docker mount, and operator-provided runtime root are the same directory and have the same database hash and row counts. This rules out backing up a stale alternate database. [Source: evidence/backup-live-data-root-comparison.json]

## Isolated restore drill

The latest encrypted archive passed checksum and metadata validation, restored into a new root, passed SQLite integrity, zero foreign-key violations, 1,862 artifact-path checks, API readiness, and authenticated Reader smoke. [Source: evidence/restore-validation.json]

The full script then failed while publishing `restore-drill.receipt.json`:

```text
PermissionError: [Errno 1] Operation not permitted
os.fchmod(parent_fd, 0o700)
```

A separate ephemeral production-image probe proved that the publisher succeeds as UID/GID 10001 when the runtime directory is owned correctly. It created a mode `0600` receipt and the parser classified it `fresh`. This isolates the defect to runner, mount, and directory integration rather than receipt serialization. [Source: evidence/recovery-receipt-ephemeral-publish.json]

## Recovery classification

- Existing encrypted archive: VERIFIED.
- Core isolated restore: VERIFIED.
- Scheduled future backup continuity: FAILED.
- Integrated restore receipt publication: FAILED.
- Runtime receipt ingestion: MISSING.
- External alert delivery: NOT_TESTED.

## Verdict

**NO_GO**. Current data is intact and recoverable from the sampled archive, but the next backup and complete recovery-freshness workflow are not trustworthy.
