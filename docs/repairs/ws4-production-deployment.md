# WS4 Production Deployment Record

Deployment date: 2026-07-23

Release ID: `ws4-production-20260723-r1`

Deployed source commit: `2ef2549d3d0154fa467137b910f87788c4a7d37e`

## Outcome

WS4 was fast-forward merged into the main worktree and deployed successfully.
The API and import worker are healthy, report the same release identity, and
pass local and public health/readiness probes. Production data, environment
configuration, Cloudflare, DNS, tunnel, and reverse-proxy settings were not
changed.

Core readiness reports `ready_with_degraded_capabilities` because F5/ViVoice is
correctly unavailable without a supported GPU. TTS remains optional and does
not make the Reader or core API unavailable.

## Merge and release commits

- `3e71744` — completed WS4 implementation branch.
- `4fa83c2` — pinned WS4 production and rollback image overlays.
- `2ef2549` — updated the release contract test for the pinned WS4 overlay.

The deployment images were built from a clean Git archive at `2ef2549`, not
from untracked runtime or operator files.

## Verification before cutover

Fresh `scripts/verify.sh` result:

- backend: 1,181 passed, 2 warnings;
- frontend: 85 test files and 758 tests passed;
- frontend production build: 1,855 modules built;
- compile, shell, lint, typecheck, and dependency gates passed;
- aggregate exit status: zero.

No durable job was queued or running before cutover. Database and artifact
paths were not migrated or modified.

An encrypted backup was created and remotely verified before deployment:

`novel-pipeline-backup-20260723-171849.tar.gz.enc`

The multipart upload encountered one transient HTTP 502 and completed through
the existing retry path. The final backup manifest and checksum verification
passed.

## Pinned images

API:

- tag: `novel-pipeline-api:ws4-production-20260723-r1`
- image ID: `sha256:6ea8841b21a170d6453cff22dbafd0213d635e707d5551e2af94dc798d8c1fe3`

Import worker:

- tag: `novel-pipeline-import-worker:ws4-production-20260723-r1`
- image ID: `sha256:b3f92efa269bc3f2804dcd2549ae853ae247f2a09f7ce87ba1d20dc9c416a205`

Both images report:

- Git SHA: `2ef2549d3d0154fa467137b910f87788c4a7d37e`;
- release ID: `ws4-production-20260723-r1`;
- schema revision: `2026-07-14-import-job-persistence-phase5`.

Runtime image digests are injected through the tracked release overlay.

## Cutover procedure and evidence

The import worker was recreated first, followed by API. This ordering is
required because the new API readiness contract validates worker release
identity. The canonical runbook was corrected to preserve this ordering for
future deployments and rollback.

Post-cutover checks:

- API container: healthy, zero restarts;
- import worker container: healthy, zero restarts;
- local `/api/health`: HTTP 200;
- local `/api/ready`: HTTP 200;
- public app, health, readiness, and version routes: HTTP 200 with a browser
  user agent;
- worker heartbeat: fresh and queue-claim capable;
- API/worker release match: true;
- authenticated operations metrics: HTTP 200 and redaction checks passed;
- unauthenticated operations metrics: HTTP 401;
- Reader book/chapter smoke: passed;
- SQLite `integrity_check`: `ok`;
- foreign-key violations: zero;
- runtime contract checks: passed for API and worker.

Cloudflare returned HTTP 403 to a default scripted Python user agent while the
same public routes returned HTTP 200 to a browser-like probe. This is an edge
filter behavior, not an origin health failure.

## Runtime hardening

API:

- non-root user;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- PID limit 256;
- memory limit 768 MiB;
- CPU limit 1;
- application-process umask `0007`.

Import worker:

- non-root user;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- PID limit 384;
- memory limit 1.5 GiB;
- CPU limit 2;
- application-process umask `0007`.

Database, WAL, and SHM permissions remained mode `0660` with the expected
runtime UID/GID.

## Operational status and limitations

The authenticated alert evaluation currently reports:

- historical failed jobs;
- backup freshness stale;
- restore-drill freshness stale.

The backup freshness alert scans the in-container `/data/backups` location,
while production encrypted backups are written to the operator-owned external
backup directory. The alert therefore does not currently reflect the verified
external backup above. This integration gap should remain visible and be fixed
in a later operations task; it is not evidence that the pre-deployment backup
failed.

TTS reports `gpu_unavailable` and no CPU synthesis was attempted. No paid
provider calls or GPU synthesis were performed during deployment.

## Rollback

Tracked rollback overlay:

`deploy/production/compose.rollback.pre-ws4-production-20260723-r1.yaml`

The stopped pre-WS4 API container is preserved as:

`novel-tnn-wsl-api-1-pre-ws4-production`

Release images, rollback images, the encrypted backup, and the stopped
container must remain until a separately approved retention cleanup. Rollback
uses the worker-first then API ordering documented in
`docs/production-release-runbook.md`.

## Decision

GO for WS4 production operation. Core health, data integrity, release
provenance, runtime controls, worker-aware readiness, metrics access, and the
GPU-only TTS invariant passed deployment checks.

The backup/restore freshness metric integration remains a documented follow-up
and does not block the deployed private single-operator release.
