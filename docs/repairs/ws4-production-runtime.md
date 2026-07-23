# Workstream 4 — Production Runtime, Readiness, Provenance, Observability, and TTS

## Outcome

Workstream 4 is implemented and verified on branch
`repair/ws4-production-runtime`. Changes were exercised with pinned local
images and an isolated Docker volume on `127.0.0.1:17860`.

No production deployment, restart, environment edit, ingress change, provider
call, GPU synthesis, database migration, or production-data mutation occurred.
Production cutover remains behind explicit operator approval.

| Finding | Staged result |
| --- | --- |
| OPS-002 | API and worker runtime contracts now have an executable drift check; staging passed non-root/read-only/capability/resource/health controls. |
| OPS-003 | API and worker expose the same build release ID plus Git SHA, timestamp, version, image identity, component, and schema revision. |
| OPS-004 | Readiness distinguishes core, required job processing, and optional capabilities; fresh/stale/missing/mismatched workers are tested. |
| OBS-001 | Authenticated low-cardinality operational metrics and deterministic alerts are exported. |
| TTS-001 | Direct F5 engine calls fail closed with a typed unavailable error before model resolution when CUDA is unavailable. |

## Baseline

- base branch: `upgrade-b/00-baseline-and-agent-guidance`
- base commit: `96cdd9217be80860e106b0fa970fccb52c3d65d0`
- implementation branch: `repair/ws4-production-runtime`
- Python: 3.11.15
- Node: 22.23.0
- npm: 10.9.8
- Docker: 29.1.3
- Docker Compose: 2.40.3
- mutable tests: isolated pytest databases/data directories with
  `NOVEL_PIPELINE_IGNORE_DOTENV=1`

The baseline focused suite passed 69 tests. The baseline verification wrapper
correctly returned non-zero in this new worktree because checkout-local
production prerequisites (`.env`, production DB, and production logs) were
intentionally absent. Product verification was subsequently run with the
external production environment validator path and dotenv loading disabled;
no environment values were sourced or printed.

## Reproduction and root causes

### OPS-002 — live runtime drift

Read-only Docker inspection showed the running worker had `cap_drop=ALL`,
`no-new-privileges`, 384 PID limit, 1.5 GiB memory, and 2 CPUs. The running API
was non-root/read-only but lacked those capability and resource controls.
Tracked Compose already described the intended API controls, so the defect was
release drift without an executable runtime conformance check.

### OPS-003 — incomplete provenance

The live API and worker used different historical tags, while `/api/version`
returned only application version `0.1.0`. There was no shared release identity
or Git/image/schema traceability.

### OPS-004 — incomplete readiness

Readiness validated API storage/database/configuration but not external worker
heartbeat, worker release identity, queue claim capability, or optional GPU TTS.
An API could therefore report ready while asynchronous work was unavailable.

### OBS-001 — in-process signals only

Operational facts existed across status, database, backup, and artifact code,
but there was no authenticated low-cardinality export or tested alert contract.

### TTS-001 — low-level CPU fallback

API and pipeline guards already rejected unavailable F5 jobs, but the direct F5
engine resolved `cuda` to `cpu` when CUDA was absent. A future direct caller
could bypass the intended GPU-only invariant and load a CPU model.

## Runtime inspect matrix

| Control | Live API before | Live worker before | Isolated staging after |
| --- | --- | --- | --- |
| non-root user | yes | yes | API + worker yes |
| read-only root | yes | yes | API + worker yes |
| drop all capabilities | no | yes | API + worker yes |
| no-new-privileges | no | yes | API + worker yes |
| PID limit | none | 384 | API 256; worker 384 |
| memory limit | none | 1.5 GiB | API 768 MiB; worker 1.5 GiB |
| CPU limit | none | 2 | API 1; worker 2 |
| healthcheck | yes | yes | API + worker healthy |
| restart policy | unless-stopped | unless-stopped | API + worker unless-stopped |

The limits preserve the already tracked Compose policy. Read-only live
measurements were approximately 173–233 MiB for API and 79–88 MiB for worker.
Under isolated large-payload import/Reader/export smoke, staging used about
89 MiB API and 52 MiB worker, with four and two PIDs respectively. The staging
Reader returned an 864,042-byte source response and a 592,041-byte translation;
the 592,056-byte TXT export completed under the limits.

`scripts/check-runtime-contract.py` performs a read-only, allowlisted Docker
inspection and fails when mandatory controls drift. It never exports container
environment values, mounts, commands, labels, or secrets.

## Release provenance

`/api/version` now exposes only non-secret build metadata:

```json
{
  "version": "0.1.0",
  "frontend_version": "0.1.0",
  "git_sha": "<full reviewed commit>",
  "build_timestamp": "<UTC timestamp>",
  "release_id": "<shared API/worker release>",
  "image_tag": "<pinned tag>",
  "image_digest": "<resolved digest or image ID>",
  "schema_revision": "<current schema revision>",
  "component": "api"
}
```

The worker writes the same release ID and Git SHA in its bounded heartbeat.
Readiness compares the two identities. Staging used release
`ws4-bbd522079daa`; both components matched. The staging API and worker image
IDs were recorded as:

- API: `sha256:097a779ee6366bed3c0a402ffb10bab7f3a309b17d16b179ddc0cd4a31d0785e`
- worker: `sha256:86023490c0b359f449311b3c6dcba70334b03d2cea4b17a4afd8a008a61295f4`

These are evidence images, not production approval. Because documentation and
restore-freshness commits followed the image build, cutover must build fresh
images from the final reviewed commit and record their new immutable IDs.

