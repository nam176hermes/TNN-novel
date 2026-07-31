# P0A Artifact Path Migration Design

**Status:** Approved on 2026-07-11

**Marker:** `P0A_FIX_APPLIED` applies only to changes delivered by this phase. Longer-term storage redesign is `RECOMMENDATION_ONLY`.

## Goal

Restore active Reader, raw and translated chapter content, rich HTML, covers, chapter audio, and TTS artifacts after a repository-root move by correcting only validated path metadata. The phase must not delete, regenerate, move, or rewrite private artifact files, chapter text, book identity, or chapter identity.

## Baseline And Apply Boundary

The repository baseline is commit `6e4436d` on `master`. The configured data root currently resolves to the repository `data/` directory, and the operator database is `data/pipeline.db`. The known stale root is `/home/thenam176/novel_pipeline`; it is treated as migration input, not as an active runtime root.

All discovery, inventory, hashing, and database inspection must use read-only access. Backup and rehearsal may create new files outside the active data tree. Rehearsal must use a copied database. The operator database must not be updated until all rehearsal gates pass and the operator gives a separate explicit apply approval. A running API or worker holding the database open is an apply blocker, not a rehearsal blocker.

## Selected Approach

Use one canonical artifact-path resolver and one approved-column registry shared by runtime artifact lookup and a dedicated migration tool. This gives runtime readers and the database migration identical old-root recognition, normalization, containment, and rejection behavior.

The alternatives were rejected for this phase:

- A migration-only script would leave runtime path handling inconsistent and provide no narrow compatibility behavior while approval is pending.
- A schema-wide conversion to relative paths would be a broader storage redesign than P0A permits.

## Components

### Canonical Artifact-Path Resolver

The resolver accepts an artifact class, stored value, configured data root, and optional exact old root. Artifact classes define whether the target is a file or directory and which configured subroot is allowed. The resolver:

- rejects blank strings before constructing a `Path`;
- rejects URLs and unrelated absolute paths;
- accepts already-current paths without changing their stored meaning;
- remaps only an exact old-root prefix while preserving the relative suffix;
- normalizes separators plus `.` and `..` components;
- verifies lexical and resolved containment beneath the class-specific allowed root;
- rejects symlink escapes where the existing filesystem makes them detectable;
- rejects directories when a file artifact is required;
- distinguishes metadata missing, file missing, and path outside the allowed root;
- never returns absolute filesystem paths in API response models.

A temporary runtime fallback may resolve the exact known old-root prefix through this resolver. It must emit a bounded warning without private content, accept no other legacy root, and be removed after the approved migration reports zero active old-root values and a post-migration regression window completes.

### Approved Path Registry

The migration registry contains explicit table, primary-key, column, artifact-class, and active-record rules. Initial candidates are:

- `books.cover_path`;
- `chapters.raw_text_path`;
- `chapters.cleaned_text_path`;
- `chapters.translated_text_path`;
- `chapters.content_html_path`;
- `chapters.audio_path`;
- `tts_jobs.output_mp3_path`;
- `tts_jobs.output_m4b_path`;
- `tts_jobs.report_json_path`;
- `tts_chunks.wav_path`;
- `tts_chunks.mp3_path`.

Schema, settings, JSON, ebook/import, export, provider, and model fields must still be inventoried. A candidate is migratable only when it is an active filesystem lookup, contains the exact old-root prefix, maps deterministically, and remains contained beneath its approved configured root. Logs, audit messages, free-form notes, external URLs, commands, endpoints, historical backup manifests, and archived reports are excluded.

### Migration Tool

`scripts/migrate_artifact_paths.py` is a default-dry-run operator tool with explicit `--db-path`, `--old-root`, `--new-root`, `--report-dir`, `--verify-files`, rollback-output, and `--apply` controls. Apply requires a fresh backup confirmation token or identifier that is recorded in the report without exposing secrets.

The tool rejects empty, identical, unrelated, or unsafe roots. It inventories every approved field, uses parameterized SQL, and generates Markdown and JSON summaries plus privacy-safe row mappings. Reports use table, column, record identifier, relative suffix or suffix hash, status, and reason; they never contain chapter text, credentials, provider secrets, or arbitrary JSON payloads.

Dry-run opens the database read-only and never mutates it. Apply acquires a SQLite write lock, verifies the reviewed pre-apply database hash, executes all updates and migration audit metadata in one bounded transaction, validates expected counts before commit, and rolls back on any SQL or validation error. Already-current values and unrelated values are unchanged. A second apply updates zero rows.

### Backup And Rollback

Before rehearsal, create a fresh protected backup through the existing backup workflow with secrets excluded and relevant artifacts included under existing policy. Because the current backup workflow records an operational event in the live database, P0A must use or add a narrowly scoped no-event option so backup creation does not violate the pre-rehearsal no-mutation gate. This is not a backup-job redesign.

