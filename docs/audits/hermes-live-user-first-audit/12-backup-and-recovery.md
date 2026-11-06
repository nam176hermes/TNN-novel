# Backup and Recovery

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Backup state

Ten encrypted backups were present. The newest was about 5.2 hours old at inspection, 5,638,417,088 bytes, and had both manifest and checksum sidecars. [Source] fresh read-only operator-backup directory scan

## Fresh isolated restore

The newest archive was restored under `/tmp/novel-tnn-live-audit/restore-drills/` using the production image. Validation passed:

- integrity: `ok`;
- foreign-key violations: `0`;
- artifact paths: `1,774`;
- books: `6`;
- chapters: `760`;
- authenticated read-only Reader smoke: PASS.

[Source] `/tmp/novel-tnn-live-audit/restore-drill.log`; fresh validation JSON; temporary restore status receipt

The production database and production restore-status location were not modified.

## Observability gap

The API and worker mount only `/data`. The external backup directory is not mounted, and `/data/logs/runtime/restore-drill.status.json` was absent. The runtime therefore cannot prove current external backup or restore freshness. See OPS-REC-003. [Source] fresh Docker mount inspection and status-file probe

## Verdict

Recovery mechanics: **GO**. Recovery observability: **GO_WITH_LIMITATIONS**.
