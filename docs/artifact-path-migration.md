# Artifact Path Migration

## Purpose

P0A repairs active filesystem metadata after the project moved away from the historical root `/home/thenam176/novel_pipeline`. It changes approved SQLite path values only. It does not move, delete, regenerate, or rewrite private artifacts.

Resolve the active checkout and configured data root before every command:

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export DATA_DIR="${DATA_DIR:-$REPO_ROOT/data}"
export DB_PATH="$DATA_DIR/pipeline.db"
cd "$REPO_ROOT"
```

Do not assume that the repository directory and configured data directory are the same. `app.config.settings.resolved_data_dir` is authoritative.

## Approved Metadata

The migration registry is defined once in `app/storage/artifact_paths.py`. It covers:

- `books.cover_path`;
- chapter raw, cleaned, translated, rich HTML, and audio paths;
- TTS MP3, M4B, report, WAV chunk, and MP3 chunk paths.

Deleted chapters are excluded. Logs, audit text, historical notes, URLs, commands, provider endpoints, backup manifests, and archived reports are not migrated.

## Containment Rules

The resolver accepts only a declared artifact class. It rejects blank metadata, URLs, unrelated absolute paths, traversal, paths outside `$DATA_DIR`, symlink escapes, missing files when verification is required, and directories supplied as file artifacts. The only compatibility remap is the exact configured legacy root; arbitrary prefix or substring replacement is forbidden.

Set `ARTIFACT_LEGACY_ROOT` only for the bounded compatibility period:

```bash
export ARTIFACT_LEGACY_ROOT=/home/thenam176/novel_pipeline
```

Remove it after the operator migration reports zero approved active old-root values and representative Reader, cover, audio, and TTS checks pass.

## Dry Run

Dry-run is the default and opens SQLite read-only:

```bash
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path "$DB_PATH" \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$DATA_DIR" \
  --report-dir output/p0a-artifact-path-migration/dry-run \
  --verify-files \
  --rollback-sql-output output/p0a-artifact-path-migration/protected-rollback-mapping.json
```

The summary reports contain record IDs, relative suffixes or hashes, counts, sizes, and classifications. They exclude chapter text, secrets, provider credentials, and absolute roots. The explicitly requested protected rollback mapping contains the exact old/new path metadata required for rollback and requests mode `0600` where the filesystem supports POSIX permissions.

## Fresh Backup

P0A backup creation must not add an operational-event row before rehearsal:

```bash
BACKUP_RECORD_EVENT=0 INCLUDE_ENV=0 \
BACKUP_INCLUDE_AUDIO=1 BACKUP_INCLUDE_EXPORTS=1 \
scripts/backup-local.sh
```

Verify the archive is non-zero, inspect its sidecar manifest, check `backup_format_version`, confirm secrets are excluded, hash the archive, and run `scripts/ops.py restore-drill`. Create a separate SQLite-consistent rollback copy with the SQLite backup API. A plain file copy is not the canonical backup for a live WAL database.

## Rehearsal

Use the consistent database copy, never `$DB_PATH`:

1. Hash the copied database.
2. Run dry-run and review all unresolved or ambiguous active records.
3. Run `--apply` with `--backup-confirmation verified:<backup-id>` and `--expected-db-sha256 <reviewed-copy-hash>`.
4. Re-hash and run dry-run plus apply a second time.
5. Require zero path updates on the second apply.
6. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
7. Compare table row counts and approved-column-only diffs.
8. Hash representative raw, translated, HTML, cover, audio, and TTS artifacts before and after.
9. Start an isolated application against the rehearsed database and test protected workflows.

Missing and ambiguous paths are reported, never guessed. An unresolved active artifact blocks operator apply unless the operator explicitly accepts it with `--allow-missing` after reviewing the report.

## Operator Apply Gate

Plan or implementation approval is not operator-apply approval. Before live apply:

- verify the fresh backup and direct DB copy;
- require a passed copied-DB rehearsal;
- review unresolved records;
- stop API and workers or enter maintenance mode;
- confirm no process holds the database;
- recheck the exact reviewed DB SHA-256;
- verify disk space and the final command.

If the hash changed, abort and regenerate dry-run and rehearsal evidence. After apply, rerun integrity, foreign keys, dry-run, representative workflows, and artifact hashes before restarting normal work.

## Rollback

If post-apply validation fails, stop writers and restore the consistent direct database copy or the verified system backup. Do not regenerate content or apply ad hoc updates. Preserve the failed run report, pre/post hashes, protected mapping, integrity output, and backup manifest for review.

## Prevention

New artifact writes must be derived from the configured data root. Active runbooks use `$REPO_ROOT`, `$DATA_DIR`, or repository-relative commands. The old root may remain only in historical evidence and this migration guide. Converting the whole schema to relative paths is `RECOMMENDATION_ONLY`, not P0A scope.
