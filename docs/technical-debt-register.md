# Technical Debt Register

## P0

### Stale Artifact Paths After Root Move

- Status: RESOLVED_IN_P0A (2026-07-12).
- Historical evidence: sampled raw, translated, content HTML, cover, audio, and TTS metadata pointed to deleted `/home/thenam176/novel_pipeline`; deterministic remapping found the files under the current data root.
- Scale: 4,159 raw, 4,159 translated, 3,464 HTML, 8 audio, 3 cover, and 8 TTS artifact path sets were remappable.
- Former impact: library counts remained visible while content/audio/cover reads failed; direct source retrieval returned no content for a representative chapter.
- Resolution: verified protected backup and restore drill; copied-DB rehearsal; transactional operator apply of 12,151 approved values; zero-update second apply; fallback removed; Reader/audio/cover/TTS/export smoke passed.
- Acceptance: no old-root paths remain; every migrated path stays under configured data root; representative Reader/audio/cover flows pass; DB integrity and operator content hashes remain valid.

## P1

### Backup Listing Scans Compressed Archives

- Status: RESOLVED_IN_P1A (verified 2026-07-18).
- Historical evidence: the original list path opened archives to obtain
  `manifest.json`, which could block a read-only status request.
- Resolution: `scripts.ops.list_backups` uses archive `lstat` plus bounded
  sidecar metadata only. Missing, malformed, orphaned, and partial artifacts
  receive safe metadata statuses; explicit archive inspection remains an
  operator-only repair action.
- Verification: `tests/test_benchmark_backup_listing.py`,
  `tests/test_mobile_api_backups.py`, and `tests/test_backup_job_service.py`
  pass in the current checkout (34 tests total); the list regression includes
  missing and malformed sidecars.

### Backup Creation Is Synchronous

- Status: RESOLVED_IN_P1A (verified 2026-07-18).
- Resolution: `BackupJobCoordinator` creates a durable backup job and returns
  HTTP 202; progress, cancellation, failure, and terminal auditing are handled
  off the request path. Secret-bearing passphrases are held only in the
  process-local TTL store, and encrypted artifacts publish only after `READY`
  sidecar validation.
- Verification: the current backup API/job suite passes 34 tests, including
  202 response, cancellation, credential-expiry, and encrypted-publication
  paths.

### Authenticated Status Exposes Absolute Paths

- Status: RESOLVED_IN_P0A.
- Historical evidence: `/api/system/status` returned and the UI rendered `database_path` and `data_dir`.
- Resolution: API/UI now expose safe labels, availability, sizes, and storage health only; smoke checks reject either legacy path field.
- Acceptance: API/UI tests assert no absolute path while status remains operationally useful.

### Reader Request And QA Cost

- Status: RESOLVED_IN_P1 (verified 2026-07-18).
- Historical evidence: duplicate cache ownership was reported, and a long QA
  fixture rendered approximately 5,182 DOM nodes.
- Resolution: Reader view delegates cache ownership to the Reader controller;
  `useChapterText` therefore skips its competing current-cache read. In
  `cee8872`, non-rich QA-overlay mode now reuses Reader's progressive
  80-paragraph scroll chunks rather than rendering every paragraph at once.
- Verification: the AUD-008 regression first failed with paragraph 120 present
  in a 180-paragraph QA overlay; after the fix it proves 80 initial paragraph
  blocks and 160 after a near-edge scroll. `ReaderView` plus `useChapterText`
  pass 105/105 and TypeScript typecheck passes.

### Operational Event Retention

- Status: RESOLVED_IN_P2C (verified 2026-07-18).
- Resolution: the app runs a lifecycle-owned background retention loop with
  bounded batches. Current settings retain operational events for 90 days or
  50,000 rows, with a 500-row batch and six-hour interval; authenticated
  sessions and failures have their own tested bounds.
- Verification: `tests/test_operational_retention.py` and
  `tests/test_retention_service.py` pass 23/23, covering age/count pruning,
  contention behavior, lifecycle ownership, and no request-time maintenance.

### Operational Documentation Path Drift

- Status: RESOLVED_IN_P0A.
- Historical evidence: active runbooks previously used the deleted personal root after the move.
- Resolution: active commands now resolve from repository/configuration variables; historical migration/audit evidence remains explicitly archival.
- Acceptance: active commands resolve from repository root or configured variables; no stale root in current operational docs.

## P2

### DNS-Rebinding-Safe Outbound Transport

- Status: SECURITY_HARDENING_REQUIRED (2026-07-18).
- Evidence: a source URL can pass DNS preflight and then be resolved again by a
  later `requests` transport. DS-002 and DS-006 cover direct import and every
  source-health caller; no useful internal target was exercised during the
  audit, so this is P2 rather than P1.
- Action: introduce one reviewed transport that connects only to the vetted
  peer address while preserving correct hostname/TLS/redirect behavior; apply
  it to every direct-import and source-health sink with integration fixtures.

### Browser Fallback Egress Policy

- Status: DESIGN_REQUIRED (2026-07-18).
- Evidence: browser fallback validates a hostname before Chromium navigation,
  but no safe peer-pinning implementation or exploit impact has been proven.
- Action: define the permitted browser egress and redirect model first, then
  implement and test it in a dedicated workstream. Do not claim direct HTTP
  controls cover Chromium.

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

- Status: RESOLVED_FOR_READER.
- Historical evidence: the prompt occupied substantial lower mobile Reader viewport until dismissed.
- Former impact: it competed with Reader navigation and primary actions.
- Resolution: existing durable dismissal remains; the prompt is task-aware and hidden only in Reader while remaining available in Library/Status and other workflows.

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

### Authenticated Parser and Reader Resource Budgets

- Status: SECURITY_HARDENING_BACKLOG (2026-07-18).
- Evidence: CSS import recursion/reparse, StarDict gzip and aggregate decode,
  Reader regex matching, and dictionary parser materialization lack one or more
  explicit work, decoded-byte, timeout, cache, or record-count ceilings.
- Action: make small format-specific changes with adversarial fixtures; retain
  existing upload and product contracts. The deep-security attack-path analysis
  calibrates these as P3 because no persistent broad outage was demonstrated.

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
