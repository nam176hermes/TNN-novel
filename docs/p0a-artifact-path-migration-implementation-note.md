# P0A Artifact Path Migration Implementation Note

## Current Status

`P0A_FIX_APPLIED` covers the canonical resolver, approved path registry, default-dry-run migration tool, copied-database apply safeguards, backup no-event gate, runtime compatibility, status path redaction, active runbook cleanup, and regression tests.

Operator database result: `NOT_APPLIED_AWAITING_EXPLICIT_APPROVAL`.

## Baseline

- Branch baseline: `master` after deep-audit documentation commit `6e4436d`.
- Implementation branch: `p0a-artifact-path-migration`.
- Historical source prefix: `/home/thenam176/novel_pipeline`.
- Current storage: configured `$DATA_DIR`, defaulting to `$REPO_ROOT/data`.
- Database: `$DATA_DIR/pipeline.db`.
- Initial read-only database integrity: `ok`.
- Initial foreign-key violations: `0`.
- Paid translation and TTS providers: excluded.

The deep audit found deterministic candidates in active raw, translated, HTML, cover, chapter-audio, and TTS metadata. The implementation inventories all eleven approved path-bearing fields rather than trusting only the audit totals.

## Safety Gates

- Dry-run opens SQLite with `mode=ro` and is the CLI default.
- Apply requires `--verify-files`, a `verified:` backup confirmation, and an exact reviewed database SHA-256.
- Apply uses `BEGIN IMMEDIATE`, parameterized values, compare-before-update predicates, integrity and foreign-key checks, and rollback on any exception.
- Deleted chapters, unrelated fields, audit text, notes, URLs, commands, and manifests are excluded.
- The resulting path must resolve beneath configured storage; traversal and symlink escapes are rejected.
- Reports exclude private content and secrets. Exact rollback path metadata is written only to the explicitly requested protected mapping.
- A second copied-DB apply must update zero path rows.

## Rollback Plan

Rollback evidence consists of a fresh system backup, sidecar manifest, archive checksum, restore drill, SQLite-consistent direct database copy, dry-run summaries, protected mapping, pre/post DB hashes, integrity results, and representative artifact hashes. Post-apply failure requires stopping writers and restoring the consistent database copy or verified archive. Content regeneration is prohibited.

## Excluded Work

- Content regeneration or deletion.
- Data-tree relocation.
- Schema-wide relative-path conversion.
- Database modularization.
- Backup job redesign.
- Reader or status-page redesign.
- Provider, TTS engine, glossary, or unrelated architecture changes.

Schema-wide relative paths and removal of absolute storage metadata are `RECOMMENDATION_ONLY` after P0A has a stable post-migration window.

## Executive Summary

The controlled implementation and copied-database rehearsal passed. All 12,151
approved active values mapped deterministically, every proposed file existed
beneath the configured rehearsal data root, no artifact was rewritten, and a
second copied-DB apply updated zero rows. Reader, cover, audio, TTS, export, and
protected-access checks passed against the migrated copy. The live operator
database was not migrated; its hash remained unchanged throughout this phase.

## Affected Tables And Columns

The dry-run inventory below is restricted to active records (deleted chapters
are excluded). `Missing before` means the stale stored absolute path did not
exist; `existing after` means its exact suffix existed beneath the configured
data root.

| Table.column | Active records | Old-root | Blank | Current | Missing before | Existing after | Migrate | Kind |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `books.cover_path` | 15 | 3 | 12 | 0 | 3 | 3 | yes | file |
| `chapters.raw_text_path` | 4,159 | 4,159 | 0 | 0 | 4,159 | 4,159 | yes | file |
| `chapters.cleaned_text_path` | 4,159 | 0 | 4,159 | 0 | 0 | 0 | yes | file |
| `chapters.translated_text_path` | 4,159 | 4,159 | 0 | 0 | 4,159 | 4,159 | yes | file |
| `chapters.content_html_path` | 4,159 | 3,464 | 695 | 0 | 3,464 | 3,464 | yes | file |
| `chapters.audio_path` | 4,159 | 8 | 4,151 | 0 | 8 | 8 | yes | file |
| `tts_jobs.output_mp3_path` | 8 | 8 | 0 | 0 | 8 | 8 | yes | file |
| `tts_jobs.output_m4b_path` | 8 | 0 | 8 | 0 | 0 | 0 | yes | file |
| `tts_jobs.report_json_path` | 8 | 8 | 0 | 0 | 8 | 8 | yes | file |
| `tts_chunks.wav_path` | 342 | 342 | 0 | 0 | 342 | 342 | yes | file |
| `tts_chunks.mp3_path` | 342 | 0 | 342 | 0 | 0 | 0 | yes | file |

