# Data and workflow certification

## Verdict

Data integrity: **GO**

Core workflows: **GO_WITH_LIMITATIONS** because translation used mocks/local
fixtures and TTS was validated unavailable rather than synthesized.

## Read-only production checks

| Check | Result |
|---|---|
| SQLite `integrity_check` | `ok` |
| Foreign-key violations | 0 |
| Duplicate `(book_id, chapter_number)` | 0 |
| Books | 6 |
| Chapters | 760 |
| Mobile jobs | 332 total: 313 completed, 17 historical failed, 2 historical interrupted |
| Active artifact scan | 1,774 paths, 0 errors |
| Active zero-byte artifacts | 0 |
| Partial/temp artifacts | 0 |
| Symlinks in data root | 0 |

Thirteen zero-byte filesystem entries were operational SQLite WAL/log-rotation
files, not active book, audio, export, or backup artifacts.

## Isolated workflow suites

Focused workflow tests completed 176 passes and covered:

- paste/TXT/EPUB/URL import and idempotency;
- import worker, job state, retry, cancellation, and stale recovery;
- translation with mock/local provider behavior;
- deterministic and glossary QA;
- export;
- backup metadata and protected download;
- restore and restore-drill behavior;
- TTS unavailable and GPU-only enforcement.

An initial focused command named a nonexistent historical test file. The
corrected command used the current test inventory and passed. No application
failure was hidden or suppressed.

## Fresh encrypted-backup restore drill

The newest encrypted production backup was restored to a new temporary root.
The drill did not touch live data and passed:

| Validation | Result |
|---|---|
| SQLite integrity | `ok` |
| Foreign-key violations | 0 |
| Artifact paths scanned | 1,774 |
| Restored books | 6 |
| Restored chapters | 760 |
| Network-isolated API health/readiness | pass |
| Authenticated read-only Reader smoke | pass |

The temporary restored files were removed only after recording aggregate
evidence. The encrypted source backup and production data were not altered.

## TTS contract

On this certification path no supported GPU was exposed. API, worker,
pipeline, and direct-engine tests returned a typed unavailable state and did
not load or synthesize on CPU. Fixture tests remained available without
pretending to be provider timing.

## Safety and exclusions

- No paid provider call.
- No GPU synthesis.
- No production import, translation, export, backup creation, restore, job
  retry, or cancellation.
- No schema migration or destructive cleanup.
- No private title or chapter content appears in the certification package.