## Readiness schema

```text
status
├── core
│   ├── api
│   ├── database
│   ├── storage
│   ├── disk
│   └── configuration
├── job_processing
│   ├── required/status/reason
│   ├── heartbeat_age_seconds
│   ├── release_id/release_match
│   └── queue_claim_capable
├── capabilities
│   └── tts: required/status/available/provider/reason
└── release
    └── API and worker release comparison
```

Rules:

- core failure, required missing/stale worker, release mismatch, or inability to
  claim queued work produces `not_ready` and HTTP 503;
- optional F5/ViVoice unavailable produces
  `ready_with_degraded_capabilities` and HTTP 200;
- an in-process worker configuration is represented explicitly and does not
  require an external heartbeat.

Staging returned HTTP 200 with core ready, a fresh claim-capable matching
worker, and `ready_with_degraded_capabilities` because no supported GPU was
available. Tests cover fresh, stale, missing, release mismatch, DB failure, low
disk, in-process processing, and optional TTS degradation.

## GPU-only TTS invariant

The F5 engine now checks runtime capability before importing or resolving the
model. Without supported CUDA it raises typed `TTSUnavailableError` and never:

- selects CPU;
- resolves or downloads the model;
- loads weights;
- begins synthesis.

Fixture tests explicitly mock an available CUDA contract; they remain useful
without representing CPU synthesis as production-capable. Existing API,
pipeline, worker, Reader-capability, retry, and invalid-job guards remain in
place.

## Operational metrics and alerts

`GET /api/ops/metrics` requires normal operator authentication. It exports:

- API health/public-probe contract;
- API/worker release match;
- worker heartbeat age and queue claim capability;
- queue depth and oldest age;
- failed/interrupted aggregate;
- validated backup freshness;
- restore-drill freshness;
- disk free and database size;
- aggregate artifact-integrity results;
- aggregate auth-session lifecycle counts;
- TTS capability;
- container restart count when supplied externally;
- deterministic low-cardinality alerts.

It does not expose content, artifact paths, filenames, owner/session/worker IDs,
tokens, cookies, environment values, or high-cardinality labels. The expensive
artifact and database snapshot is cached for 30 seconds.

Staging evidence:

- unauthenticated metrics: HTTP 401;
- authenticated metrics: HTTP 200;
- release match: true;
- worker claim capability: true;
- TTS status: unavailable;
- expected clean-staging warnings: backup stale and restore drill stale;
- response redaction assertions: passed.

Restore-drill success is now published atomically as mode-0600 JSON containing
only `status` and `completed_at`, and only after all isolated restore validation
gates pass. Alert thresholds, polling ownership, cutover, and rollback are in
`docs/operations/runtime-alerts-and-rollback.md`.

## Files changed

- `Dockerfile`
- `compose.yaml`
- `app/runtime_identity.py`
- `app/runtime_status.py`
- `app/import_worker.py`
- `app/mobile_api/main.py`
- `app/mobile_api/routers/health.py`
- `app/mobile_api/routers/operations.py`
- `app/mobile_api/services/operational_metrics_service.py`
- `app/mobile_api/services/tts_service.py`
- `app/services/tts/availability.py`
- `app/services/tts/f5_vietnamese_engine.py`
- `scripts/check-runtime-contract.py`
- `scripts/production_restore_drill.sh`
- `scripts/record_restore_drill_status.py`
- focused runtime, readiness, metrics, restore, health, and TTS tests
- this report and the operations runbook

## Commits

- `a26b5d5 fix(runtime): align api container hardening`
- `bbaef8e feat(version): expose release provenance`
- `9ad454d fix(readiness): include worker and capability status`
- `fe9a5b1 fix(tts): enforce gpu-only engine invariant`
- `bbd5220 feat(ops): export authenticated operational metrics`
- `aaa0e2f feat(ops): record restore drill freshness`
- final documentation commit: recorded after verification

## Verification and security review

Targeted suites covered runtime policy, identity, readiness state transitions,
TTS direct-call failure, metrics authentication/redaction/alerts, and restore
status publication. Isolated Docker staging covered pinned builds, health,
readiness, provenance, runtime limits, import, large Reader responses, export,
backup metadata, metrics authentication, and GPU-unavailable behavior.

The full mandatory commands and exact final results are recorded at the end of
this report after the final gate.

Security/data conclusions:

- production state was inspected read-only and never modified;
- staging used a newly created disposable volume and alternate loopback port;
- the isolated staging containers, network, and volume were removed after the
  smoke checks; evidence images were retained;
- no Docker socket is mounted into the API;
- metrics and version endpoints contain allowlisted, non-secret fields;
- no database migration or artifact contract changed;
- no challenge, proxy, browser fingerprint, solver, provider, or ingress
  behavior changed;
- no CPU or GPU synthesis was performed.

## Remaining limitations and approval gate

- Public post-deployment probes are not run because deployment is not approved.
- Container restart count and public uptime require an external monitor; the API
  intentionally has no Docker socket.
- Alert evaluation is available in the authenticated endpoint, but notification
  delivery must be configured in the operator monitor.
- Resource limits passed representative isolated smoke workloads, not a full
  maximum-concurrency soak test.
- Paid-provider and actual GPU TTS performance remain untested by design.

## GO / NO-GO

**GO for operator review and an explicitly approved staging-to-production
cutover using freshly rebuilt final-commit images.**

**NO-GO for production restart/deployment in this task, and NO-GO for starting
Workstream 5 until the operator reviews this report and decides whether to
deploy/validate WS4 or intentionally defer that deployment.**
