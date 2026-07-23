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
| `backup_stale` | warning | No validated backup newer than two days |
| `restore_drill_stale` | warning | No successful restore drill newer than eight days |
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

## Restore-drill freshness

`scripts/production_restore_drill.sh` publishes a bounded status file only after
database integrity, artifact availability, restored API readiness, and the
authenticated Reader smoke test all pass. The status contains only `status` and
`completed_at`, is atomically replaced, and is mode `0600`. A failed or absent
drill never overwrites the last successful timestamp with a false success.
