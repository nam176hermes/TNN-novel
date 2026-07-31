# P2C Background Backup, Retention, and Domain Modularization Design

**Status:** Approved for implementation planning

**Date:** 2026-07-13

## Purpose

Move system-backup creation out of the HTTP request, bound long-lived operational metadata, and reduce the largest frontend/backend change surfaces through explicit business seams. The implementation must preserve the existing archive/restore format, operator database schema semantics, Reader behavior, public route paths except for the documented asynchronous backup response, and current authentication/security controls.

This is an incremental compatibility-facade extraction. It is not a database redesign, ORM migration, external queue rollout, Reader visual redesign, or broad application rewrite.

## Verified Baseline

The approved design baseline is clean `master` commit `a4f7cc8`.

| Change surface | Baseline size | Main coupled responsibilities |
| --- | ---: | --- |
| `app/database/db.py` | 6,225 lines | connection, schema compatibility, auth, jobs, operations, Reader, books, glossary, sources, TTS |
| `app/mobile_api/services/pipeline_service.py` | 5,713 lines | file/content access, books, Reader, imports, annotations, dictionaries, X-Ray, source and QA collaboration |
| `web/src/components/ReaderView.tsx` | 5,367 lines | Reader controller, TOC, chrome, audio jobs, offline cache, annotations, AI/X-Ray and rendering |
| `web/src/styles.css` | 13,558 lines | global tokens, shell and every feature, with responsive overrides thousands of lines from base rules |

The current system-backup POST runs synchronous archive creation inside an async route. The project already has a SQLite-backed in-process `JobTracker` with leases, heartbeat, cancellation, stale interruption, job logs, and a visible Jobs UI. P1A already made normal backup listing sidecar-only and established atomic compact-sidecar publication without changing restore format.

Read-only operator counts at design time were:

- `auth_sessions`: 7,091 rows;
- `auth_login_failures`: 8 rows;
- `operational_events`: 16,483 rows.

No retention deletion was performed while producing this design.

## Considered Approaches

### Selected: incremental extraction behind compatibility facades

Extract one domain at a time, keep existing imports working through re-exports/delegation, and verify behavior after each seam. This has the smallest rollback unit and prevents a simultaneous API, database, Reader, and cascade rewrite.

### Rejected: one-shot modularization

A single large movement would reduce line counts quickly but combine behavior changes with thousands of import and cascade changes. It would make failures hard to attribute and is not justified for a private operator database.

### Rejected: frontend-only split

Splitting only Reader/CSS leaves synchronous backups, unbounded metadata growth, the QA service cycle, and backend repository coupling unresolved.

## Architecture and Dependency Direction

The intended direction is:

```text
FastAPI routers -> domain services -> domain repositories/file adapters
React ReaderView controller -> feature hooks/controllers -> presentational feature components
styles entry -> ordered CSS layers -> feature-owned base and responsive rules
```

Compatibility facades are temporary stable import surfaces, not duplicate implementations. A function moves to one authoritative module; the legacy module imports and re-exports it until callers are migrated safely.

## 1. Job-Backed System Backup Creation

### API contract

`GET /api/system/backups` and the protected download route remain unchanged. `POST /api/system/backups` changes from returning a completed `SystemBackupItem` to returning HTTP `202 Accepted` with a safe job response containing:

- `job_id`;
- `status` (`queued` initially);
- `message`;
- no archive path, passphrase, command, internal manifest, or secret-bearing parameters.

The frontend stores the returned job id, follows the existing authenticated job-status API, and reloads the sidecar-only backup list only after the job reaches `completed`. Failure, interruption, and cancellation are entry-independent and do not block core Status rendering.

### Job execution

Add the `backup` job type to the existing `JobTracker`/`JobService` architecture. The request handler performs only validation, safe job creation, and scheduling. Blocking archive work runs through `asyncio.to_thread()`.

Persisted job parameters may contain only non-secret options:

- include audio;
- include exports;
- include job logs;
- include secrets boolean;
- retry lineage and safe progress fields.

The encryption passphrase is stored only in an in-memory, process-local secret store keyed by job id. The store supports take-once retrieval, explicit deletion, and a short expiry. It never serializes values, returns them from an API, or includes them in logs/exceptions. A process restart makes an encrypted backup job `interrupted`; retry requires a new authenticated submission with the passphrase. No automatic encrypted retry is attempted.

