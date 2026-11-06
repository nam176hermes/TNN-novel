# Runtime, readiness, and observability


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Containers

API and worker were running and healthy with restart count 0 and no OOM state. Both run as the `novel` user, use a read-only root filesystem, drop all capabilities, set no-new-privileges, and have CPU, memory, and PID limits. Only `/data` is a writable bind mount. [Source: evidence/live-runtime-second-snapshot.json]

At the sampled point the API used about 215 MiB of 768 MiB and four PIDs. The worker used about 69 MiB of 1.5 GiB and two PIDs. The application process had umask `0007`; database, WAL, and SHM were mode `0660`. [Source: evidence/live-runtime-second-snapshot.json]

## Readiness

Local and public readiness returned HTTP 200 and `ready_with_degraded_capabilities`. Database, storage, disk, jobs, public configuration, and worker checks passed. Worker heartbeat age was near one second, queue claiming was enabled, and API and worker release IDs matched. Optional TTS reported `gpu_unavailable` without making core readiness fail. [Source: evidence/live-runtime-second-snapshot.json]

Focused tests independently cover missing worker, stale heartbeat, and release mismatch with HTTP 503. [Source: evidence/test-summary.json]

## Metrics and alerts

The authenticated operational metrics implementation and deterministic alert rules pass tests. Unauthenticated metrics access returns HTTP 401. Recovery receipts are missing, so recovery-freshness alerts cannot become fresh. No external notifier or public-health monitor delivery receipt was demonstrated. [Source: evidence/http-security-probes.json] [Source: evidence/test-summary.json]

## Provenance limitation

The API version payload reports the correct release, Git SHA, build timestamp, tag, and schema, but reports `image_digest=unknown`. Docker inspection supplies the immutable image IDs outside the application. [Source: evidence/live-runtime-second-snapshot.json]

## Verdict

Runtime and readiness: **GO**.

Observability: **GO_WITH_LIMITATIONS** until recovery receipts and one external delivery path are proven.
