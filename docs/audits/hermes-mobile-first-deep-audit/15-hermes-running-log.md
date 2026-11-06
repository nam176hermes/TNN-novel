# Hermes Mobile-First Deep Audit Running Log

Audit started: 2026-07-22T12:50:57-04:00
Repository: `/home/thenam176/Novel-TNN`
Mode: audit and repair planning only

## Safety boundary

- Production database, artifacts, external production environment, containers, ingress and challenge behavior remain read-only.
- No production restart, deployment, migration, product repair or paid-provider call is authorized.
- Browser/challenge integration is inspected only at its contract boundary. No third-party challenge is live-tested.
- F5/ViVoice is evaluated as GPU-only.
- Private values and chapter content are excluded from logs and reports.

## Phase 0: baseline

### Commands and inspections completed

- Captured repository root, branch, commit SHA, dirty status and active worktrees.
- Captured Python, Node, npm, Git, Docker, Compose, Playwright and Windows Chrome versions.
- Inspected `scripts/verify.sh`, `tests/conftest.py`, `compose.yaml`, `Dockerfile`, CI, dependency manifests, environment loading and readiness code.
- Inspected production environment file existence, mode and variable names without reading values.
- Inspected live container image references, users, mounts, runtime hardening, health, restart count and resource usage without mutation.
- Probed local and public `/`, `/api/ready` and `/api/version` with timing and response-header capture.
- Ran read-only SQLite integrity, foreign-key, logical orphan, duplicate-key and artifact-path checks inside the API container.
- Started a fresh isolated baseline verification run with `NOVEL_PIPELINE_IGNORE_DOTENV=1`, temporary test data and an external frontend build directory.

### Environment and evidence

- Baseline commit: `286cd49129494604eb1fe6413307375a15bc4a0b`.
- Branch: `upgrade-b/00-baseline-and-agent-guidance`.
- Worktree was already dirty at audit start. Product files were not changed by the audit.
- Production API and import worker reported healthy at baseline.
- Public and local readiness returned HTTP 200.
- SQLite `integrity_check` returned `ok`; `foreign_key_check` returned zero rows.
- No duplicate `(book_id, chapter_number)` keys were found.
- Populated chapter and TTS artifact-path checks found no missing, outside-root or zero-byte referenced files.

### Baseline findings requiring synthesis

- Live API container hardening differs from tracked Compose expectations: the API runtime lacks the tracked capability drop, no-new-privileges flag, PID limit, CPU limit and memory limit. The worker has those controls.
- Live API and worker use different historical image tags. `/api/version` reports only `0.1.0` and `phase1`, not a commit or deploy identity.
- Public responses did not expose the expected modern security-header set in the captured headers.
- `/api/ready` does not report worker heartbeat or GPU/TTS capability.
- Production contains many completed jobs and retained operational/auth rows; retention effectiveness and queue semantics remain under audit.

### Failures and limitations

- `docker compose ps` without the external env file failed safely because required production variables were absent. Runtime inspection used `docker inspect` instead and did not render secret-bearing configuration.
- Direct host access to `data/pipeline.db` is denied by container ownership. Read-only aggregate checks were executed inside the API container without copying or modifying the database.
- CodeGraph index is absent for this repository. Static inspection uses targeted source search and direct reads.
- Local Python has Playwright `1.61.0`; Patchright package metadata is absent from the project venv. Browser binary discovery requires separate runtime inspection.

## Active workstreams

- Controller: Phase 0 baseline, authenticated runtime browser audit and final synthesis.
- Read-only worker A: Mobile Reader, mobile UX, desktop parity, accessibility, request ownership and maintainability.
- Read-only worker B: Backend workflows, data integrity, security, operations, backup/recovery, readiness, observability and CI.

## Completed evidence collection

- Authenticated mobile interaction ran at 360x740, 390x844 and 412x915.
- Desktop route and Reader checks ran at 1366x768 and 1440x1000.
- Reader translation, QA, raw-state, chapter navigation, offline reload, TOC, settings and request ownership were inspected in isolated staging.
- Focused backend workflow tests passed 271 tests.
- Focused security tests passed 115 tests.
- Focused TTS tests passed 42 tests; production returned safe `tts_unavailable` without synthesis.
- Production SQLite integrity, foreign keys, job aggregates and artifact inventory were inspected read-only.
- A fresh encrypted restore drill passed integrity, artifact-path validation and authenticated Reader smoke.
- Docker runtime hardening, provenance, readiness, resources, logs and public/local health were inspected read-only.
- Performance, desktop parity, keyboard behavior, touch targets and maintainability evidence were collected.

## Final limitations

- No live CAPTCHA or third-party challenge test.
- No paid translation request.
- No GPU voice synthesis and no CPU F5/ViVoice attempt.
- No production mutation, restart, restore, deployment or ingress change.
- No full screen-reader or measured contrast certification.
- Independent Claude and Codex CLI report reviews were unavailable due missing CLI authentication; deterministic package validation was used and passed.

## Deliverables

The audit package contains documents `00` through `15`, including the final report, feature matrix, issue register and this running log. Final mechanical and adversarial validation is recorded by the controller before handoff.