### Staging and publication

Backup creation writes into a protected staging directory inside the configured backup directory so final publication stays on the same filesystem. The shared archive builder must:

1. create a uniquely named partial artifact;
2. add selected modules while invoking a cooperative cancellation callback between bounded file/member operations;
3. write the unchanged complete internal manifest;
4. close and validate the archive;
5. create compact sidecar metadata in staging;
6. fsync files where supported;
7. atomically rename the final archive and then its sidecar into their established names;
8. remove owned partial files on failure/cancel.

Normal listing ignores partial/staging names. Cancellation before publication produces no final archive or `READY` sidecar. After final archive publication, sidecar publication failure is recorded as a failed job and the artifact remains safely visible as `METADATA_MISSING`; the code must not delete a valid completed archive merely to hide that failure.

### Concurrency, progress, and recovery

Only one backup creation job may execute per configured backup directory. The job uses existing SQLite claim/lease behavior to prevent duplicate execution. Progress uses safe coarse steps rather than byte-perfect claims:

- preparing;
- collecting files;
- writing archive;
- validating;
- encrypting when requested;
- publishing.

On process loss, stale jobs become `interrupted` under existing recovery rules. Unencrypted retry creates a new job and never overwrites an existing valid archive. Encrypted retry requires resubmission because the passphrase is intentionally gone.

### Audit behavior

The request records a safe `backup_job_queued` event. Completion/failure/cancel records one terminal event with job id, safe filename when available, encryption/secrets booleans, duration, and result. No event contains a passphrase, full path, raw exception, archive member, or private content.

## 2. Operational Metadata Retention

### Approved default policy

The approved balanced defaults are:

| Data | Age bound | Count bound | Never delete |
| --- | ---: | ---: | --- |
| revoked or expired auth sessions | 30 days | 5,000 | active, unexpired sessions |
| login failures | 30 days | 5,000 | n/a |
| operational events | 90 days | 50,000 | n/a |

Both bounds apply: rows older than the age bound are eligible, and rows beyond the newest count bound are eligible even if younger. Settings are positive environment-backed integers with these defaults; invalid/non-positive values fail configuration validation rather than silently disabling retention.

For sessions, retention age is based on `revoked_at` when present or `expires_at` for expired sessions. Active unexpired rows are excluded from both age and count pruning. Date comparison uses SQLite date conversion rather than lexical assumptions because existing timestamps use both ISO offsets and SQLite timestamp formatting.

### Repository and service seam

Create `app/database/connection.py` as the authoritative connection primitive and retain `get_connection` as a compatibility export from `db.py`. Schema initialization/migration ownership remains centralized and unchanged.

Create:

- `app/database/auth_repository.py` for auth sessions and login failures;
- `app/database/operations_repository.py` for operational events and retention pruning;
- `app/mobile_api/services/retention_service.py` for policy orchestration and safe summaries.

`db.py` re-exports moved functions during migration. There is one implementation for each query.

### Maintenance scheduling

Retention does not run inside login, status, list, or other request handlers. A process-local maintenance task runs once after application startup and every six hours afterward. Each table is pruned in small configurable batches using short transactions. The task yields between batches and stops cleanly on application shutdown.

Concurrent processes may both attempt maintenance safely because deletion is idempotent. SQLite busy/locked errors are logged safely and retried at the next interval; they do not prevent API startup.

After a run that deletes at least one row, record one sanitized `operational_retention` summary containing counts only. The summary is written after operational-event pruning and is allowed to consume one slot; the next run remains bounded. Zero-delete runs do not create events.

### Operator visibility

Authenticated system status adds safe row counts and last-retention summary without exposing database paths or row contents. No retention delete button is added in this phase.

## 3. ReaderView Feature Extraction

### Boundary rule

`ReaderView` remains the route-level controller and owns the selected book/chapter contract. Feature modules own their local state/effects and expose narrow props/callbacks. They must not import `ReaderView` at runtime or fetch duplicate chapter content.

Move shared Reader types and settings persistence to `web/src/components/reader/types.ts` and `readerSettings.ts`. Existing imports are migrated; temporary type re-exports from `ReaderView` are allowed only until all internal callers move.

