# Data integrity and artifacts


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Database

| Check | Result |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 rows |
| Journal mode | WAL |
| Busy timeout | 5,000 ms |
| Schema revision | `2026-07-14-import-job-persistence-phase5` |
| Duplicate book key | 0 |
| Duplicate active chapter number | 0 |
| Duplicate active canonical URL | 0 |

[Source: evidence/production-data-integrity.json]

## Artifacts

The read-only scan found 798 raw chapters, 739 translations, 6 chapter audio files, 306 TTS WAV chunks, 6 TTS MP3 outputs, 6 TTS reports, and one cover. All declared active paths existed, were non-zero, and resolved inside the data root. There were no partial or temporary artifacts and no escaping symlinks. [Source: evidence/production-data-integrity.json]

Thirteen zero-byte files were rotated logs and one maintenance SQLite WAL, not active Reader, translation, export, or audio artifacts. Historical failed mobile jobs all retained an error field; 13 lacked the newer structured safe-error field and are treated as bounded legacy debt. [Source: evidence/production-failed-job-zero-byte-classification.json]

## Reader and job invariants

- No orphan Reader progress rows.
- No cross-book Reader progress.
- No orphan or duplicate QA reports.
- No non-positive content revisions.
- No completed translation missing its artifact.
- No completed TTS job missing its declared output.

## Non-mutation proof

Database, WAL, and SHM hashes and the audited row counts were identical before and after production read-only checks. The database SHA-256 remained `92cbfe65e2859dfc17fa2e4e224f1d42df0216dfce94af2e23648f4558fde77d`. [Source: evidence/production-data-final-fingerprint.json]

## Verdict

**GO** for data integrity at the audit timestamp. This does not replace continuous backup and artifact monitoring.
