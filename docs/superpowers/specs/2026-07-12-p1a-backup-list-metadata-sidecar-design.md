# P1A Backup List Metadata and Sidecar Repair Design

**Status:** Approved for implementation planning

**Phase marker:** `P1A_FIX_APPLIED`

**Date:** 2026-07-12

## Purpose

Make normal system-backup listing fast, bounded, and metadata-only. A list request must not open, decompress, decrypt, checksum, or inspect archive members. Legacy archives without usable sidecars remain visible and can be repaired only through an explicit operator command.

P1A changes backup metadata reads and sidecar operability only. It does not change the archive or restore format, create job-backed backups, add restore controls, alter book export, modify the operator database, delete archives, or perform a live restore.

## Verified Baseline

The clean baseline is branch `master` at commit `5c1c04845b293f9f53fb61cafdcf209003534a5c`. The P0A completion commits are present.

The configured backup inventory currently contains three supported plain archives:

- one current archive with a valid sidecar;
- two legacy archives without sidecars;
- no malformed sidecars in the current inventory.

The largest current archive is approximately 5.6 GB. The valid sidecar is approximately 5.85 MB because it duplicates the full internal manifest, including 28,864 file checksum records.

The measured list path currently:

- spends about 10 ms enumerating the directory;
- spends about 113 ms reading the valid full sidecar;
- spends about 13.56 seconds reading the manifest from the larger legacy archive;
- spends about 646 ms reading the manifest from the smaller legacy archive;
- opens two compressed archives;
- takes about 14.35 seconds in total;
- returns approximately 5.0 MB because the full manifest is embedded in the API response.

These measurements were collected read-only. No archive, sidecar, or operator database was changed.

## Root Cause and Existing Flow

`GET /api/system/backups` calls `BackupService.list_backups()`, which calls `scripts.ops.list_backups()`. For each archive, `list_backups()` calls `read_backup_manifest()`.

`read_backup_manifest()` combines two responsibilities:

1. read an adjacent `.manifest.json` sidecar when present;
2. otherwise open a plain `.tar.gz` archive and extract its internal `manifest.json`.

The implicit fallback makes request latency proportional to compressed archive size and filesystem throughput. The list response also embeds the entire manifest, including private artifact-relative names and tens of thousands of checksums, although the frontend uses only a small summary.

## Selected Design

Use the existing `.manifest.json` sidecar filename and support both legacy full sidecars and new compact sidecars. Do not introduce a second metadata filename.

The internal archive `manifest.json` remains unchanged and complete for restore validation. New or repaired external sidecars contain only safe listing metadata. Existing full sidecars remain readable, but the normal list path extracts an allowlisted summary and never returns file-level checksum/path entries.

This design provides backward compatibility without retaining archive inspection in a request path or creating two sidecar sources of truth.

## Metadata-Only List Flow

The normal list operation will:

1. enumerate a bounded set of recognized backup artifacts and recognized sidecars;
2. use `lstat`/bounded stat metadata without following unsafe symlink targets;
3. classify archive format from a supported safe filename;
4. read an adjacent sidecar only when it is a regular file within the configured backup directory;
5. reject sidecars above a documented maximum size;
6. parse a JSON object and validate allowlisted field types;
7. build a compact response independently for each entry;
8. sort deterministically by creation/stat time and safe filename.

The normal list operation will not call `tarfile.open`, decrypt an archive, compute an archive checksum, walk members, or call an archive-inspection helper. One failed entry cannot fail the list.

No cache will be added initially. The entry count is small, and correctness is simpler when every request reflects current stat/sidecar state. A short local cache is `RECOMMENDATION_ONLY` unless post-change measurement proves the metadata-only path still misses the target.

## Metadata States

Every backup-like entry receives one state:

- `READY`: supported, regular, non-zero artifact plus valid compatible sidecar;
- `METADATA_MISSING`: supported artifact exists without a sidecar;
- `METADATA_INVALID`: sidecar exists but is unreadable, oversized, malformed, or fails schema/type validation;
- `ARTIFACT_MISSING`: recognized sidecar exists without its archive;
- `ARTIFACT_INVALID`: archive is zero-byte, unreadable, a directory, or an unsafe symlink;
- `UNSUPPORTED_FORMAT`: a backup-like filename has an unrecognized archive extension.

Unrelated directory entries are ignored. Status and warning text are fixed safe messages; raw exceptions, tracebacks, host paths, and sidecar contents are never returned.

Only `READY` entries receive a `download_url` or browser download action. Missing or invalid metadata entries remain visible with an explicit repair warning. The existing authenticated direct-download endpoint and its containment checks remain compatible; P1A does not turn the list endpoint into a restore or archive-validity oracle.

