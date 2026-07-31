# P2C Background Backup, Retention, and Modularity Implementation Note

**Date:** 2026-07-14

**Branch:** `feat/p2c-background-retention-modularity`

**Original verification baseline:** `9f47a41` (`refactor(services): extract reader content seams`)

**Closure code baseline:** `f744b25` (`fix(backups): isolate staging cleanup failures`)

**Scope:** P2C only; no operator data migration, restore, retention apply, paid
provider call, schema redesign, or Reader redesign was performed.

## Executive summary

P2C moves API-triggered system-backup creation from the request into the
existing tracked in-process job runner, adds bounded scheduled operational
metadata retention, and extracts the approved Reader, CSS, database, content,
and QA seams behind compatibility surfaces.

The backup archive/internal manifest/sidecar/restore formats remain unchanged.
`POST /api/system/backups` is the one intentional public contract change and
returns `202 Accepted` with a safe job response. Tests and operator safety
checks in this audit were read-only with respect to the configured operator DB
and backup directory.

Full `scripts/verify.sh` did **not** return success: its unbounded Vitest phase
could not start two workers after 78 files/701 tests had passed. The exact
failure and the complete bounded ext4 equivalent are recorded below. Do not
describe the script itself as passing.

**Phase status: COMPLETE.** The completion audit closed the dedicated terminal
backup-event gap in `9d04ffe`/`de94de7`. Final whole-branch review then found
that secret-bearing background backups briefly published plaintext before
encryption. `3f3b83d` moved that work into private staging, `a4eac8c` made
partial final-link rollback reliable, and `f744b25` prevented best-effort
staging cleanup from overturning READY success or masking the primary failure;
independent re-review approved the fixes.
The documented bounded verification equivalent passes; `scripts/verify.sh`
itself still returned RC 1 and is not described as passing.

## Implemented architecture

### Background system backups

- The authenticated POST validates and queues a `backup` job, returns HTTP 202,
  and performs no archive creation in the request handler.
- Durable states cover preparing, writing, validating, encrypting, publishing,
  and terminal outcomes. The Status UI follows the existing authenticated job
  state and reloads the sidecar-only list after completion.
- One backup runs per resolved backup directory in a process. Blocking work is
  offloaded to a thread and cancellation drains that worker before lock/secret
  release.
- Passphrases use a locked process-local, take-once, expiring store. Persisted
  job parameters contain non-secret options only. Restart loss is intentional;
  encrypted retry requires a new submission/passphrase.
- Archive construction uses private same-directory staging, bounded member
  iteration, validation, collision-safe no-clobber publication, and cleanup of
  owned partial artifacts. For non-secret backups, a valid archive survives
  sidecar publication failure as `METADATA_MISSING`.
- An API/background secrets-included backup never publishes its plaintext
  archive or sidecar in the live backup directory. Plaintext creation and
  encryption remain below a mode-`0700` hidden staging directory; only the
  completed `.tar.gz.enc` and READY sidecar are linked into the live directory.
  Sidecar-first publication,
  an owned hidden reservation, and immediate link-ownership tracking make
  in-progress/crash residue unlistable and normal publication failures fully
  reversible. Protected downloads require a supported final name, regular
  non-symlink artifact, and valid matching sidecar.
- Queue submission writes `backup_job_queued`. After durable terminal state,
  the coordinator attempts one dedicated `backup_job_terminal` event for each
  completed, failed, or cancelled outcome. The background archive path suppresses
  the legacy direct-operator `backup_success` event.

### Operational retention

- Retention runs once after startup and every 21,600 seconds by default, never
  as a request side effect.
- Approved defaults are inactive sessions 30 days/5,000, login failures 30
  days/5,000, and operational events 90 days/50,000. Batch size defaults to 500.
- All settings are positive validated environment integers. Active unexpired
  sessions are excluded from age and count pruning.
- Each run is bounded by its initial row-count budget, yields between batches,
  drains an active SQLite worker during shutdown, and safely defers busy/locked
  work to a later interval.
