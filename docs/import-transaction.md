# Reviewed Text Import Transactions

## Stages

The reviewed paste/TXT commit path has three explicit stages.

1. Validation and planning validates every chapter, resolves raw/translated fields, computes source hashes, loads active target chapters in one query, and classifies each item as `ADD`, `SKIP`, or `REPLACE`. No book, chapter, or final content file is created during payload validation.
2. Transactional mutation stages content under `data/.import-staging`, starts `BEGIN IMMEDIATE`, re-reads active chapters, rejects stale replacement decisions, moves staged files to unique final names, writes all chapter rows through one connection, and commits once.
3. Post-commit follow-up runs glossary extraction and deterministic QA outside the SQLite write transaction. A follow-up failure returns a sanitized warning and does not misreport the committed import as failed.

The endpoint does not currently accept an optional translation/TTS action. P2B therefore did not add job creation or change provider behavior.

## Transaction Ownership

`PipelineService.import_reviewed_text_plan()` owns one short-lived connection and the explicit begin/commit/rollback boundary. The transaction-aware database helpers accept that connection and never commit independently. Existing standalone chapter CRUD functions retain their prior transaction behavior.

No global write connection or SQLite pool was introduced.

## Duplicate Revalidation

Active chapters are fetched in one indexed query and indexed in memory by chapter number and source hash. The same classification is run before staging and after `BEGIN IMMEDIATE`.

If the action, target chapter ID, or existing chapter fingerprint changes between those checks, the commit is rejected and the operator must preview again. The fingerprint includes title, content paths, source hash, status, translation timestamp, and deletion state. This prevents a stale overwrite from silently replacing a concurrent manual edit.

Explicit `overwrite` remains required. `skip` preserves existing content. Repeated chapter numbers inside one reviewed batch retain the legacy sequential behavior, including an explicit in-batch overwrite updating the ID inserted earlier in the same transaction.

## Rollback And Files

Database exceptions roll back the new book, all chapter inserts, and all chapter updates. Staged and newly finalized files are removed on handled failures. A partial file move is also cleaned before the exception escapes.

SQLite cannot atomically commit filesystem renames. A process kill between final file movement and the SQLite commit can still leave an unreferenced final file. Existing files replaced by an approved overwrite are retained rather than destructively deleted during this phase. A future safe artifact cleanup tool should identify unreferenced files before deletion.

## Result Semantics

`book_id`, title, content kind, chapter count, imported/skipped/overwritten counts, chapter IDs, and warnings retain their existing response shape. Counts are populated from operations that reached the successful commit. Skipped items do not appear in `chapter_ids`, matching prior behavior.

Post-commit exception text is not returned. The warning tells the operator that content was saved and that server logs should be checked, without exposing stack traces or internal paths.

## Isolation

Tests and benchmarks create fresh synthetic databases and content directories. They do not copy or write the operator database. Use the benchmark with an explicit Linux work root:

```bash
.venv/bin/python scripts/benchmark_import_transaction.py \
  --counts 1,10,120,500 \
  --runs 3 \
  --large-bytes 4900000 \
  --work-root /home/$USER/novel-tnn-p2b-fixtures \
  --output output/p2b/import-after-linux.json
```

Without `--work-root`, Python may inherit a Windows-backed temporary directory even when the checkout is under `/home`; such results must not be labeled Linux-filesystem measurements.