## Sidecar Contract

The external sidecar is a versioned JSON object containing only safe backup-level metadata:

- sidecar schema version;
- backup filename;
- backup format version;
- created timestamp;
- archive size;
- encrypted flag;
- secrets-included flag;
- included and excluded module identifiers;
- file count;
- source byte count;
- application/build version when available;
- artifact state;
- archive checksum only when it was already calculated by an explicit workflow.

It must not contain passphrases, provider keys, environment contents, absolute internal paths, command lines, file-level path/checksum inventories, or private content.

Unknown fields are ignored. Required and optional fields have strict expected types, bounded strings/lists, and safe defaults. Booleans are not silently accepted as integers. Unsafe filenames and values containing absolute filesystem paths do not enter the response.

Legacy full sidecars are compatible inputs: the parser validates and copies only known backup-level fields. It ignores the legacy `checksums` array for response construction. The parser has a maximum input size large enough for the currently verified legacy sidecar but finite and documented. New compact sidecars remain substantially smaller.

## Atomic Publication

Backup creation and repair publish sidecars only after the corresponding artifact is present, regular, non-zero, and has the expected supported filename.

Sidecar publication uses a temporary file in the destination directory, restrictive file permissions, flush/fsync where practical, and atomic `os.replace`. A failed write removes the temporary file and never publishes a partial `READY` sidecar.

The internal manifest and archive bytes are not rewritten. Existing valid sidecars are not replaced by repair unless the operator supplies `--overwrite`.

## Explicit Archive Inspection and Repair

Archive inspection is separated from sidecar reads with clear responsibilities matching the codebase:

- `read_backup_sidecar(...)` reads and validates external metadata only;
- `inspect_backup_archive_explicitly(...)` opens an archive and reads its internal manifest only from an operator/maintenance workflow.

`read_backup_manifest(...)` may remain as a compatibility wrapper for explicit creation, encryption, restore, or test call sites, but the normal list path must not call a helper that can fall back to archive inspection.

`scripts/ops.py` gains `backup-metadata-repair` with:

- `--backup-dir`;
- exactly one of `--filename` or `--all-missing`;
- dry-run as the default;
- explicit `--apply`;
- `--overwrite` for replacing a valid sidecar;
- `--passphrase-env` for encrypted archive inspection;
- optional `--report-dir`.

Dry-run opens selected archives only because archive inspection is the explicitly requested maintenance action, but it writes nothing. Apply publishes only validated sidecars. The command reports filename-level outcomes and safe counts without printing absolute paths, raw private manifest data, or passphrase values.

Plain `.tar.gz` archives are inspected directly. Encrypted `.tar.gz.enc` archives without metadata are reported as requiring a passphrase when the configured environment variable is empty. When supplied, the archive is decrypted only to a protected temporary workspace, inspected, and cleaned. Passphrases are not accepted as literal command-line values, persisted, or logged.

Corrupt, unsupported, ambiguous, or unsafe artifacts receive entry-specific failures. The tool never guesses metadata, creates a `READY` sidecar for an unvalidated artifact, modifies archive bytes, deletes archives, or performs a live restore.

## API Contract

The existing item fields are preserved where practical:

- `filename`;
- `size_bytes`;
- `created_at`;
- `encrypted`;
- `secrets_included`;
- `included_modules`;
- `excluded_modules`;
- `manifest` as a bounded safe summary for compatibility;
- `download_url`, empty unless `READY`.

The response adds:

- `metadata_status`;
- `repair_needed`;
- `manifest_available`;
- `archive_available`;
- `warning`.

No response contains absolute paths, sidecar paths, archive member paths, commands, passphrases, raw exceptions, tracebacks, or file-level private metadata. Authentication, session/CSRF behavior, and protected download semantics are unchanged.

## Status UI

Backup list state remains independent of core system status. The application tracks backup loading, loaded/empty, and failure states separately so the readiness and storage cards render immediately even if backup metadata cannot load.

The existing backup panel receives only narrow changes:

- show a backup-list loading indicator;
- show an empty state;
- show entry-specific missing/invalid metadata warnings;
- show a safe retry/reload action;
- show protected download only for `READY` entries;
- show CLI repair guidance without executing repair from the browser.

No restore button, restore UI, status-page redesign, or automatic repair is added. All warning values render as React text and cannot inject raw HTML.

## Rehearsal and Operator Repair Gates

Before writing operator sidecars:

