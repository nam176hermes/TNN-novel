# P2B Multi-Chapter Import Transaction Optimization

## Executive Summary

P2B replaces per-chapter reviewed-import connections and commits with one bounded transaction. On isolated ext4 fixtures, the 120-chapter service median fell from 366.449 ms after P2A to 24.724 ms with follow-ups stubbed. The authenticated ASGI route measured 144.083 ms median with real glossary follow-up, versus the P1 observation of approximately 5.62 seconds.

No schema redesign, new index, server preview session, chunked upload, ImportPanel split, provider call, translation/TTS execution, or live operator data mutation was performed.

## Root Cause

Before P2B, each reviewed chapter performed a chapter lookup, wrote final files, called standalone `add_chapter()`, and sometimes called `update_chapter_paths()`. Those helpers opened and committed their own connections. A 120-chapter raw fixture produced 243 connections, 122 commit calls, 1,219 traced SQL statements, and 240 duplicate queries even with QA/glossary stubbed.

Payload size was not the cause: the P1 120-chapter request was approximately 96 KB, while a near-4.9 MB single chapter completed much faster.

## Architecture Before

- Target book could be created before all chapter payloads were validated.
- Duplicate detection performed one or more lookups per chapter.
- Every chapter insert/update owned a separate connection and commit.
- A mid-batch SQL failure could leave an incomplete book and committed earlier chapters.
- Content was written directly to final paths before each database mutation.
- Glossary and QA ran inline after each independently committed chapter.

## Architecture After

- All chapter text and mode validation completes before mutation.
- One active-chapter query creates a deterministic in-memory plan.
- Files are written to a unique staging directory.
- One connection starts `BEGIN IMMEDIATE`, reloads target chapters, and rejects stale plans.
- Book creation/update and all chapter writes commit together once.
- Handled SQL/file failures roll back the database and remove staged/new files.
- Glossary/QA run after commit and return sanitized warnings on failure.

## P2B_FIX_APPLIED

### Transaction-aware import helpers

Small connection-aware helpers were added to `app/database/db.py` for book resolution, bounded active-chapter loading, insert, and update. They do not commit. Existing general CRUD functions were not rewritten.

### Bounded duplicate detection

Chapter numbers and non-empty source hashes are indexed in memory after one active-chapter query. The plan is recalculated under the write lock. The existing active chapter-number index supports the target-book lookup; no new index was justified.

`EXPLAIN QUERY PLAN` on the 360-chapter route fixture reported `SEARCH chapters USING INDEX idx_chapters_active_number_lookup (book_id=?)` for the bounded active-chapter load.

### Rollback and stale safety

Controlled tests cover validation failure, trigger-induced constraint failure after a partial insert, second-file finalization failure, and concurrent chapter modification between planning and commit. All database mutations and newly generated files are removed on handled commit failure.

### Safe post-commit warnings

Glossary/QA failures no longer echo arbitrary exception text into API results. The import remains committed and receives a safe warning.

## Filesystem Behavior

The reviewed text path writes raw/translated content files; it is not database-only. P2B stages those files and cleans them on handled failures. Filesystem and SQLite commits cannot be fully atomic across a process crash. Approved overwrite artifacts that are no longer referenced are retained to avoid destructive cleanup without a dedicated reference audit.

## Post-Commit Behavior

Glossary extraction and deterministic QA remain behaviorally unchanged but execute after the write transaction. The endpoint has no optional translation/TTS job request fields, so no job behavior exists to migrate in this phase and no provider work was run.

The measured raw-only 120-chapter follow-up still performs per-chapter glossary repository work: 241 total connections and 121 commits, but outside the import transaction. This is a remaining optimization opportunity, not a write-lock or atomicity defect.

## API And UI Compatibility

The API request and response schemas are unchanged. Existing authentication, 5 MB rejection, raw/translated/both field placement, duplicate error/skip/overwrite behavior, warning shape, and book/chapter links remain covered. No frontend source or layout changed.

