# P2A Database Lifecycle And Library Query Optimization

## Executive Summary

P2A removes schema/migration work from normal SQLite connections and replaces both measured book-list N+1 paths with bounded queries. On an isolated WSL Linux filesystem fixture, normal connection median fell from 11.921 ms to 0.035 ms. The 59-book translated-library route measured 5.188 ms median after the change versus the P1 observed 645-739 ms range.

No schema redesign, ORM, pool, new index, public response field, frontend redesign, provider behavior, or live operator data change was made.

## Root Cause - Connection Overhead

Before P2A, every `get_connection()` call performed WAL negotiation, migration-table setup, the complete legacy migration/check sequence, provider and style seeding, operator seeding, ownership backfill, schema-version recording, commit, and connection setup.

Fresh Linux breakdown over 30 runs:

| Stage | Median |
| --- | ---: |
| Raw connect | 0.083 ms |
| WAL pragma | 0.659 ms |
| Legacy migration/checks | 7.911 ms |
| Provider seed | 0.141 ms |
| Style seed | 0.076 ms |
| Operator seed | 0.120 ms |
| Owner backfill | 0.314 ms |

The repeated migration/check sequence was the dominant cause. `init_db()` also reached migration once through `get_connection()` and then called it again explicitly.

## Root Cause - Library N+1

`PipelineService.list_books()` and `list_translated_book_summaries()` first selected all books, then called `list_chapters()` once for each book. For 59 books this meant 60 logical SELECTs and 60 connections. Because each connection repeated initialization, trace instrumentation observed 29,820 total SQL statements, including schema/setup statements.

The fresh P2A baseline reproduced a 936.776 ms median service time for 59 books. This is consistent with the P1 route observation of approximately 0.65-0.74 seconds; filesystem cache and fixture differences account for the run-to-run range.

## Database Lifecycle Changes

### P2A_FIX_APPLIED

`get_connection()` now performs only row-factory, foreign-key, and busy-timeout setup. `init_db()` explicitly owns WAL configuration, schema/migration work, default seeding, ownership backfill, version recording, and commit.

Legacy migration remains idempotent and runs once per explicit initialization. It runs before the canonical schema script so old tables gain columns required by current indexes.

No global connection is shared. Existing short-lived connection and transaction ownership remain intact.

The root Typer CLI now initializes the database once before normal commands. This preserves standalone CLI safety without restoring migration work to repository connections; `init` and help-only invocation retain their existing behavior.

## Library Query Changes

### P2A_FIX_APPLIED

The general book list now uses one `EXISTS` query against active chapters. The translated library uses one CTE aggregate with window ranking for first/latest translated chapters. Query count is constant as book count grows.

The router and response sanitizers are unchanged. The service still derives safe cover URLs and the router still removes internal cover paths.

## Query Plan Findings

The general list scans the small books table and probes `idx_chapters_active_number` by `book_id`. The aggregate query scans active chapters through `idx_chapters_active_number`, looks up books by primary key, and uses temporary B-trees for window ordering/grouping/final ordering.

At 59 books/590 chapters the aggregate service median was 2.668 ms; at 100 books/1,000 chapters it was 3.872 ms. Temporary sorting is therefore not a measured bottleneck at this scale.

## Index Changes

No index was added. Existing `idx_chapters_active_number` is used by both new query plans. An additional index would be speculative and would add write/migration cost without measured benefit.

## API Compatibility

Response fields, translated detection, active/deleted filtering, counts, first/latest chapter IDs, title/number metadata, ordering, cover URL behavior, authentication, and path sanitization are unchanged.

The repository-level `list_books()` continues to include books with zero chapters. API list filters remain unchanged. Reader progress and last-read values were not present in the library contract and were not added.

## Frontend Compatibility

No frontend code or type changed. Existing library cards continue receiving the same payload shape and navigation identifiers.

## Before/After Performance

Measurements used synthetic databases under `/home/thenam176/Novel-TNN-P2A-audit-20260710`; no `.env` or operator data was copied.

| Measurement | Before | After |
| --- | ---: | ---: |
| Raw SQLite connection median | 0.029 ms | 0.031 ms |
| Project connection median | 11.921 ms | 0.035 ms |
| 59-book translated service median | 936.776 ms | 2.668 ms |
| 59-book translated route median | P1: 645-739 ms | 5.188 ms |
| 59-book general route median | P1: 645-663 ms | 3.195 ms |
| 100-book translated service median | Not measured in P1 | 3.872 ms |

After timings used seven route/service samples except connection setup, which used ten after samples and fifty baseline samples. These local timings are not production latency guarantees.

## Query Count Before/After

| Path at 59 books | Before | After |
| --- | ---: | ---: |
| General list logical SELECTs/connections | 60 / 60 | 1 / 1 |
| Translated library logical SELECTs/connections | 60 / 60 | 1 / 1 |
| Translated trace statements including setup | 29,820 | 3 (2 pragmas + 1 query) |

## Files Changed

- `app/database/db.py`
- `app/main.py`
- `app/mobile_api/services/pipeline_service.py`
- `tests/test_database_db.py`
- `tests/test_database_performance_contracts.py`
- `tests/test_cache_migration.py`
- `tests/test_mobile_api_system_status.py`
- `tests/test_provider_service.py`
- `scripts/benchmark_database_library.py`
- `docs/database-lifecycle.md`
- `docs/backend-performance-measurements.md`
- `docs/p2a-database-library-implementation-note.md`

## Tests Run

The RED phase reproduced all intended failures: request migration, duplicate migration in `init_db()`, and per-book connection growth.

Final validation:

- lifecycle/legacy focused contracts: 7 passed;
- database, library API, ownership, and security targeted suite: 104 passed, 2 known deprecation warnings;
- frontend library and App integration: 30 passed;
- Playwright E2E: 5 passed, including library/Reader workflow;
- production frontend build: passed;
- standalone CLI initialization contracts: 2 passed;
- `scripts/verify.sh`: exit 0;
- full backend: 647 passed, 2 warnings in 811.85 seconds;
- full frontend: 70 files and 605 tests passed;
- final production build: passed in 11.74 seconds;
- pyflakes, typecheck, `pip check`, environment check, and `git diff --check`: passed.

The final full verify took 22 minutes 56 seconds on `/mnt/c`; this is filesystem/tooling duration, not an application performance benchmark. Known warnings remain the passlib `crypt` deprecation and jieba `pkg_resources` warning.

## Remaining Limitations

- Some provider read functions intentionally retain local default-seed safeguards; they are outside the measured library path and were not changed to avoid provider behavior drift.
- Startup initialization remains approximately 10-15 ms warm and can be higher cold. That cost is explicit and process-scoped.
- The aggregate plan uses temporary B-trees. Revisit only with larger copied-database evidence.
- This phase does not add progress/last-read fields or alter zero-chapter visibility in API lists.

## RECOMMENDATION_ONLY

If the library grows well beyond the measured 100-book/1,000-chapter fixture, re-run the benchmark and plan inspection before considering summary tables or new indexes. Do not denormalize based on current results.

## P2B Readiness

The database lifecycle and list-query seams are now explicit enough for the next focused phase. P2B should address the measured multi-chapter import transaction path, not broad database modularization.