### TOC seam

Create `ReaderTocSheet.tsx` plus `useReaderToc.ts` for:

- open state;
- query and ascending/descending order;
- current-chapter anchoring;
- filtered chapter previews;
- first/latest navigation actions.

Changing order never changes the current chapter. Opening the TOC scrolls to the current item. The component receives prepared chapter metadata and an `onSelectChapter` callback; it does not load chapter content.

### Controls seam

Create `ReaderChrome.tsx` and `ReaderQuickControls.tsx` for the top bar, three-zone chapter navigation, immersive visibility, mode/settings controls, and safe-area structure. ReaderView provides current position, availability booleans, and callbacks. Important exit/navigation actions retain text labels and minimum mobile touch targets.

### Audio seam

Create a lazy-loaded `ReaderAudioFeature.tsx` and `useReaderAudio.ts`. The hook owns job submission/polling, playlist state, cached URL selection, error sanitization, bulk confirmation, auto-next, and cleanup. The presentational module renders the compact mini-player and audio sheet. Importing ReaderView without opening audio must not eagerly load the audio feature chunk.

### Offline-cache seam

Create `useReaderOfflineCache.ts` for cache manifest/status, book cache/remove actions, cached chapter/audio URL lookup, service-worker messages, and cleanup. It depends on the existing `readerCache` state module and authenticated API client boundaries. It does not own chapter selection or Reader rendering.

### Behavior preservation

This extraction does not redesign Reader visuals, add a new cache format, change storage keys, alter API responses, or modify annotation/AI/X-Ray behavior. Existing Reader integration tests remain authoritative, with new seam tests added before movement.

## 4. Feature CSS and Layers

### Layer order

`web/src/styles.css` becomes an import manifest. Every stylesheet declares rules in one of these fixed layers:

```css
@layer tokens, base, shell, components, features, utilities, overrides;
```

Initial files are:

- `styles/tokens.css`;
- `styles/base.css`;
- `styles/shell.css`;
- `styles/components.css`;
- `styles/reader.css`;
- `styles/library.css`;
- `styles/import.css`;
- `styles/operations.css`;
- `styles/utilities.css`.

The entry imports files in deterministic order. Feature media rules live in the same feature file immediately after or near the corresponding base section. There is no separate multi-thousand-line mobile override tail.

### Extraction method

CSS splitting is mechanical and behavior-preserving:

1. establish screenshot, overflow, touch, and critical selector tests;
2. add the ordered layer manifest;
3. move one complete selector family with its responsive rules;
4. run CSS contract tests, component tests, Playwright screenshots/workflows, and build;
5. commit before moving the next family.

Selectors are not renamed during movement. Specificity changes introduced by layers must be resolved by assigning the original cascade intent, not by adding `!important` or duplicating selectors. Route-level lazy CSS is excluded initially because deterministic cascade preservation is more important than payload reduction in this phase.

## 5. PipelineService and Database Business Seams

### Database seam sequence

After connection/auth/operations extraction required by retention, extract `app/database/reader_repository.py` for Reader progress, annotations, dictionary/AI cache, X-Ray entities, mentions, and timeline queries. `db.py` keeps compatibility exports while callers migrate. Book/library and import transaction functions remain in place during this phase because P2A/P2B already optimized and verified those seams.

No table is renamed, split, or replaced. SQL, transaction boundaries, foreign keys, migration order, and return payload shapes remain unchanged unless a retention query is explicitly new.

### Service seam sequence

Create `content_file_service.py` for canonical artifact resolution and bounded source/translation/HTML file access. Create `reader_service.py` for Reader progress/content-facing orchestration and collaboration with `reader_repository`.

Break the `pipeline_service -> qa_service -> pipeline_service` cycle by defining a narrow `ChapterContentReader` protocol accepted by `QAService`. `PipelineService` may implement that protocol during compatibility migration, while new Reader/content services also satisfy it. `qa_service.py` must no longer import the concrete `PipelineService` class at runtime.

`PipelineService` delegates moved behavior and preserves its public method signatures so existing routers and tests continue to work. Routers migrate to focused services only after compatibility tests prove identical behavior. Import, translation, glossary, source, and export behavior are not reorganized merely to reduce line count.

## Error Handling and Security

