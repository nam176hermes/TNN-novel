# P04 — Source Chapter Idempotency Migration

## Scope

P04 makes source-backed chapter import idempotent. It does not change import
queueing, retry policy, source parsing, or the duplicate strategy used by the
reviewed ebook-import workflow.

The repository uses raw SQLite (`sqlite3`) with in-code, idempotent migrations:

- canonical DDL: `app/database/schema.py`
- migration/backfill entrypoint: `app/database/db.py:init_db()`
- schema version: `2026-07-14-import-idempotency-phase4`

## Canonical identity

For a source-backed chapter, identity is:

```text
(resolved book id, adapter_id, canonical_chapter_url)
```

`resolved book id` comes from the existing normalized `book_key` resolver. The
book also stores `canonical_source_url` for provenance. URLs are canonicalized
by P02's `app.security.url_policy.validate_fetch_url()` with DNS resolution
disabled for persistence/backfill; this canonicalizes scheme, hostname/IDNA,
default port, path, and fragment without making migration-time network calls.

The active-row SQLite unique index is:

```sql
CREATE UNIQUE INDEX idx_chapters_active_canonical_identity
ON chapters(book_id, adapter_id, canonical_chapter_url)
WHERE deleted_at IS NULL AND adapter_id != '' AND canonical_chapter_url != '';
```

Manual/paste imports without an adapter plus canonical chapter URL retain the
existing chapter-number duplicate behavior. They do not claim a source
identity that they do not possess.

## Added fields

`books` gains:

- `canonical_source_url TEXT DEFAULT ''`

`chapters` gains:

- `canonical_chapter_url TEXT DEFAULT ''`
- `content_hash TEXT DEFAULT ''`
- `source_updated_at TEXT DEFAULT ''`
- `last_import_operation TEXT DEFAULT ''`
- `content_revision INTEGER NOT NULL DEFAULT 1`

`source_hash` remains for backward compatibility. P04 writes the normalized
content SHA-256 to both `source_hash` and `content_hash` for source imports.

## Upsert outcomes

Within one `BEGIN IMMEDIATE` transaction, source-backed `import_from_text()`
resolves or creates the book and stores the chapter:

| Existing identity | Content hash | Outcome |
|---|---|---|
| none | n/a | `created` |
| present | unchanged | `skipped_duplicate` |
| present | changed | `updated`, with `content_revision + 1` |

A concurrent writer that already created the matching identity is re-read and
reported as `skipped_duplicate` rather than returning a server error.

The incoming raw artifact is deleted after a skip or DB rollback. Updated raw
artifacts are not automatically deleted: retention/cleanup must remain an
explicit, separately approved operation.

## Safe legacy backfill

At `init_db()` the migration:

1. adds missing fields using column-existence checks;
2. backfills `content_hash` from `source_hash` and initializes revision to 1;
3. canonicalizes existing source/book URLs without network I/O;
4. preserves all legacy rows;
5. when two legacy active rows would share an identity, keeps the oldest row's
   canonical identity and marks the later row `backfill_identity_conflict`.

The conflict row remains readable and retains its original `source_url`; it is
not deleted, merged, or overwritten. This permits the new unique index without
silently losing operator data.

## Rollback

This migration is additive. Application rollback is safe when the previous
application version reads the database because it ignores the new columns and
index.

Do not drop fields or the index from a production database as a routine
rollback. If an emergency schema rollback is required:

1. stop the application and take a verified SQLite backup;
2. confirm no deployed code depends on the new canonical identity fields;
3. drop only `idx_chapters_active_canonical_identity` if necessary;
4. leave added columns in place unless a separately tested offline database
   rebuild is approved.

Dropping columns in SQLite requires table rebuild and is destructive-risk work;
it is deliberately out of scope for P04.

## Verification

Run with the repository's isolated test environment:

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
.venv/bin/python -m pytest -q -s tests/test_import_idempotency.py
scripts/verify.sh
git diff --check
```