## Before/After Performance

Canonical measurements used synthetic data under `/home/thenam176/Novel-TNN-P2B-audit-20260711` on ext4, three samples per case. Operator data was not copied.

| Fixture | Before P2B median | After median | After transaction |
| --- | ---: | ---: | ---: |
| 1 chapter | 8.504 ms | 5.938 ms | 3.076 ms representative |
| 10 chapters | 35.744 ms | 7.207 ms | 2.982 ms representative |
| 120 chapters | 366.449 ms | 24.724 ms | 8.153 ms representative |
| 500 chapters | Not measured | 94.859 ms | 32.334 ms representative |
| 4.9 MB single chapter | P1 approximately 800 ms | 20.917 ms | 2.676 ms representative |

The P1 5.62-second 120-chapter route included pre-P2A setup and mounted-filesystem costs. The new authenticated ASGI route with real glossary follow-up measured 233.297, 142.758, and 144.083 ms; median 144.083 ms.

With actual glossary follow-up, the 120-chapter service median was 149.771 ms. Fixture synthesis/provider speed is not involved.

## Connection, Query, And Commit Counts

| Fixture | Before connections / commits | After transaction connections / commits | Before duplicate queries | After duplicate queries |
| --- | ---: | ---: | ---: | ---: |
| 1 chapter | 5 / 3 | 1 / 1 | 2 | 1 |
| 10 chapters | 23 / 12 | 1 / 1 | 20 | 1 |
| 120 chapters | 243 / 122 | 1 / 1 | 240 | 1 |

The 120-chapter traced SQL count fell from 1,219 to 139. The remaining 120 insert statements scale with committed chapters; connection, transaction, commit, and duplicate-query counts are bounded.

## Files Changed

- `app/database/db.py`
- `app/mobile_api/services/pipeline_service.py`
- `tests/test_import_transaction_performance_contracts.py`
- `scripts/benchmark_import_transaction.py`
- `docs/import-transaction.md`
- `docs/import-performance-measurements.md`
- `docs/p2b-import-transaction-implementation-note.md`

## Tests Run

Final validation:

- new transaction performance contracts: 9 passed;
- import wizard, ebook, URL, metadata, and mobile security targeted suite: passed;
- pyflakes for changed Python files: passed;
- Linux synthetic benchmark: passed for 1, 10, 120, 500, and 4.9 MB cases;
- authenticated 120-chapter ASGI route benchmark: HTTP 200 on all three runs;
- `scripts/verify.sh`: exit 0;
- full backend: 656 passed, 2 baseline deprecation warnings in 820.88 seconds;
- full frontend: 70 files and 605 tests passed in 517.58 seconds;
- production build: passed, 1,841 modules, 17.48 seconds in the full verify run;
- Playwright E2E: 5 passed, including import wizard and library/reader workflows;
- `pip check`, environment check, typecheck, pyflakes, shell syntax checks, and `git diff --check`: passed;
- operator database SHA-256, size, and mtime remained unchanged.

## Remaining Limitations

- Post-commit glossary extraction remains per chapter and accounted for most of the difference between 24.724 ms transaction-focused and 149.771 ms full-service medians.
- A hard process kill during the filesystem-rename/SQLite-commit gap can leave an unreferenced file.
- Existing replaced files are retained; safe unreferenced-artifact cleanup requires a separate read-only inventory and operator-approved deletion phase.
- No low-end Android import benchmark was added.

## RECOMMENDATION_ONLY

Add a bounded glossary extraction API only if future profiling shows the 150 ms local follow-up cost is user-visible at larger chapter counts. Server-side preview sessions and chunked uploads remain unjustified under the current 5 MB limit.

## P2C Readiness

P2B meets the measured import target without broad modularization. P2C may proceed only after full verification is green and a reviewed P2B commit exists. It should use this transaction seam rather than splitting all of `db.py`, `pipeline_service.py`, or `ImportPanel`.