The full schema/text-field scan found no old-root matches outside these
approved fields. The following lookalikes are intentionally excluded:

- `books.source_url`, `chapters.source_url`, managed-source URLs, catalog URLs,
  and provider `base_url` values are external URLs, not artifacts.
- `ebook_import_runs.filename` is an upload basename; its `warnings_json` is a
  historical report. Neither contained the old root.
- job/event/QA/cache/reader JSON, logs, model names, and parser configuration
  are free-form operational or historical metadata, not active lookup paths.
- backup manifests and archived reports are immutable historical evidence.
- `$DATA_DIR`, TTS model/reference settings, export roots, and directory layout
  are configuration-owned; no database settings table stores the stale root.

## Dry-Run Results

- Migration version: `p0a-artifact-paths-v1`.
- Reviewed copied-DB SHA-256: `f9b10c4f...eee80ca`.
- Remappable: 12,151.
- Unresolved: 0.
- Containment failures: 0.
- Collision warnings: 8. Each is an intentional shared reference where a
  chapter audio field and its TTS output field point to the same MP3; no two
  distinct files competed for one target.
- Dry-run database hash before/after: unchanged.

## Remappable Counts

Raw 4,159; translated 4,159; rich HTML 3,464; covers 3; chapter audio 8;
TTS final MP3 8; TTS report 8; TTS WAV chunks 342. Cleaned, M4B, and chunk-MP3
fields were blank and required no update.

## Missing And Ambiguous Counts

All audited active old-root paths mapped deterministically. Missing after
remap: 0. Ambiguous suffixes: 0. Duplicate candidate files: 0. Path escapes:
0. Optional blank metadata remained blank and was not marked available.

## Resolver And Containment Rules

One resolver and one approved-field registry serve migration and runtime
compatibility. They reject blank values before constructing `Path`, URLs,
unrelated absolute roots, traversal, resolved paths outside `$DATA_DIR`,
symlink escapes, missing files when verification is requested, and directories
where a file is required. Already-current values are unchanged. The temporary
fallback accepts only the configured exact historical root and emits one
bounded diagnostic; remove `ARTIFACT_LEGACY_ROOT` after live migration and
post-apply smoke checks.

## Backup And Rollback Evidence

- Backup: `novel-pipeline-backup-20260711-235102.tar.gz`.
- Created: 2026-07-11 23:51:02 local time.
- Archive size: 5,602,479,376 bytes.
- Archive SHA-256: `1463c34b...8b04f56`.
- Manifest version: 2; 28,864 files/checksums; 6,259,819,454 source bytes.
- Included: database, uploads, covers, book assets, glossary/QA, managed
  sources, non-secret settings, audio, and exports.
- Excluded: secrets and job logs. Secrets included: false.
- Restore drill: passed; restored SQLite integrity: `ok`.
- Direct SQLite-consistent rollback copy: 47,063,040 bytes,
  SHA-256 `f9b10c4f...eee80ca`, integrity `ok`, foreign-key violations 0.
- Protected rollback mapping: 12,151 exact metadata mappings,
  SHA-256 `3a7554b2...fbef4c`, mode `0600` on a mode `0700` Linux directory.

The archive, direct database copy, and exact rollback mapping remain outside
the repository. Restoration requires stopping all writers before replacing
the database. No encryption passphrase or private content appears here.

## Copied-DB Rehearsal

