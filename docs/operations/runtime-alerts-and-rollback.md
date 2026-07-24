# Runtime alerts, deployment, and rollback

This runbook covers the private single-operator deployment. It does not grant
approval to restart or deploy production.

## Operational endpoints

- `GET /api/health` is the minimal liveness probe.
- `GET /api/ready` is the dependency and capability readiness probe.
- `GET /api/version` exposes non-secret release provenance.
- `GET /api/ops/metrics` is authenticated and returns low-cardinality
  operational state plus evaluated alert rules.

Readiness has three states:

- `ready`: all required components and configured capabilities are ready;
- `ready_with_degraded_capabilities`: the core application and required worker
  are ready, but an optional capability such as GPU TTS is unavailable;
- `not_ready`: a required core check or required worker check failed.

Do not page on `ready_with_degraded_capabilities` solely because F5/ViVoice is
unavailable. F5/ViVoice remains GPU-only and must fail closed without CUDA.

## Alert rules

Poll the authenticated metrics endpoint from the operator monitor. Alert codes
are stable and deliberately contain no book, chapter, filename, token, user, or
session identifiers.

| Code | Severity | Trigger |
| --- | --- | --- |
| `worker_not_ready` | critical | Required import worker cannot claim queued work |
| `release_mismatch` | critical | API and worker release IDs differ |
| `disk_critical` | critical | Free space below 100 MiB |
| `disk_low` | warning | Free space below 1 GiB |
| `queue_stale` | warning | Oldest queued work exceeds one hour |
| `jobs_failed` | warning | Failed or interrupted work exists |
| `external_backup_missing`, `restore_drill_missing` | warning | Required receipt is absent |
| `external_backup_stale`, `restore_drill_stale` | warning | Receipt exceeds its configured maximum age |
| `external_backup_invalid`, `restore_drill_invalid` | warning | Receipt JSON, schema, size, or file type is invalid |
| `external_backup_future`, `restore_drill_future` | warning | Completion time exceeds allowed clock skew |
| `external_backup_wrong_release`, `restore_drill_wrong_release` | warning | Producer version differs from the running release |
| `backup_stale`, `restore_drill_stale` | warning | Compatibility aliases emitted with every non-fresh recovery state |
| `artifact_integrity` | critical | Active artifact scan finds unavailable files |

Container restart count is reported only when an external orchestrator provides
it. Docker socket access is intentionally not mounted into the API container.
Public reachability also remains an external probe.

## Release build

Build API and worker from the same clean commit and release ID. Replace the
example variables with the reviewed release values.

```bash
export NOVEL_GIT_SHA="$(git rev-parse HEAD)"
export NOVEL_BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export NOVEL_RELEASE_ID="release-${NOVEL_GIT_SHA:0:12}"
export NOVEL_API_IMAGE_TAG="novel-pipeline-api:${NOVEL_RELEASE_ID}"
export NOVEL_WORKER_IMAGE_TAG="novel-pipeline-import-worker:${NOVEL_RELEASE_ID}"

docker build --target api \
  --build-arg NOVEL_GIT_SHA="$NOVEL_GIT_SHA" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$NOVEL_BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$NOVEL_RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$NOVEL_API_IMAGE_TAG" \
  -t "$NOVEL_API_IMAGE_TAG" .

docker build --target import-worker \
  --build-arg NOVEL_GIT_SHA="$NOVEL_GIT_SHA" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$NOVEL_BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$NOVEL_RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$NOVEL_WORKER_IMAGE_TAG" \
  -t "$NOVEL_WORKER_IMAGE_TAG" .
```

Record both immutable local image IDs before staging. At cutover, provide the
resolved image digests through `NOVEL_API_IMAGE_DIGEST` and
`NOVEL_WORKER_IMAGE_DIGEST`. API and worker must report the same release ID.

## Pre-deployment gate

1. Confirm the worktree is clean and the release commit was reviewed.
2. Run the complete repository verification gate.
3. Build both pinned images from that exact commit.
4. Run them against an isolated data volume and alternate loopback port.
5. Verify health, readiness, version, authenticated metrics, import, Reader,
   export, and backup-list smoke paths.
6. Run `scripts/check-runtime-contract.py` against both staging containers.
7. Confirm `tts.status=unavailable` on a host without supported CUDA and verify
   there is no CPU model load.
8. Record prior production image tags, IDs, release ID, and database schema.
9. Create and validate a fresh encrypted backup.
10. Obtain explicit operator approval before production restart or deployment.

## Cutover gate

