# Technical Debt Register

## P0

### Stale Artifact Paths After Root Move

- Status: BROKEN, reproduced read-only.
- Evidence: all sampled/stored raw, translated, content HTML, cover, audio, and TTS artifact paths point to deleted `/home/thenam176/novel_pipeline`; deterministic remapping to the current `data/` root finds the files.
- Scale: 4,159 raw, 4,159 translated, 3,464 HTML, 8 audio, 3 cover, and 8 TTS artifact path sets were remappable.
- Impact: library counts remain visible but content/audio/cover reads can fail; direct source retrieval returned no content for a representative chapter.
- Action: create a fresh protected backup, rehearse a prefix migration on a copied DB, verify hashes/integrity/foreign keys, then run a controlled idempotent migration with rollback.
- Acceptance: no old-root paths remain; every migrated path stays under configured data root; representative Reader/audio/cover flows pass; DB integrity and operator content hashes remain valid.

## P1

### Backup Listing Scans Compressed Archives

- Status: BROKEN at current data size.
- Evidence: `GET /api/system/backups` exceeded 20 seconds; two archives have no sidecar manifests; list code opens archives to obtain `manifest.json`.
- Impact: status/settings can block on a read-only list operation.
- Action: produce/repair bounded sidecar metadata, never scan large archives in the request list path, surface invalid metadata safely.
- Acceptance: warm list under 250 ms for current backup count; no path/manifest leakage; corrupt archive does not block other entries.

### Backup Creation Is Synchronous

- Status: WORKING_WITH_LIMITATIONS.
- Evidence: isolated creation took 11.4-17.5 seconds and runs inside the async HTTP handler.
- Impact: timeout risk, no durable progress/cancel/retry, unclear operator state.
- Action: implement the previously scoped durable job-backed backup with in-memory passphrase lifecycle and staged atomic publication.
- Acceptance: create returns HTTP 202 quickly; no passphrase persistence; cancel prevents publication; restore drill remains compatible.

### Authenticated Status Exposes Absolute Paths

- Status: SECURITY/PRIVACY REGRESSION.
- Evidence: `/api/system/status` returns and UI renders `database_path` and `data_dir` for authenticated non-public requests.
- Impact: unnecessary host topology disclosure to any compromised authenticated session and inconsistency with protected path policy.
- Action: return safe labels/availability and sizes only; retain paths in server logs/CLI diagnostics where necessary.
- Acceptance: API/UI tests assert no absolute path while status remains operationally useful.

### Reader Request And QA Cost

- Status: WORKING_WITH_LIMITATIONS.
- Evidence: duplicate loads in P1; QA path 102-599 ms and approximately 5,182 DOM nodes on long fixture.
- Impact: delayed interaction and avoidable network/render work.
- Action: establish one request owner and progressive QA rendering; profile before memoization/virtualization.
- Acceptance: one chapter/content request owner; normal modes under target; long QA has no obvious main-thread freeze.

### Operational Event Retention

- Status: WORKING_WITH_LIMITATIONS.
- Evidence: 16,396 rows and approximately 4.16 MB in the current DB; bounded API reads do not prove bounded storage retention.
- Impact: silent database growth over long private operation.
- Action: define age/count retention and operator-visible storage summary; preserve security-relevant recent history.
- Acceptance: documented bound, tested pruning, no request-time mass deletion.

### Operational Documentation Path Drift

- Status: INCORRECT.
- Evidence: current runbooks and deployment/backup docs still contain `/home/thenam176/novel_pipeline` commands after the root move.
- Impact: operator can execute commands in a nonexistent path or misdiagnose deployment.
- Action: update active runbooks; clearly label immutable historical plans as archival.
- Acceptance: active commands resolve from repository root or configured variables; no stale root in current operational docs.

## P2

### Duplicate Glossary Terms

- Status: DATA_QUALITY_REVIEW_REQUIRED.
- Evidence: 72 exact normalized-source duplicates in read-only checks.
- Impact: conflicting terminology and unnecessary QA work.
- Action: generate a non-destructive conflict report; operator chooses canonical terms; add uniqueness only after semantic rules are agreed.

### Large Domain Modules And Circular Dependency

- Status: MAINTAINABILITY.
- Evidence: `db.py` 6,225 lines, PipelineService 5,700, ReaderView 5,251, CSS 12,244; direct PipelineService/QA circular import.
- Impact: high change-risk and difficult test ownership.
- Action: follow `docs/code-modularity-plan.md`; break circular dependency before broad movement.

### Mobile Library And Import Density

- Status: UX_LIMITATION.
- Evidence: two-column 390px library and dense wrapped import steps in screenshots.
- Impact: scanning and touch accuracy.
- Action: one-column compact mobile cards and separated vertical import steps.

### PWA Install Prompt Backoff

- Status: UX_LIMITATION.
- Evidence: prompt occupies substantial lower mobile viewport until dismissed.
- Impact: competes with navigation and primary actions.
- Action: durable dismissal/backoff and task-aware presentation.

### M4B Chapter Markers

- Status: WORKING_WITH_LIMITATIONS.
- Evidence: fixture M4B validates as media but has no chapter markers.
- Impact: audiobook navigation quality.
- Action: decide product contract, then add ffprobe-backed marker tests if required.

### Reproducible Python Dependencies

- Status: MAINTAINABILITY.
- Evidence: runtime manifests use compatible ranges without a fully locked deployment set; npm lockfile provides stronger Node reproducibility.
- Impact: future environment drift.
- Action: define a reviewed Python lock/constraints workflow without broad upgrades.

## P3

### Deprecation Plan

- `passlib`/`crypt`: Python deprecation warning; bcrypt is intentionally constrained for compatibility.
- `jieba`/`pkg_resources`: deprecated setuptools API.
- `vinorm`: previously observed deprecation path; verify actual active dependency before replacement.
- Action: isolate replacements in dedicated upgrade phases with auth/text-normalization regression suites.

### Low-End Device And WAN Evidence

- Current browser measurements are local desktop Chromium and do not establish low-end Android memory, WAN latency, offline eviction, or battery behavior.
- Add these only after P0/P1 correctness work.

## Resolved Baseline Debt

- P0 environment/venv drift: resolved.
- Frontend translated-library integration regression: resolved as test/route alignment.
- DB connection initialization overhead and library N+1: resolved by P2A.
- Multi-chapter import per-chapter connections/commits: resolved by P2B.
