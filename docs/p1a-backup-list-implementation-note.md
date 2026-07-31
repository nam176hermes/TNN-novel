# P1A Backup List Metadata and Sidecar Repair Implementation Note

**Marker:** `P1A_FIX_APPLIED`

**Implementation baseline:** branch `master`, commit `ac8032b`. The approved P1A design and plan commits and the P0A completion commits were present. Seven intentional mobile UI files were documented at baseline and later committed separately as `f2763dd`; P1A did not overwrite unrelated user work.

## Executive summary

Normal backup listing is now sidecar/stat-only. Missing or invalid metadata is entry-specific and never causes archive inspection or blocks other entries. An explicit dry-run-first repair command inspects selected legacy archives and atomically creates compact sidecars. New backup creation also publishes compact sidecars while preserving the complete internal manifest and restore format.

The operator inventory contained three plain archives: one current archive with a sidecar and two legacy archives without sidecars. The legacy sidecars were generated only after copied-directory rehearsal. All three operator archives now list as `READY`. No backup archive or operator database bytes were changed.

## Root cause and previous flow

`GET /api/system/backups` called `BackupService.list_backups()`, then `scripts.ops.list_backups()`, then a combined manifest reader. When a sidecar was absent, that reader opened and decompressed `.tar.gz` to find `manifest.json`. The observed baseline opened two archives, took about 14.35 seconds, and returned about 5 MiB because a legacy full manifest was embedded in the response. The largest current archive is approximately 5.6 GB.

## New metadata-only flow

The list path now:

1. enumerates the backup directory once;
2. validates supported safe filenames and `lstat` metadata;
3. reads at most 8 MiB from an adjacent regular non-symlink sidecar;
4. validates and allowlists backup-level fields;
5. classifies each entry independently;
6. returns a bounded safe response;
7. gives a download URL only to `READY` entries.

It never calls `tarfile.open`, decrypts, checksums, or walks archive members. No cache was added because the sidecar-only path meets the target and direct stat state is more reliable for the small inventory.

## Sidecar and repair behavior

New compact sidecars use schema version `1` and atomic same-directory publication. Existing valid sidecars are not overwritten by default. `scripts/ops.py backup-metadata-repair` requires an explicit backup directory and selection, defaults to dry-run, supports `--apply`, `--overwrite`, a passphrase environment-variable name, and an optional safe JSON report.

Plain legacy archives with internal `manifest.json` reuse the verified internal metadata. Manifestless legacy archives are repaired only after tar structure, member safety, `data/` payload, member count, module presence, file count, source bytes, and secrets presence are deterministically inspected. Unsafe paths, links, corrupt archives, unsupported formats, and encrypted archives without an explicitly supplied environment passphrase fail without a sidecar.

## Corrupt and missing metadata behavior

The API states are `READY`, `METADATA_MISSING`, `METADATA_INVALID`, `ARTIFACT_MISSING`, `ARTIFACT_INVALID`, and `UNSUPPORTED_FORMAT`. Errors are fixed safe messages. Raw exceptions, internal paths, commands, member names, passphrases, and tracebacks are excluded. Malformed, oversized, orphaned, zero-byte, unsupported, unreadable, and symlink cases are covered by isolated tests.

## API and frontend

The API preserves existing fields and adds metadata state, repair-needed, manifest/archive availability, and a safe warning. Authentication and protected download routing remain unchanged. The frontend loads backup metadata independently from core system status, renders loading/empty/failure states, shows entry-level repair warnings, and offers download only for entries with a protected `download_url`. No restore control or automatic browser repair was added.

## Copied-directory rehearsal

Only the two missing-sidecar archives were copied to an isolated temporary directory; the 5.6 GB current archive was not duplicated. Rehearsal results:

- dry-run selected 2, would write 2, failed 0;
- first apply wrote 2 sidecars;
- second apply wrote 0;
- both archive SHA-256 values were unchanged;
- both entries listed `READY`;
- warm metadata-only list median 0.182 ms, maximum 0.224 ms, archive opens 0;
- representative restore drill returned SQLite integrity `ok`;
- no live restore was run.

One archive was from a manifestless legacy format. Initial rehearsal correctly refused it rather than guessing. The explicit inspector was extended with deterministic legacy derivation and traversal/link validation, covered by red/green tests, before rehearsal restarted.

## Operator sidecar repair and identity evidence

The final operator dry-run selected 2, would write 2, failed 0. Explicit apply wrote 2 sidecars; a second apply selected/wrote 0. All three archive hashes match the pre-repair baseline:

```text
cd997d26615080009e8d01237f88f17c6d630bffc7db720e2b26edad1fa09ab1
3ee59570162790bd79f6e412f3a0b69379ac81945b88a701c7f72f6776a90f02
1463c34b154fc62b84a2953983c011372063cb27a0b456ceaf52d32ec8b04f56
```

The operator database remained 50,450,432 bytes with unchanged mtime and SHA-256:

```text
c78b5c1093d73986b743d8cc1fc4f4c099e11fb7b0012ceba617d31a33bef877
```

No operator database write, archive rewrite, archive deletion, paid provider call, or live restore occurred.

## Before and after performance

| Measurement | Before | After |
| --- | ---: | ---: |
| Current list warm time | ~14.35 s total baseline | 102.943 ms median, 115.650 ms max |
| Normal-list archive opens | 2 | 0 |
| Current response payload | ~5 MiB | 2,638 B service JSON |
| Repaired-copy list | n/a | 0.182 ms median |

The current operator median remains above the preferred 100 ms because one compatible legacy full sidecar is 5.85 MiB, but it is below the required 250 ms and never opens its 5.6 GB archive. Replacing a valid legacy sidecar solely for compaction was not necessary and was intentionally avoided without `--overwrite`.

The synthetic benchmark measured 0.729 ms for ten compact sidecars and 0.065 ms for a sparse 512 MiB missing-sidecar archive, with zero archive opens. Latency therefore depends on entry/sidecar count rather than compressed archive size.

## Restore and security compatibility

The representative copied restore drill succeeded. The archive format and internal manifest were unchanged. Filename traversal, archive symlink escape, sidecar symlinks, authentication, non-cacheable backup routes, encryption safeguards, and protected download behavior remain covered. API/browser responses expose no absolute filesystem paths or private file-level manifest data.

## Final verification

- backend verification: 730 tests passed; SQLite/runtime, typecheck, and package-integrity gates passed;
- backup, repair, benchmark, API, and EPUB focused suites: 80 tests passed in the final combined run, including the final sidecar path-validation change;
- frontend suite: all 71 files and 625 tests passed in four resource-bounded shards (`--maxWorkers=2`);
- Playwright mobile workflows: 6 passed;
- frontend typecheck, lint, and production build passed;
- `git diff --check` passed.

The unbounded frontend invocation inside `scripts/verify.sh` encountered three Vitest fork startup timeouts after 68 files and 607 tests had already passed. The three affected files passed 18/18 when rerun directly, and the entire 71-file suite passed when split into four two-worker shards. WSL swap was fully consumed and unrelated Node processes were left untouched. This is recorded as an environment/runner operability limitation rather than hidden or represented as an exact successful `scripts/verify.sh` exit. Changing the shared Vitest worker configuration remains `RECOMMENDATION_ONLY` and requires separate approval.

## Remaining limitation and P2C readiness

Backup creation is still synchronous. Job-backed creation, retention redesign, restore UI, restore-format changes, and broad Status redesign are outside P1A and remain `RECOMMENDATION_ONLY` for P2C. P1A leaves a clean seam: creation already publishes a validated compact sidecar, while listing is bounded and independent of future creation execution mode.