- A non-zero run writes one count-only `operational_retention` audit. Event
  pruning reserves its slot; zero-delete runs write no audit.

### Repository and service seams

- `app/database/connection.py` owns connection creation.
- `auth_repository.py`, `operations_repository.py`, and
  `reader_repository.py` own their domain queries.
- `app/database/db.py` retains compatibility exports with object identity
  coverage; tables, migration order, SQL payloads, and transaction semantics
  are not redesigned.
- `ContentFileService` owns contained artifact resolution and bounded
  source/translation/HTML reads. `ReaderService` owns Reader-facing content,
  progress, and annotation orchestration. `PipelineService` delegates its
  established public methods.
- `QAService` depends on the `ChapterContentReader` protocol instead of a
  runtime import of `PipelineService`, removing the concrete import cycle.

### Reader and CSS seams

- `ReaderView` remains the route/data controller.
- TOC state/UI lives in `useReaderToc` and `ReaderTocSheet`; chrome/settings in
  `ReaderChrome` and `ReaderQuickControls`; audio in `useReaderAudio` plus lazy
  `ReaderAudioFeature`; offline cache in `useReaderOfflineCache`.
- Reader data APIs, storage keys, cache format, annotations, text modes, and
  visible workflow are preserved.
- `styles.css` declares `tokens, base, shell, components, features, utilities,
  overrides` and imports the owning stylesheets once. Reader, Library, Import,
  and Operations responsive rules are colocated in their feature files.

## Environment and operator safety

The configured locations are recorded only as `configured data root /
pipeline.db` and `configured backup root`; private full paths are not published.
Before tests:

- operator DB size: 50,450,432 bytes;
- operator DB mtime: `2026-07-14T03:32:00.371847Z`;
- operator DB SHA-256:
  `808c398742822a3ee5eb4bbd7f440ea852472488532a7b1572b2fe82404dea21`;
- `PRAGMA integrity_check`: `ok`;
- foreign-key violations: `0`;
- archives: 3 files, 5,800,382,260 bytes total; all three were hashed;
- adjacent sidecars: 3; all three were hashed.

After all tests, build, package checks, fallback shards, and cleanup, DB size,
mtime, SHA-256, integrity and FK result were byte-for-byte/value-for-value
unchanged. The complete archive stat/hash inventory and sidecar inventory were
also unchanged.

Pytest sets `NOVEL_PIPELINE_IGNORE_DOTENV=1` and a temporary `DATA_DIR` before
application imports. Backup tests use `tmp_path`; Playwright intercepts all API
routes. `scripts/verify.sh` was given a disposable ignored worktree DB/log
fixture and placeholder `.env` only so its environment preflight could run.
Those fixtures and the ext4 mirror were removed afterward.

No backup creation/repair, restore, retention apply, operator content write,
translation provider, or TTS provider was invoked against live data.

## Verification evidence

