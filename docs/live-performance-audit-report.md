# Phase P1 Live Performance, Workflow, and UI/UX Audit

## Executive Summary

Runtime health is verified on an isolated Linux-filesystem checkout. API startup, production frontend, real Chromium workflows, import, Reader, fixture TTS, export, backup, accessibility basics, and security protections were exercised without paid providers or live operator data.

- Overall performance score: **6.5/10**
- Desktop UX score: **7.5/10**
- Mobile UX score before fixes: **4.5/10**; after narrow fixed-control fixes: **6/10**
- Private single-operator runtime suitability: **7/10**, conditional on backup and import bottlenecks being addressed

Top measured bottlenecks:

1. Project DB connection setup: 9.346 ms median versus 0.038 ms raw SQLite.
2. Book/library N+1: about 0.65-0.74 seconds at 59 synthetic books.
3. 120-chapter commit: 5.62 seconds despite a 96 KB request.
4. Synchronous backup: 11.4-17.5 seconds on a small fixture dataset.
5. Reader QA path: up to 599 ms and about 5,182 DOM nodes, plus duplicate requests.

Top workflow strengths:

1. Production routes lazy-load and warm navigation is generally about 0.15 seconds locally.
2. Import preview bounds rendered output and remains usable at the current 5 MB limit.
3. Reader text becomes visible independently of audio/dictionary completion.
4. TTS normalization/chunking overhead is small and artifact validation is present.
5. Authentication, SSRF, traversal, encrypted-secret backup, and protected artifact controls remain effective.

Most urgent performance fix: make DB initialization startup-scoped and remove library N+1 queries. Major wholesale refactoring is not justified first. Reader splitting is justified after request/raw-mode correctness fixes. Import splitting is justified later for responsibility and testing, not current speed. Backend repository/service separation is justified incrementally after transaction/query seams are established.

## Audit Environment

See `docs/live-performance-audit-implementation-note.md`. Measurements came from commit `c4a7873` on WSL Linux with an isolated synthetic database. The canonical `/mnt/c` checkout was used only for reviewed source patches and final verification.

## Measurement Methodology

HTTP route timing, Chromium production-build timing, PerformanceObserver long tasks/layout shifts, DOM inspection, screenshots, `EXPLAIN QUERY PLAN`, synthetic import commits, fixture audio, ffmpeg/ffprobe, and targeted security tests were used. Approximate Playwright timings are not Core Web Vitals.

## Test Fixtures

Synthetic fixtures covered short, normal, dialogue-heavy, raw-only, long, QA-warning, audio, 150-chapter, 1 MB, 4.9 MB, 120-chapter, and long-single-chapter cases. No copyrighted full content is included.

## Runtime Verification

- API health/readiness: HTTP 200.
- API process start to health/readiness: about 971 ms.
- Production web shell: reachable.
- Browser console errors in successful audit run: 0.
- Full fixed-control run: desktop, 390x844, and 360x740 completed.

## Route Timing Results

Most individual read routes were below 100 ms locally, but `/system/status` was about 94 ms warm and book lists degraded sharply with book count. See `docs/backend-performance-measurements.md` and `output/live-audit-2026-07-10/measurements/route-timings.json`.

## Database Findings

Connection initialization and N+1 access dominate. Existing chapter/job indexes are effective. No speculative index was added. The import path needs a bounded transaction rather than per-chapter connection/commit behavior.

## Bundle Findings

Main JS is 341.96 KB, CSS 188.78 KB, Reader 181.73 KB, and Import 49.70 KB raw. Route lazy loading works. Reader optional capabilities are bundled together. See `docs/frontend-performance-measurements.md`.

## React Rendering Findings

No React DevTools profile was fabricated. Observable evidence shows duplicate Reader loads, a QA interaction up to 599 ms, long tasks up to 249 ms, and a QA DOM around 5,182 nodes. Memoization should not precede request ownership and QA pipeline fixes.

## Page-Load Results

Login content appeared in 91-161 ms; authenticated useful shell took 830-844 ms. Cold route loads were usually under one second. Warm major-route runs were usually 143-160 ms with the audit settle allowance. These meet the directional local target.

## Import Performance Results

5 MB client preview is acceptable on this machine but should remain capped. The poor case is 120-chapter commit at 5.62 seconds. Server preview sessions and chunked upload are future options; transaction repair is the immediate action. See `docs/import-performance-measurements.md`.

## Reader Performance Results

Reader open and chapter switching were locally under one second. Duplicate requests and QA rendering are measurable issues. Raw/split/Raw gon are unavailable in the actual top-level workflow despite source data. Virtualization is not yet justified. See `docs/reader-performance-measurements.md`.

## TTS Non-Provider Results

Normalization/chunking are cheap; merge scales with chunk count. Fixture smoke passed 9/9 checks across three runs. M4B was valid media but had no chapter markers. Real-provider speed remains NOT_TESTED. See `docs/tts-performance-measurements.md`.

## Export/Backup Results

Exports completed in 94-106 ms median. Backup was synchronous and took 11.4-17.5 seconds. Backup should become job-backed before dataset growth makes request timeout or operator ambiguity worse.

## Desktop UI/UX Findings