Validate the archive and sidecar manifest, non-zero size, manifest version, listed modules, and supported checksums. Create a separate SQLite-consistent database copy for direct rollback and record its hash, size, time, and protected permissions. A restore drill must target an isolated directory.

Rollback evidence consists of the system backup, direct database copy, pre/post hashes, manifest, migration report, and row-level old/new path metadata. If post-apply validation fails, stop writers and restore the database through the documented rollback procedure. Do not regenerate content.

### Copied-Database Rehearsal

The rehearsal uses the direct database copy and an isolated view of the current data tree. The artifact tree may use a read-only representative copy when a full duplicate is unnecessary, but all sampled paths and every proposed containment check must resolve against the actual configured layout.

Run dry-run, inspect counts, apply to the copy, then apply a second time. Verify SQLite integrity, foreign keys, table row counts, approved-column diffs, zero unexpected mutations, remaining old-root counts, missing/ambiguous classification, and idempotency. Any unresolved active Reader, cover, audio, or TTS artifact blocks operator apply unless the operator explicitly accepts it.

Representative raw, translated, HTML, cover, audio, and TTS artifacts are checked using size and SHA-256 before and after rehearsal. Covers receive an image probe; audio receives a type probe and `ffprobe` where supported. Artifact hashes must not change.

### Runtime Workflow Validation

Run an isolated API/web instance against the rehearsed database and configured artifact tree. Validate library listing, representative books and chapters, raw-only and translated Reader modes, rich HTML, cover delivery, audio streaming and download, TTS status, and path-dependent export behavior. Protected artifact routes must deny unauthenticated access and succeed with authenticated access.

Responses and browser-visible content must contain no absolute filesystem path or known old-root value. Reader failures must distinguish missing metadata, missing files, and containment rejection rather than silently returning empty content. Existing focused integration or Playwright harnesses are extended where practical; paid translation and TTS providers remain disabled.

### Status Redaction

`/api/system/status` and `StatusSettingsView` expose safe availability, size, health, and logical labels only. The response model and TypeScript type remove `database_path` and `data_dir`. Tests assert authenticated and public responses and rendered UI contain no absolute host paths. This change does not redesign the status page or remove sanitized server-side diagnostics.

### Prevention

Audit artifact writers for chapter files, rich content, covers, audio, TTS, ebook/import staging, and exports. New writes must originate from the configured current data root or a centralized storage helper and must never persist the old root. P0A does not convert the whole schema to relative paths.

Active scripts and runbooks replace personal absolute commands with repository-relative commands, `$REPO_ROOT`, `$DATA_DIR`, or configuration-derived values. Historical audit evidence may retain the old root when explicitly archival. Migration documentation may identify it as the source prefix.

## Error And Ambiguity Policy

Unresolved records are classified as missing, ambiguous suffix, duplicate candidates, outside the data tree, inactive stale metadata, optional artifact, or historical-only metadata. The tool never guesses among candidates, points a file field to a directory, changes availability flags for missing files, deletes metadata, or regenerates artifacts.

Collision warnings identify multiple records or source suffixes mapping to one target. A collision is reportable and blocks apply unless identity and intended sharing are already established by application semantics.

## Testing Strategy

Implementation follows test-driven development. Resolver tests cover blanks, current paths, exact-prefix remapping, unrelated paths, traversal, URLs, symlink escapes, file/directory type, missing targets, and idempotency. Migration tests create temporary databases and prove dry-run immutability, approved-column scope, report privacy, transaction rollback, second-apply zero updates, and unchanged row counts and integrity.

API and frontend tests cover Reader retrieval, cover and audio routes, protected access, status redaction, and absence of absolute paths. Regression tests assert new writes do not persist the old root and active operational files do not contain it outside explicit archival/migration allowlists.

Final validation includes targeted tests, copied-database rehearsal, representative workflow smoke tests, frontend tests, production build, lint, `scripts/verify.sh`, and `git diff --check`. Any environment-dependent test that cannot run is reported with its exact reason. Tests must use isolated databases and must never point at the operator database.

## Deliverables And Evidence

P0A delivers the resolver, approved registry, default-dry-run migration tool, reports, rollback mapping, copied-database rehearsal evidence, status redaction, runbook updates, tests, and implementation notes. The final report distinguishes `P0A_FIX_APPLIED` work from `RECOMMENDATION_ONLY` items and records baseline, inventory, counts, unresolved records, backup proof, idempotency, integrity, file identity, smoke results, files changed, tests run, limitations, and operator-apply status.

The operator apply result remains `NOT_APPLIED_AWAITING_EXPLICIT_APPROVAL` until the separate approval gate is satisfied. Approval of this design or implementation plan is not approval to mutate the operator database.