After approval, update only the reviewed image variables and use the repository
Compose configuration. Do not edit Cloudflare, DNS, tunnel, or reverse-proxy
configuration as part of this workstream.

Immediately verify:

```text
local /api/health = 200
local /api/ready = 200 and not not_ready
public /api/health = 200
public /api/ready = 200 and not not_ready
API release ID = worker release ID = approved release ID
worker heartbeat is fresh and queue_claim_capable=true
authenticated metrics are available and redacted
container restart counts remain stable
```

## Rollback

Rollback is required if a mandatory probe fails, release IDs differ, the worker
cannot claim work, protected downloads fail, or logs show repeated startup or
database errors.

1. Stop new job creation through the existing operator procedure.
2. Preserve logs and record the failing image IDs and release payloads.
3. Restore the previously recorded API and worker image tags in the deployment
   environment; do not use a floating `latest` tag.
4. Recreate both services with the repository Compose configuration.
5. Re-run local health/readiness/version and authenticated smoke checks.
6. Re-enable job creation only after the worker heartbeat and release match are
   healthy.
7. Restore data only if a separately approved data rollback is actually
   required. This workstream introduces no database migration.

Never delete the current database, artifact tree, backup, or image during an
application rollback. Retain the failed images until the incident is reviewed.

## Recovery receipt contract

Runtime reads only these fixed paths below `DATA_DIR`:

- `logs/runtime/external-backup.receipt.json`
- `logs/runtime/restore-drill.receipt.json`

Each receipt has exactly `status`, `completed_at`, `archive_hash_id`,
`validation_counts`, and `producer_version`. Status is `passed`, completion time
is UTC, and the hash identifier is a lowercase SHA-256 identifier. Validation
counts use a bounded allowlist and describe checks that were actually executed.
The runtime requires an exact successful contract per receipt kind before it can
classify a receipt as fresh:

- External backup: `archive_verified=1`, `metadata_verified=1`,
  `checksum_verified=1`, `remote_uploads_verified=3`, and
  `remote_metadata_verified=2`.
- Restore drill: `checksum_verified=1`, `sqlite_integrity_checks=1`,
  `foreign_key_violations=0`, `artifact_paths_scanned` present and non-negative,
  `api_readiness_checks=1`, and `authenticated_reader_smokes=1`.

Missing, unsuccessful, or cross-kind counters make the receipt `corrupt`.
The producer version must match `NOVEL_RELEASE_ID` for a fresh state.

The maximum ages are configured with
`NOVEL_EXTERNAL_BACKUP_MAX_AGE_SECONDS` (default `172800`) and
`NOVEL_RESTORE_DRILL_MAX_AGE_SECONDS` (default `691200`). Future timestamps use
`NOVEL_RECOVERY_RECEIPT_FUTURE_SKEW_SECONDS` (default `300`). Invalid overrides
fall back to these safe defaults.

`scripts/production_backup.sh` publishes only after local metadata and checksum
verification, off-site upload, remote archive and metadata re-download
comparison, and remote retention rotation succeed. A verification or rotation
failure leaves the previous receipt unchanged.
`scripts/production_restore_drill.sh` publishes only after SQLite integrity,
foreign-key, artifact, API readiness, and authenticated Reader checks succeed.
Both producers publish through the pinned `BACKUP_IMAGE` as UID/GID
`10001:10001`, with networking disabled and only the dedicated
`DATA_DIR/logs/runtime` receipt directory mounted at `/receipts`. The directory
must already exist, resolve to that fixed location, and be owned for UID 10001
access. `RECOVERY_PRODUCER_VERSION` is mandatory and is verified against the
image's embedded `NOVEL_RELEASE_ID`; operators must set both to the intended API
release ID. The producer does not receive API credentials or query the running
service. If the running API uses another release, its bounded receipt reader
classifies the result as `wrong_release` and emits the stable recovery alert.
The publisher
receives only the archive hash identifier, validation counts, producer version,
and its fixed in-container output path. Backup secrets,
R2 credentials, archive and report paths, and `production.env` are never passed
to the publisher container.

Publication uses a mode `0700` parent, a mode `0600` temporary file, file fsync,
atomic replacement, and directory fsync. Runtime rejects symlinks, non-regular
files, oversized payloads, unknown keys, and malformed values.

The API never reads or returns backup archives, checksum sidecars, backup
directories, archive names, remote object keys, report paths, passphrases, R2
configuration, credentials, parser exceptions, or arbitrary receipt fields.
Only authenticated metrics and system status expose the bounded derived state,
age, safe completion timestamp, hash identifier, allowlisted counts, producer
version, and threshold.