1. inventory archive and sidecar names, formats, sizes, and states using stat/sidecar reads only;
2. create a protected rehearsal directory containing copies of the two legacy missing-sidecar archives;
3. hash each copied archive;
4. run repair dry-run and inspect its safe report;
5. apply repair to the copies;
6. run apply a second time and require zero changes;
7. verify copied archive hashes are unchanged;
8. list the rehearsal directory and require zero archive opens;
9. run a restore drill on a representative repaired copy in an isolated target;
10. verify no temporary files remain.

Only after these gates pass may missing sidecars be generated beside operator archives. Existing operator archives remain unchanged. Operator repair is followed by archive-hash checks, metadata-only listing, idempotency verification, and current-inventory performance measurement.

The operator database hash, size, and mtime are captured before and after the phase. Live authentication/API smoke tests that could create audit or session rows are not used against the operator database; API tests use isolated databases.

## Benchmark Design

`scripts/benchmark_backup_listing.py` creates isolated fixtures for:

- zero backups;
- two valid compact sidecars;
- ten synthetic metadata entries;
- missing sidecars;
- malformed or oversized sidecars;
- a large sparse archive with no sidecar;
- valid legacy and repaired sidecars.

It records directory enumeration time, sidecar read/parse time, service total time, archive-open count, bytes read where practical, entry count, and serialized response size. The benchmark instruments archive opening so any normal-list archive access is visible and treated as failure.

Performance acceptance is:

- zero normal-list archive opens;
- current warm list below 250 ms, preferably below 100 ms after compact operator sidecars exist;
- response size bounded by entry count and compact metadata;
- large missing-sidecar archive latency independent of archive size.

Normal unit tests assert behavior and zero archive access, not brittle wall-clock limits. Dedicated Linux/WSL benchmark evidence records latency.

## Security and Compatibility

P1A preserves:

- authentication on list, creation, and download routes;
- safe filename and traversal rejection;
- backup-directory containment;
- symlink escape rejection where applicable;
- encryption and passphrase handling;
- internal manifest and restore validation;
- protected, non-cacheable backup routes;
- archive bytes and existing restore format.

Tests use isolated backup and data directories. Malformed sidecar types, oversized input, zero-byte artifacts, orphan sidecars, unsupported extensions, unreadable entries, unrelated files, symlinks, and raw HTML-like strings are covered without disclosing host paths or secrets.

## Test Strategy

Backend tests cover metadata-only listing, all metadata states, deterministic sorting, zero archive opens, safe bounded response fields, entry isolation, authentication, traversal/symlink protection, and no absolute path exposure.

Operator tests cover repair dry-run, valid plain repair, encrypted behavior, corrupt archives, atomic publication, cleanup on failure, no default overwrite, archive hash stability, idempotency, and absence of passphrases/private manifest content in output.

Restore tests prove that sidecar repair does not change the internal manifest or archive and that the existing isolated restore drill still succeeds.

Frontend tests cover independent loading, core status visibility on backup failure, missing/invalid warnings, valid protected download actions, safe text rendering, retry behavior, and absence of restore controls.

Verification runs targeted backend, router, operator, restore, security, API-client, and Status UI tests first, followed by production build, typecheck, lint, package checks, `scripts/verify.sh`, and `git diff --check`. The final evidence also confirms unchanged operator database metadata, unchanged archive hashes, zero paid providers, no live restore, no stale temporary repair files, and no secrets in reports.

## Documentation Deliverables

Implementation will create or update:

- `docs/backup-metadata-sidecars.md`;
- `docs/backup-restore.md`;
- `docs/p1a-backup-list-implementation-note.md`;
- `docs/backend-performance-measurements.md`;
- `docs/deployment-hardening.md`.

The implementation note records the baseline, exact old and new flows, current inventory summary without private absolute paths, rehearsal evidence, operator repair result, before/after timing, archive-open count, archive hash evidence, test results, remaining synchronous-creation limitation, and P2C readiness.

## Excluded Work

The following remain out of scope:

- job-backed or asynchronous backup creation (`RECOMMENDATION_ONLY`, planned for P2C);
- restore UI or live restore;
- archive/restore format redesign;
- backup deletion or retention redesign;
- book export changes;
- operator database or job-system changes;
- broad Status-page redesign;
- broad backup-service modularization;
- caching without measurement evidence.

## Completion Conditions

P1A is complete when normal listing opens zero archives, is bounded and under 250 ms warm for the current inventory, isolates corrupt/missing metadata, publishes sidecars only through explicit dry-run/apply repair, proves repair idempotency and archive hash stability, preserves authenticated download and restore compatibility, exposes no paths/secrets/private manifest inventory, keeps core Status usable independently, leaves the operator database unchanged, and passes full verification without mixing in P2C work.