| Check | Result |
| --- | --- |
| Focused backend command from Task 15 | RC 0; 199 passed, 1 warning |
| Focused frontend command, `--maxWorkers=2` | RC 0; 7 files, 162 tests passed |
| Playwright Chromium | RC 0; 8 tests passed, including 390 px/360 px Reader and Status backup states |
| Frontend typecheck | RC 0 |
| Production build in worktree | RC 0; 1,850 modules; separate `ReaderAudioFeature` chunk (8.63 kB) |
| `scripts/verify.sh` compile/shell/env/lint stages | Reached and passed before pytest |
| `scripts/verify.sh` full backend | 824 passed, 2 warnings; pip check clean |
| `scripts/verify.sh` frontend | **RC 1**; 78 files/701 tests passed, then two worker-start timeouts |
| Exact failed worker files | `PipelineDashboard.test.tsx`, `ReaderSettingsSheet.test.tsx` |
| Deterministic ext4 fallback | RC 0; source=80, mirror=80, unique=80, combined=80; 8 sequential shards x 10 files, max 2 workers; 80 files/705 tests passed |
| Ext4 production build | RC 0; 1,850 modules; separate audio chunk retained |
| Python package check | RC 0; no broken requirements |
| Frontend package tree | RC 0; `npm ls --depth=0` |
| Operator safety after verification | DB/integrity/FK/archive/sidecar snapshots unchanged |
| Task 16 focused terminal-event suite | RC 0; 22 tests passed |
| Task 16 five-file regression suite | RC 0; 98 tests passed, 1 pre-existing passlib `crypt` deprecation warning |
| Task 16 compile/lint checks | `compileall` RC 0; Python lint and frontend `tsc --noEmit` RC 0 |
| Task 18 backup/ops/job suite | RC 0; 88 tests passed, 1 pre-existing passlib `crypt` deprecation warning |
| Task 18 real encryption/restore compatibility | RC 0; temp-only OpenSSL `create_encrypted_backup` to `restore_drill` smoke passed |
| Task 18 static checks | `scripts/lint.sh` and `git diff --check` RC 0 |

The Vitest error was:

```text
[vitest-pool]: Failed to start forks worker
Caused by: [vitest-pool-runner]: Timeout waiting for worker to respond
```

At failure time the WSL environment had sustained DrvFS worker I/O wait and
about 3.6 GiB of 4.0 GiB swap in use. The documented bounded equivalent passed,
but `scripts/verify.sh` itself remains a failed command for this run.

The build emitted one pre-existing warning that
`assets/reference-ui/sidebar-scenery.png` was unresolved at build time and
would remain for runtime resolution. It did not fail the build.

## Completion matrix

| Approved acceptance criterion | Status | Evidence |
| --- | --- | --- |
| Backup POST returns 202 and archive creation runs through a tracked background job | PASS | `routers/backups.py`, `backup_job_service.py`; focused backend and full backend suites |
| No backup passphrase is persisted or exposed | PASS | secret-store/coordinator tests; safe API schema and job params |
| Cancellation before publication leaves no final archive/sidecar | PASS | ops cancellation/failure-window tests; focused backend suite |
| Secrets-included background backups never expose plaintext through live list/download | PASS | `3f3b83d`, `a4eac8c`, `f744b25`; concurrent encryption, crash-residue, malformed-sidecar, collision, post-link, and cleanup failure-injection tests |
| Completed archives remain restore-compatible and list through sidecars | PASS | ops restore/list tests and backup API tests; archive format unchanged; no live restore was run |
| Retention enforces age/count bounds without deleting active sessions or mass-deleting in requests | PASS | retention repository/service/lifespan tests; full backend suite |
| ReaderView delegates TOC, controls, audio, and offline-cache ownership | PASS | direct feature tests plus ReaderView regression suite |
| Audio is lazy-loaded and Reader behavior remains covered | PASS | lazy-boundary/audio tests; separate production build chunk |
| CSS uses deterministic layers/features with responsive rules colocated | PASS | `styles.layers.test.ts`, mobile Playwright, production build |
| `db.py` has connection/auth/operations/Reader repository seams behind compatibility exports | PASS | repository identity/behavior tests and full backend suite |
| PipelineService delegates Reader/content behavior and QA runtime cycle is removed | PASS | content/Reader/QA protocol tests and import smoke |
| Each coordinator-owned backup terminal outcome has one dedicated sanitized operational event | PASS | `9d04ffe`, `de94de7`; 22 focused tests and 98-test regression suite |
| Public API/security behavior outside backup POST 202 remains compatible | PASS | full backend 824, focused route suites, authenticated mocked E2E |
| Full verification/completion audit with no operator mutation | PASS VIA DOCUMENTED EQUIVALENT | verify script RC 1 is disclosed; complete bounded 80-file/705-test suite, backend, E2E, type/build/package checks passed; operator snapshots unchanged |

## Additional approved-design audit closure

