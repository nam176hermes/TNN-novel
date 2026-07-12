# P0A Artifact Path Migration Implementation Note

## Current Status

`P0A_FIX_APPLIED` covers the canonical resolver, approved path registry, default-dry-run migration tool, copied-database apply safeguards, backup no-event gate, runtime compatibility, status path redaction, active runbook cleanup, and regression tests.

Operator database result: `APPLIED_AND_VERIFIED_2026-07-12`.

The live maintenance run used only the fresh evidence under the protected run
directory created on 2026-07-12. Earlier apply reports and hashes were treated
as historical and were not reused. The first maintenance baseline hash changed
while the SQLite backup API consolidated the database/WAL state, so it was
invalidated before dry-run or rehearsal review. All later gates used the new
stable baseline.

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

The controlled implementation, copied-database rehearsal, and operator apply
passed. All 12,151 approved active values mapped deterministically, every
proposed file existed beneath the configured data root, no artifact was
rewritten, and second rehearsal/live applies updated zero rows. Reader, cover,
audio, TTS, export, protected-access, status-redaction, and mobile browser
checks passed after restart without the legacy-root fallback.

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
- Reviewed maintenance/copy SHA-256: `28274440...410977c`.
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

- Backup: `novel-pipeline-backup-20260712-122645.tar.gz`.
- Created: 2026-07-12 12:26:45 local time.
- Archive size: 5,602,481,822 bytes.
- Archive SHA-256: `12bc81fc...7320ed29`.
- Manifest version: 2; 28,864 files/checksums; 6,259,835,838 source bytes.
- Included: database, uploads, covers, book assets, glossary/QA, managed
  sources, non-secret settings, audio, and exports.
- Excluded: secrets and job logs. Secrets included: false.
- Restore drill: passed; restored SQLite integrity: `ok`.
- All 28,864 restored file size/checksum entries matched the manifest.
- Direct rollback copy: 47,079,424 bytes, SHA-256
  `28274440...410977c`, integrity `ok`, foreign-key violations 0.
- Protected rollback mapping: 12,151 exact metadata mappings,
  operator SHA-256 `909c55e1...c903160b`, mode `0600` on a mode `0700`
  Linux directory.

The archive, direct database copy, and exact rollback mapping remain outside
the repository. Restoration requires stopping all writers before replacing
the database. No encryption passphrase or private content appears here.

## Copied-DB Rehearsal

Final copied apply run `4ba6c9b2-cd14-4bf2-8c72-9333060cf3c8` updated exactly
12,151 approved values in one `BEGIN IMMEDIATE` transaction. Post-apply
integrity was `ok`, foreign-key violations were 0, all unapproved table hashes
were unchanged, and the only row-count change was one safe migration event.
All eleven approved columns then contained zero active old-root matches. The
rehearsal also exposed and fixed a WAL post-hash audit race before live apply;
the final tool checkpoints/truncates committed WAL before reporting its hash.

## Idempotency Result

The post-apply dry-run proposed zero updates. Second copied apply run
`ede6e8de-6301-4955-ac2d-79ac8ed92383` updated zero rows and left the copied
database hash unchanged at `b25907f0...9b34da5`. The second operator apply run
`34b936b3-7738-471d-8368-4fa06227d795` also updated zero rows.

## Operator Apply Result

`P0A_FIX_APPLIED`. With API/workers stopped, operator apply run
`15ab8d7f-91f2-43b1-a09d-3fab4886db07` migrated exactly 12,151 approved rows.
Reviewed pre-apply SHA-256 was `28274440...410977c`; checkpointed post-apply
SHA-256 was `78b63908...141e0a0`. Immediate integrity was `ok`, foreign-key
violations were 0, the post-apply dry-run reported zero remappable/unresolved
values, and the second apply updated zero rows. Normal startup/auth activity
may legitimately change the later operator DB file hash, so the recorded
apply hash remains the durable maintenance evidence.

## File Identity Checks

Pre/post size and SHA-256 matched for representative raw, translated, HTML,
cover, chapter-audio, TTS MP3, and TTS report artifacts. The cover probed as a
JPEG and representative MP3s passed `ffprobe`. Backup checksum samples also
matched raw, translated, covers, book assets, audio, and exports. Migration
changed SQLite metadata only.

## Reader/Cover/Audio/TTS Smoke Results

Against the migrated operator DB after fallback removal and restart:

- unauthenticated library and cover requests returned 401;
- authenticated library, book, chapter list, raw source (4,912 characters),
  translation (4,916), HTML (5,397), cover (137,209 bytes), audio range (206),
  audio/TTS downloads (2,513,884 bytes), export (11,140,711 bytes), and status
  calls succeeded with non-empty representative artifacts;
- Playwright logged in, opened Library, opened a migrated book and Reader, and
  observed non-empty translated content;
- mobile Playwright confirmed the install prompt appears in Library/Status but
  is absent in Reader, Reader content is non-empty, fixed controls do not cause
  horizontal overflow, cover/playlist requests return 200, and service-worker
  caches are v4;
- no old/current absolute root appeared in API/UI output and there were no
  failed non-optional browser requests (view-change QA requests were cancelled);
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
verification passed 696 tests; the complete frontend rerun passed 607 tests in
71 files; frontend typecheck/lint, package consistency, production build, and
copied-DB API/Playwright smokes passed. `git diff --check` passed. The only
warnings were existing dependency deprecations for Python `crypt` and
`pkg_resources`. Real-provider validation ran in dry-run mode and explicitly
reported no provider invocation.

## Remaining Limitations

- The snapshot had no active raw-only chapter for representative live-data
  smoke; automated tests cover that mode.
- Backup/restore remains operationally slow while the data tree resides on the
  Windows-mounted filesystem; the verified archive itself is valid.
- Relative-path schema conversion and a centralized storage architecture are
  `RECOMMENDATION_ONLY` and outside P0A.

## Backup-Operability Readiness

Live maintenance is complete. The verified full archive, successful restore
drill, direct rollback copy, protected mappings, pre/post hashes, integrity
results, and failed-first-rehearsal evidence remain protected outside the
repository. The app is running normally without `ARTIFACT_LEGACY_ROOT`.
