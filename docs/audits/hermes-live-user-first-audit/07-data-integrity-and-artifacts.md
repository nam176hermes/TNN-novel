# Data Integrity and Artifacts

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Production read-only checks

- SQLite integrity: `ok`.
- Foreign-key violations: `0`.
- Tables: `41`.
- Books: `6`.
- Active chapters: `754`.
- Duplicate chapter keys: `0`.
- Artifact paths checked: `1,773`.
- Missing artifacts: `0`.
- Zero-byte artifacts: `0`.
- Outside-root artifacts: `0`.
- Symlink artifacts: `0`.

[Source] read-only SQLite URI `mode=ro` and artifact stat audit inside `novel-tnn-wsl-api-1`

## Job consistency

No terminal job lacked a completion timestamp. No completed translation or TTS job lacked its expected output contract. No active or stale leases were observed. [Source] read-only production invariants

## Fresh restore comparison

The newest encrypted backup restored to an isolated root with database integrity `ok`, foreign-key count `0`, 1,774 artifact paths validated, 6 books, and 760 chapters. The difference from active production chapter count reflects backup contents and chapter-state counting boundaries, not a failed restore. [Source] fresh restore validation JSON

## Verdict

Data integrity: **GO**. No destructive database action was performed.