### Terminal operational events

Task 16 closed the terminal-event design gap in `9d04ffe`, with the three
lifecycle review findings fixed and independently re-reviewed clean at
`de94de7`.

- `backup_job_queued` remains the submission event.
- After terminal persistence, the coordinator attempts exactly once to write
  `backup_job_terminal` for `completed`, `failed`, or `cancelled`. Event-write
  failure is swallowed after one attempt and cannot undo the durable terminal
  job state or cause a duplicate retry.
- The event uses source `backup_job_coordinator`, a constant message, the job
  id, result-specific severity, and safe details: `result`, `encrypted`,
  `secrets_included`, bounded integer `duration_ms`, and an optional
  basename-only `backup_filename` on completion. Completed booleans come from the
  published backup result; failure/cancellation use request intent because no
  completed artifact exists.
- No passphrase, raw exception, directory, archive member, provider secret, or
  private content is persisted or logged by this event path.
- The background service disables the legacy `backup_success` event. That
  event remains the default for direct operator/CLI backup creation; generic
  `job_failure` remains a separate tracker event and is not the dedicated
  backup terminal event.

### Encrypt-before-publish

Final whole-branch review rejected the former service sequence because it
published a READY plaintext archive before starting encryption. Background
execution made that previously synchronous window reachable by concurrent
authenticated list/download requests.

- `3f3b83d` introduced a dedicated secrets-included path whose plaintext bytes
  and sidecar stay below private mode-`0700` staging on the backup filesystem.
- Encryption and READY metadata validation complete before final publication.
  During encryption, normal listing returns no candidate and protected download
  cannot resolve either the staged plaintext name or future encrypted name.
- Final publication is sidecar-first. An owned `.final-name.partial` reservation
  suppresses sidecar-only process-crash residue; after the encrypted link exists,
  the pair is READY and downloadable.
- `a4eac8c` records ownership immediately after each successful hardlink, before
  unlinking its staging source. Injected sidecar-source and archive-source unlink
  failures both roll back every owned live link.
- `f744b25` makes cleanup of process-owned hidden staging best-effort. Injected
  cleanup failures at both inner and outer boundaries preserve READY success;
  cleanup failure also cannot mask a primary encryption/publication error.
  Any residue keeps its hidden unsupported name and remains outside normal
  list/download paths.
- A temp-only real OpenSSL encrypted-backup restore drill passed. The archive,
  internal manifest, sidecar, and restore formats did not change.

## Rollback

For the affected seam, run `git revert <commit>` once per commit, newest first,
then run that seam's focused tests. The boundaries below are inclusive:

- backup jobs/publication/terminal audit: revert `f744b25`, then `a4eac8c`, then `3f3b83d`,
  then `de94de7`, then `9d04ffe`,
  then every backup-seam commit from `04ad491` backward through and including
  `b77fa38`;
- repository/retention: revert every affected commit from `56534d9` backward
  through and including `38156ce`;
- Reader features: revert every affected commit from `987aea0` backward through
  and including `31093ba`;
- CSS layers/features: revert every affected commit from `2a77755` backward
  through and including `46759eb`;
- Reader repository/services: revert `9f47a41`, then `6c2ba0a`.

Stop the app and create/verify a fresh operator backup before rollback. Do not
delete archives and do not run database downgrade SQL: P2C changes neither the
schema nor backup/restore format.

## Remaining limitations

- Jobs and retention are in-process; they are not a multi-node durable queue.
- Process loss does not resume archive work and loses encrypted backup secrets.
- Pending retention audit recovery is process-local; a hard kill may lose that
  pending summary even though committed deletions remain committed.
- `ReaderView`, `PipelineService`, `db.py`, App shell, and ImportPanel still have
  intentionally deferred domains.
- CSS remains eagerly loaded through one ordered manifest.
- No live operator restore, backup creation, sidecar repair, or retention apply
  was authorized or performed in this documentation/verification task.