Desktop hierarchy, navigation, and Reader typography are strong. Density and repeated controls should be reduced selectively, not redesigned wholesale. The install prompt overlays content until dismissed.

## Mobile UI/UX Findings

Two blocking overlaps were fixed. The two-column library remains cramped, import steps are too tall/dense, Reader controls consume substantial viewport height, and touch targets remain small. See `docs/live-ui-ux-audit.md`.

## Accessibility Findings

Visible names and labels were present in measured pages, but many mobile controls are below 44 px. Heading progression, focus trapping/return, contrast, and reduced motion need dedicated follow-up. No WCAG compliance claim is made.

## Security Regression Results

- Unauthenticated books/audio/export/backup: denied with 401.
- Provider keys: masked/no raw key field.
- Loopback URL preview: blocked.
- Traversal request: blocked.
- Secret backup without encryption: blocked.
- Internal chapter paths: leak reproduced, then narrowly fixed and covered by a passing regression test.

## LIVE_AUDIT_FIX_APPLIED

### Mobile PWA Prompt

- Issue: install prompt intercepted the Import CTA.
- Evidence: Playwright pointer interception at 390x844.
- Fix: offset prompt above the fixed mobile bar.
- Tests: CSS regression test and completed post-fix browser run.
- Risk: low.

### Mobile Reader Controls

- Issue: chapter navigation covered the QA/mode row.
- Evidence: Playwright pointer interception at 390x844 and 360x740.
- Fix: separate vertical positions and content padding.
- Tests: CSS regression test and completed post-fix browser run.
- Risk: low.

### Internal Path Leakage

- Issue: authenticated chapter metadata exposed Linux file paths.
- Evidence: live response contained `/home/...` paths.
- Fix: router responses now emit availability markers and clear book cover paths while retaining safe `/book-assets/` references.
- Tests: `test_book_and_chapter_metadata_do_not_expose_internal_paths`; security file passed 25 tests.
- Risk: low-medium because frontend uses path fields as availability flags; full verification is required.

## RECOMMENDATION_ONLY

### P1 DB Lifecycle and Library Query

- Evidence: 9.346 ms connection setup; 0.65-0.74 s lists at 59 books.
- Impact: all DB-backed routes and future scale.
- Solution: startup-scoped migrations plus aggregate library repository query.
- Scope: medium; acceptance is bounded query count and materially lower 59-book timing.

### P1 Multi-Chapter Transaction

- Evidence: 120 chapters took 5.62 s while 4.9 MB one-chapter import took 0.80 s.
- Impact: long blocking import and inaccurate perceived progress.
- Solution: bounded transaction with rollback and duplicate validation before writes.
- Scope: medium; acceptance is 120-chapter synthetic commit under 1.5 s locally without changing duplicate behavior.

### P1 Job-Backed Backup

- Evidence: 11.4-17.5 s synchronous requests.
- Impact: timeout and unclear failure/retry.
- Solution: tracked background job with protected artifact result.
- Scope: medium.

### P1 Reader Data Contract and QA

- Evidence: raw modes disabled; duplicate calls; QA up to 599 ms/5,182 nodes.
- Impact: missing workflow and long interaction.
- Solution: explicit raw contract, single request owner, progressive QA rendering.
- Scope: medium-high.

### P2 Mobile Library and Accessibility

- Evidence: cramped two-column 390 px screenshot and 19-22 small controls.
- Impact: readability and touch errors.
- Solution: one-column compact cards below a tested breakpoint and 44 px controls.
- Scope: small-medium.

## Modularization Readiness

Reader split: yes, after P1 correctness and request fixes. Import split: yes later for ownership/testing, not speed. Backend split: yes incrementally after connection/transaction policy is explicit. CSS split: yes only after screenshot coverage. See `docs/modularization-readiness.md`.

## Prioritized Roadmap

- P0: no remaining known unauthenticated access or destructive-data blocker; path leak fix must remain green.
- P1: DB startup/connection lifecycle, aggregate library query, multi-chapter transaction, job-backed backup, Reader raw/request/QA fixes, M4B marker decision.
- P2: Reader optional-panel split, Import source modules, domain repositories, mobile library/accessibility, CSS feature boundaries.
- P3: bundle analyzer, visual polish, broader low-end-device and WAN benchmarks.

## Tests and Validation

- Baseline before P1: backend 641 passed, frontend 603 passed, E2E 5 passed, `scripts/verify.sh` exit 0.
- Audit targeted security: 34 passed in Linux; patched canonical security file: 25 passed.
- New mobile CSS tests: 2 passed on Linux.
- `/mnt/c` targeted Vitest worker timed out before running tests; classified as WSL-mounted-filesystem environment failure.
- Final full verification is recorded after report generation.

## Remaining Unknowns

Real-provider TTS speed/cost, low-end Android memory, formal accessibility/contrast, production WAN behavior, production-size backup, restore drill, cache reuse speed, M4B player compatibility, and large private-catalog source behavior remain unknown.

## Final Recommendation

Keep the current architecture and product design. Execute a focused P1 performance/correctness phase before modularization: DB lifecycle, aggregate library query, import transaction, backup job, and Reader data/request ownership. Then split Reader first, Import second, backend repositories third, and CSS last, preserving the verified single-operator security model.