First copied apply run `a72b08c3-d743-4e47-8370-b7a5ba500027` updated exactly
12,151 approved values in one `BEGIN IMMEDIATE` transaction. Post-apply
integrity was `ok`, foreign-key violations were 0, all unapproved table hashes
were unchanged, and the only row-count change was one safe migration event.
All eleven approved columns then contained zero old-root matches.

## Idempotency Result

The post-apply dry-run proposed zero updates. Second copied apply run
`cbcfec8a-3bec-4b81-a8ec-44c07566445d` updated zero rows and left the copied
database hash unchanged at `cb9519c6...f19d58`.

## Operator Apply Result

`NOT_APPLIED_AWAITING_EXPLICIT_APPROVAL`. The operator database remained at
SHA-256 `fc9bdefd...88606` before backup, after backup, and after rehearsal.
An active application process was also observed, so the maintenance-mode/no-
writers gate is not satisfied. A later live apply must recheck the complete
hash and repeat review if it differs.

## File Identity Checks

Pre/post size and SHA-256 matched for representative raw, translated, HTML,
cover, chapter-audio, TTS MP3, and TTS report artifacts. The cover probed as a
JPEG and representative MP3s passed `ffprobe`. Backup checksum samples also
matched raw, translated, covers, book assets, audio, and exports. Migration
changed SQLite metadata only.

## Reader/Cover/Audio/TTS Smoke Results

Against the migrated copied DB:

- unauthenticated library and cover requests returned 401;
- authenticated library, book, chapter list, raw source, translation, HTML,
  cover, audio stream/download, TTS status/download, export, and status calls
  returned 200 with non-empty representative artifacts;
- Playwright logged in, opened Library, opened a migrated book and Reader, and
  observed non-empty translated content;
- no old root appeared in browser console output and there were no failed
  non-optional requests (optional absent QA reports returned expected 204s);
- no active raw-only chapter existed in this snapshot, so raw-only behavior is
  covered by automated integration fixtures rather than a live data sample.

## Status Path Redaction

`/api/system/status` now returns availability, sizes, storage health, and a
logical label without `database_path`, `data_dir`, or any absolute host path.
The status UI renders only those safe values. Backend, frontend, and browser
checks cover the redaction.

## Runbook Updates

Active backup, deployment, local operation, and systemd examples use
`$REPO_ROOT`, `$DATA_DIR`, configuration, or neutral deployment paths. The
historical root remains only in migration material and explicitly historical
audit evidence. A regression test rejects it in active code/runbooks.

## Files Changed

The patch is limited to the canonical storage resolver/registry, migration
tool, backup checkpoint/event gates, active Reader/cover/audio/TTS/export path
resolution, narrow status redaction, active runbooks, and tests. No schema,
provider, content, or broad UI redesign is included.

## Tests Run

Targeted resolver, migration, rollback, backup, Reader, export, audio/TTS,
status, security, environment, and frontend tests passed. Final backend
verification passed 692 tests; the complete frontend rerun passed 605 tests in
70 files; frontend typecheck/lint, package consistency, production build, and
copied-DB API/Playwright smokes passed. `git diff --check` passed. The only
warnings were existing dependency deprecations for Python `crypt` and
`pkg_resources`. Real-provider validation ran in dry-run mode and explicitly
reported no provider invocation.

## Remaining Limitations

- Live apply and live post-apply smoke are intentionally pending a separate
  maintenance-window authorization.
- The exact-root runtime fallback is temporary and must be removed after a
  successful live migration stabilization period.
- The snapshot had no active raw-only chapter for representative live-data
  smoke; automated tests cover that mode.
- Relative-path schema conversion and a centralized storage architecture are
  `RECOMMENDATION_ONLY` and outside P0A.

## Backup-Operability Readiness

Ready for a controlled maintenance window: a verified full archive, successful
restore drill, direct SQLite rollback copy, protected exact mapping, hashes,
and rollback procedure exist. Not ready for live apply until writers are
stopped and the operator DB hash matches the reviewed baseline immediately
before execution.