- Public/authenticated responses contain safe fixed errors, not tracebacks or absolute paths.
- Backup jobs never persist or log passphrases.
- Partial backup names are unlistable and undownloadable.
- Retention never deletes active sessions and never runs mass deletion in a request.
- Repository extraction retains parameterized SQL and foreign-key enforcement.
- Reader extraction does not weaken protected content/audio/cache access.
- CSS movement must preserve focus, reduced-motion, safe-area, and mobile overflow behavior.
- No paid translation or TTS provider is invoked by tests or maintenance.

## Testing Strategy

All behavior changes and extractions use test-first red/green cycles.

### Backup

- POST returns `202` quickly and performs no archive work before response;
- job lifecycle, lease, single-concurrency, progress, cancellation and interruption;
- passphrase absent from DB, API, logs and reports;
- cancel/failure cleans owned staging files and does not publish `READY` metadata;
- successful plain/encrypted archives pass the existing restore drill;
- protected listing/download behavior remains unchanged.

### Retention

- active sessions survive age/count pruning;
- revoked and expired sessions obey age and count bounds;
- login failures and operational events obey both bounds;
- batch sizes and transaction rollback are verified;
- startup/periodic task is independent from request handlers;
- summary contains counts only and zero-delete runs create no event;
- operator DB is never used by tests.

### Reader and CSS

- TOC sorting/search/current anchoring and chapter selection;
- chrome exit, immersive toggle, previous/next and quick controls;
- audio lazy loading, polling, cancel/error and mini-player;
- offline cache manifest, add/remove, cached URL and offline states;
- existing Reader modes, annotations, QA, AI/X-Ray and progress suites;
- 360x740 and 390x844 overflow/touch/safe-area Playwright coverage;
- CSS layer order, unique selector ownership and media colocation checks;
- production build chunk inspection confirms audio remains optional.

### Repository and service seams

- compatibility exports are identity/behavior equivalent;
- auth, operations and Reader repository contract tests;
- query-count and import transaction performance contracts remain green;
- QA protocol removes runtime circular import;
- API route/response tests remain unchanged.

Final verification includes focused suites after every seam, full backend, full frontend with resource-bounded workers where needed, Playwright mobile workflows, typecheck, lint, production build, package checks, `scripts/verify.sh` or documented equivalent when the environment cannot start unbounded workers, and `git diff --check`.

## Delivery Sequence and Commit Boundaries

1. Async backup contract, secret lifecycle, staging/publication, frontend job tracking.
2. Connection/auth/operations repositories and retention maintenance.
3. Reader TOC and controls extraction.
4. Reader audio and offline-cache extraction, including lazy loading.
5. CSS layers and feature files, one feature family per verified commit.
6. Reader repository, content-file service, Reader service, and QA protocol cycle removal.
7. Full completion audit and operational documentation.

Each boundary must be independently testable and reviewable. Behavior changes are not mixed into mechanical file movement.

## Explicit Exclusions

- Celery, Redis, external queues, multi-node worker orchestration;
- restore UI or restore-format redesign;
- backup archive deletion/retention changes beyond existing `BACKUP_KEEP` behavior;
- operator-triggered destructive retention UI;
- ORM adoption or database schema redesign;
- Reader visual redesign, cache-format migration, or annotation redesign;
- ImportPanel modularization;
- broad App shell or API-client rewrite;
- unrelated provider, translation, TTS, glossary, source, export, or dependency changes.

## Acceptance Criteria

The phase is complete only when:

- backup POST returns `202` and archive creation runs through a tracked background job;
- no backup passphrase is persisted or exposed;
- cancellation before publication leaves no final archive/sidecar;
- completed archives remain restore-compatible and list through sidecars;
- retention enforces the approved age/count bounds without deleting active sessions or mass-deleting in requests;
- ReaderView delegates TOC, controls, audio, and offline-cache ownership to focused modules;
- audio is lazy-loaded and Reader behavior remains covered;
- CSS is split into deterministic layers/features with responsive rules colocated near base feature rules;
- `db.py` has connection/auth/operations/Reader repository seams behind compatibility exports;
- PipelineService delegates content/Reader behavior and the QA runtime cycle is removed;
- public API/security behavior outside the documented backup `202` response remains compatible;
- full verification and completion audit pass with no operator DB mutation by tests.
