# Data Integrity and Artifact Audit

## Production read-only results

| Check | Result |
|---|---|
| SQLite integrity | `ok` |
| Foreign-key violations | 0 |
| Journal mode | WAL |
| Busy timeout | 5,000 ms |
| Declared foreign keys | 28 |
| Duplicate book/chapter numbers | 0 |
| Temporary artifacts | 0 |
| Partial artifacts | 0 |
| Symlinks under data root | 0 |

[Source: read-only Python and SQLite probe inside production API container]

## Job state inventory

- Mobile jobs: 329 total, 313 completed, 14 failed, 2 interrupted.
- TTS jobs: six completed, all with MP3 and report JSON, none with M4B.
- Missing M4B is not classified as corruption because MP3 is a valid output.

[Source: read-only aggregate query]

## File inventory

The data tree contained 44,574 files totaling about 6.45 GB. Thirteen zero-byte files were limited to rotated logs and one maintenance SQLite WAL. Active referenced chapter and TTS artifact checks found no missing, outside-root, or zero-byte files. [Source: production filesystem aggregate and approved-path checks]

## Connection nuance

A direct audit connection reported `PRAGMA foreign_keys=0`. This setting is connection-local. The database had no violation, so the observation is not classified as a production integrity defect without proof that application connection factories omit enforcement. [Source: direct audit connection; database connection code]

## Restore certification

The fresh encrypted restore drill reported integrity `ok`, zero FK errors, 1,774 validated artifact paths, six books, and 760 chapters. [Source: latest restore validation JSON]

Verdict: GO with limitations.
