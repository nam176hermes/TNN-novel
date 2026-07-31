# P2C Background Backup, Retention, and Domain Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move backup creation to tracked background jobs, enforce bounded operational retention, and split Reader, CSS, PipelineService, and database responsibilities along verified business seams without redesigning the database or Reader workflow.

**Architecture:** Reuse the existing SQLite-backed in-process job tracker and sidecar backup format. Extract domain implementations into focused modules while keeping compatibility exports/delegates in `db.py` and `PipelineService`. ReaderView remains the route controller; feature hooks/components own TOC, controls, audio, and offline-cache state. CSS uses deterministic layers with responsive rules colocated inside feature files.

**Tech Stack:** Python 3.11, FastAPI, SQLite, asyncio, Pydantic, pytest; React 19, TypeScript, Vite, Vitest/Testing Library, Playwright, CSS cascade layers.

## Global Constraints

- Preserve existing backup archive and restore formats.
- `POST /api/system/backups` is the only intentionally changed public contract and must return HTTP `202` with a safe `JobResponse`.
- Never persist or log a backup passphrase.
- Never delete active unexpired auth sessions.
- Retention defaults are sessions `30 days / 5,000`, login failures `30 days / 5,000`, operational events `90 days / 50,000`.
- Retention runs after startup and every six hours, never as request-time mass deletion.
- Do not rename, split, or redesign database tables.
- Keep `db.py` and `PipelineService` compatibility surfaces while callers migrate.
- Preserve Reader visuals, storage keys, API calls, annotation behavior, and cache format.
- CSS selector movement is behavior-preserving; do not add `!important` to repair ordering.
- Do not invoke paid translation or TTS providers in tests.
- Do not use the operator database in tests.

---

### Task 1: Backup job states and asynchronous API contract

**Files:**
- Modify: `app/mobile_api/job_states.py`
- Modify: `app/mobile_api/schemas/__init__.py`
- Modify: `app/mobile_api/routers/backups.py`
- Modify: `tests/test_job_states.py`
- Modify: `tests/test_mobile_api_backups.py`

**Interfaces:**
- Produces: canonical states `PREPARING_BACKUP`, `WRITING_BACKUP`, `VALIDATING_BACKUP`, `ENCRYPTING_BACKUP`, `PUBLISHING_BACKUP`.
- Produces: `POST /api/system/backups -> JobResponse`, HTTP `202`.
- Consumes later: `BackupJobCoordinator.start_backup_job(...) -> str` from Task 3.

- [ ] **Step 1: Add failing state-transition tests**

Add tests proving the ordered flow and terminal safety:

```python
def test_backup_job_state_flow_is_forward_only() -> None:
    states = [
        "QUEUED", "CLAIMED", "PREPARING_BACKUP", "WRITING_BACKUP",
        "VALIDATING_BACKUP", "ENCRYPTING_BACKUP", "PUBLISHING_BACKUP", "COMPLETED",
    ]
    assert all(is_valid_job_state_transition(a, b) for a, b in zip(states, states[1:]))
    assert not is_valid_job_state_transition("PUBLISHING_BACKUP", "WRITING_BACKUP")
```

- [ ] **Step 2: Run the state test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_job_states.py`

Expected: failure because backup states are not in `CANONICAL_JOB_STATES` or transitions.

- [ ] **Step 3: Add explicit backup states and transitions**

Extend `CANONICAL_JOB_STATES`, `ALLOWED_JOB_STATE_TRANSITIONS`, and `STAGE_TO_STATE` with the approved forward sequence. Each backup state may transition to itself or `FAILED`, `CANCELED`, `STALE_INTERRUPTED`; only the next approved step may advance.

- [ ] **Step 4: Add a failing authenticated POST contract test**

Override a coordinator dependency with a recording fake and assert:

```python
response = await client.post("/api/system/backups", headers=headers, json={"include_audio": True})
assert response.status_code == 202
assert response.json() == {"job_id": "backup-job-1", "status": "queued", "message": "Backup queued"}
assert list(backup_service_fixture.backup_dir.glob("*.tar.gz")) == []
```

Also assert authentication remains required and validation rejects `include_secrets=true` without a passphrase before creating a job.

- [ ] **Step 5: Run the route test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_mobile_api_backups.py -k 'create or authentication'`

Expected: current route returns `200` and a completed backup item.

- [ ] **Step 6: Change the route contract minimally**

Use `status_code=202`, response model `JobResponse`, and a new dependency `get_backup_job_coordinator`. The route passes validated booleans/passphrase to `start_backup_job`, records only `backup_job_queued`, and returns:

```python
JobResponse(job_id=job_id, status="queued", message="Backup queued")
```

Do not run `BackupService.create_backup()` in the route.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_job_states.py tests/test_mobile_api_backups.py
git diff --check
```

Commit:

```bash
git add app/mobile_api/job_states.py app/mobile_api/schemas/__init__.py app/mobile_api/routers/backups.py tests/test_job_states.py tests/test_mobile_api_backups.py
git commit -m "feat(backups): accept background backup jobs"
```

---

### Task 2: Atomic staged backup builder with cooperative cancellation

**Files:**
- Modify: `scripts/ops.py`
- Modify: `tests/test_ops_scripts.py`
- Update: `docs/backup-restore.md`

**Interfaces:**
- Produces: `BackupCancelled(RuntimeError)`.
- Produces: `create_backup(..., cancel_check: Callable[[], bool] | None = None, progress_callback: Callable[[str], None] | None = None) -> Path`.
- Produces: final artifact names only after validation/publication; partial names are outside `BACKUP_GLOB_PATTERNS`.

- [ ] **Step 1: Write a failing cancellation/publication test**

Create an isolated data tree with multiple files. Cancel after the first `writing` callback and assert:

```python
with pytest.raises(ops.BackupCancelled):
    ops.create_backup(
        data_dir=data_dir,
        out_dir=backup_dir,
        cancel_check=lambda: cancel_flag[0],
        progress_callback=record_progress,
    )
assert list(backup_dir.glob("novel-pipeline-backup-*.tar.gz")) == []
assert list(backup_dir.glob("*.partial*")) == []
assert list(backup_dir.glob("*.tmp")) == []
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_ops_scripts.py -k 'cancel or publication'`

Expected: `create_backup` does not accept callbacks and/or publishes directly.

- [ ] **Step 3: Implement staging helpers**

Add private helpers with exact responsibilities:

```python
class BackupCancelled(RuntimeError): ...

def _raise_if_backup_cancelled(cancel_check: Callable[[], bool] | None) -> None: ...
def _notify_backup_progress(callback: Callable[[str], None] | None, step: str) -> None: ...
def _backup_staging_path(out_dir: Path, final_name: str) -> Path: ...
```

Create staging inside `out_dir`, use mode `0o700`, build a partial archive there, validate it, build the compact sidecar there, and publish with `os.replace`. Cleanup only paths/directories created by the current invocation.

- [ ] **Step 4: Replace broad `tar.add(directory)` calls with bounded member iteration**

Add files one at a time in deterministic path order. Call cancellation before each file and progress between approved stages. Preserve archive names and manifest contents exactly.

- [ ] **Step 5: Add failure-window tests**

Monkeypatch archive validation, encryption, archive rename, and sidecar rename independently. Prove:

- validation/encryption failure publishes neither final file;
- cancellation before archive rename publishes neither file;
- sidecar publication failure after a valid archive rename leaves the archive visible as `METADATA_MISSING` and does not delete it;
- normal listing ignores staging/partial names;
- existing restore round-trip remains green.

- [ ] **Step 6: Verify focused ops suite and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_ops_scripts.py tests/test_benchmark_backup_listing.py
git diff --check
```

Commit:

```bash
git add scripts/ops.py tests/test_ops_scripts.py docs/backup-restore.md
git commit -m "feat(backups): publish staged archives atomically"
```

---

### Task 3: Backup coordinator, in-memory passphrase lifecycle, and UI job tracking

**Files:**
- Create: `app/mobile_api/services/backup_job_service.py`
- Create: `tests/test_backup_job_service.py`
- Modify: `app/mobile_api/services/backup_service.py`
- Modify: `app/mobile_api/services/job_service.py`
- Modify: `app/mobile_api/routers/backups.py`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/client.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/StatusSettingsView.tsx`
- Modify: `web/src/components/StatusSettingsView.test.tsx`

**Interfaces:**
- Produces: `BackupSecretStore.put(job_id, value)`, `.take(job_id)`, `.discard(job_id)`.
- Produces: `BackupJobCoordinator.start_backup_job(...) -> str`.
- Produces: safe persisted job type `backup`, total `6`, non-secret params only.
- Frontend consumes: `SystemBackupJobStart = {job_id: string; status: string; message: string}`.

- [ ] **Step 1: Write failing secret-store tests**

Test one-time retrieval, expiry, explicit discard, and no repr/serialization leakage:

```python
store.put("job-1", "correct horse")
assert store.take("job-1") == "correct horse"
assert store.take("job-1") == ""
assert "correct horse" not in repr(store)
```

- [ ] **Step 2: Verify RED then implement `BackupSecretStore`**

Run: `.venv/bin/python -m pytest -q tests/test_backup_job_service.py -k secret`

Implement a locked process-local mapping of opaque job id to `(expires_monotonic, secret)`. Do not expose an iterator or payload method.

- [ ] **Step 3: Write failing coordinator lifecycle tests**

Using an isolated `JobTracker`, fake `BackupService`, and real event loop, prove:

- start persists safe booleans but not passphrase;
- work starts after the caller receives a job id;
- only one coordinator job per backup directory runs at once;
- progress maps to explicit backup states;
- cancel callback observes `cancel_requested`;
- terminal success returns `completed` and safe filename in params;
- encrypted work fails safely if the secret expired;
- secret is discarded in every terminal path.

- [ ] **Step 4: Implement `BackupJobCoordinator`**

Use the shared tracker and an `asyncio.Lock` keyed by resolved backup directory. Schedule `_run_backup_job()` through `tracker.start_background_task`. Run blocking work with:

```python
item = await asyncio.to_thread(
    self.backup_service.create_backup,
    ...,
    cancel_check=lambda: self._cancel_requested(job_id),
    progress_callback=lambda step: self._publish_step(job_id, step),
)
```

Never include `passphrase` in `params`, messages, errors, operational details, or exception text.

- [ ] **Step 5: Extend `BackupService.create_backup` callback forwarding**

Keep it synchronous and reusable by CLI. It forwards callbacks to `ops.create_backup`/encryption, returns a safe list item, and performs no job persistence itself.

- [ ] **Step 6: Verify backend GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_backup_job_service.py tests/test_mobile_api_backups.py tests/test_job_service_logic.py tests/test_ops_scripts.py
```

- [ ] **Step 7: Write failing frontend client and Status tests**

Expect `createSystemBackup()` to return a job response. In `StatusSettingsView`, expect queued/running progress, cancel availability through the existing job API, and an independently usable backup list.

- [ ] **Step 8: Implement frontend tracking**

Add `backupJobId` and derive the current job from existing job polling/state. `backupBusy` remains true only while queued/running. On completed transition call `loadBackups()` once and show a safe success message. On failure/interruption/cancel show the existing safe job error. Do not keep the passphrase in React state after the POST resolves.

- [ ] **Step 9: Verify and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/api/client.test.ts src/components/StatusSettingsView.test.tsx src/App.test.tsx
.venv/bin/python -m pytest -q tests/test_backup_job_service.py tests/test_mobile_api_backups.py
git diff --check
```

Commit all Task 3 files with:

```bash
git commit -m "feat(backups): track creation in background jobs"
```

---

### Task 4: Extract connection and authentication repositories

**Files:**
- Create: `app/database/connection.py`
- Create: `app/database/auth_repository.py`
- Modify: `app/database/db.py`
- Create: `tests/test_auth_repository.py`
- Modify: `tests/test_database_db.py`
- Modify: `tests/test_mobile_api_security.py`
- Modify: `tests/test_mobile_api_users.py`

**Interfaces:**
- Produces: `connection.get_connection(db_path: Path) -> sqlite3.Connection`.
- Produces/re-exports unchanged auth function signatures from `db.py`.
- Consumes later: retention session pruning from Task 5.

- [ ] **Step 1: Add failing repository import/compatibility tests**

Assert the new module imports and facade symbols are identical:

```python
from app.database import auth_repository
from app.database import db

assert db.create_auth_session is auth_repository.create_auth_session
assert db.record_auth_login_failure is auth_repository.record_auth_login_failure
```

Add real isolated SQLite behavior tests for create/get/touch/revoke/refresh rotation/failure count/clear.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_auth_repository.py`

Expected: module does not exist.

- [ ] **Step 3: Extract the connection primitive**

Move only `get_connection` to `connection.py`. Import and re-export it from `db.py`. Do not move `init_db`, migrations, `SCHEMA`, seed logic, or transaction policies.

- [ ] **Step 4: Extract auth implementations**

Move session/failure functions and their private UTC helper to `auth_repository.py`. It imports only standard library plus `connection.get_connection`. Replace definitions in `db.py` with imports. Preserve signatures and result payloads.

- [ ] **Step 5: Verify auth/security suites and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_auth_repository.py tests/test_database_db.py tests/test_mobile_api_security.py tests/test_mobile_api_users.py
git diff --check
```

Commit:

```bash
git add app/database/connection.py app/database/auth_repository.py app/database/db.py tests/test_auth_repository.py tests/test_database_db.py tests/test_mobile_api_security.py tests/test_mobile_api_users.py
git commit -m "refactor(db): extract authentication repository"
```

---

### Task 5: Operations repository and bounded retention queries

**Files:**
- Create: `app/database/operations_repository.py`
- Modify: `app/database/auth_repository.py`
- Modify: `app/database/db.py`
- Create: `tests/test_operational_retention.py`
- Modify: `tests/test_mobile_api_system_status.py`

**Interfaces:**
- Produces: `RetentionPolicy` data passed from service layer.
- Produces: `prune_auth_records(...) -> dict[str, int]`.
- Produces: `prune_operational_events(...) -> int`.
- Produces/re-exports `record_operational_event` and `list_operational_events` unchanged.

- [ ] **Step 1: Write failing age-bound tests**

Seed active, expired, revoked, old/new failure and event rows with both `2026-01-01T00:00:00+00:00` and `2026-01-01 00:00:00` timestamp forms. Assert active sessions survive and eligible old rows are deleted.

- [ ] **Step 2: Write failing count-bound tests**

Seed more than a small test cap, invoke a batch size of two repeatedly, and assert only the newest cap remains. Count pruning for sessions must consider only revoked/expired sessions.

- [ ] **Step 3: Verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_operational_retention.py`

Expected: repository/functions absent.

- [ ] **Step 4: Extract operational-event implementation**

Move sanitizers plus record/list functions to `operations_repository.py`; re-export from `db.py`. Preserve bounded list response behavior and sanitization.

- [ ] **Step 5: Implement batch pruning**

Use `julianday(column)` comparisons and select primary keys before deletion. Each call deletes at most `batch_size` rows in one transaction and returns exact counts. Apply age eligibility first, then count overflow. Roll back the whole current batch on injected SQL failure.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_operational_retention.py tests/test_mobile_api_system_status.py tests/test_mobile_api_security.py
git diff --check
```

Commit:

```bash
git add app/database/operations_repository.py app/database/auth_repository.py app/database/db.py tests/test_operational_retention.py tests/test_mobile_api_system_status.py
git commit -m "feat(db): enforce operational retention bounds"
```

---

### Task 6: Scheduled retention service and operator-safe status

**Files:**
- Create: `app/mobile_api/services/retention_service.py`
- Create: `tests/test_retention_service.py`
- Modify: `app/mobile_api/config.py`
- Modify: `app/mobile_api/main.py`
- Modify: `app/mobile_api/routers/health.py`
- Modify: `app/mobile_api/schemas/__init__.py`
- Modify: `.env.example`
- Modify: `docs/deployment-hardening.md`
- Modify: `docs/database-lifecycle.md`

**Interfaces:**
- Produces: `RetentionService.run_once() -> RetentionSummary`.
- Produces: `run_retention_loop(service, interval_seconds, stop_event)`.
- Produces safe status fields: counts and last summary only.

- [ ] **Step 1: Write failing configuration tests**

Instantiate `MobileAPISettings` with approved defaults and reject zero/negative retention values. Add environment names:

```text
AUTH_SESSION_RETENTION_DAYS=30
AUTH_SESSION_RETENTION_MAX_ROWS=5000
AUTH_LOGIN_FAILURE_RETENTION_DAYS=30
AUTH_LOGIN_FAILURE_RETENTION_MAX_ROWS=5000
OPERATIONAL_EVENT_RETENTION_DAYS=90
OPERATIONAL_EVENT_RETENTION_MAX_ROWS=50000
OPERATIONAL_RETENTION_BATCH_SIZE=500
OPERATIONAL_RETENTION_INTERVAL_SECONDS=21600
```

- [ ] **Step 2: Verify RED and implement validated settings**

Run: `.venv/bin/python -m pytest -q tests/test_config_settings.py -k retention`

Use Pydantic field constraints or an explicit validator; do not silently clamp invalid configuration.

- [ ] **Step 3: Write failing service/scheduler tests**

Prove one run drains multiple bounded batches, yields between batches, writes one count-only event only when deletions occur, and treats SQLite busy errors as a safe skipped run. Prove no API request is required to invoke it.

- [ ] **Step 4: Implement service and FastAPI lifespan ownership**

Create an `asynccontextmanager` lifespan that starts one maintenance task after `_prepare_runtime`, passes a shutdown event, cancels/awaits it on shutdown, and never blocks app startup on a maintenance error. Preserve existing `create_app()` behavior and static mounts.

- [ ] **Step 5: Add safe status summary tests and implementation**

Return only table labels, row counts, last run time, deleted counts, and result. Reject absolute path fields and row contents in response tests.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_retention_service.py tests/test_config_settings.py tests/test_mobile_api_system_status.py tests/test_mobile_api_static.py
git diff --check
```

Commit:

```bash
git commit -m "feat(ops): schedule bounded metadata retention"
```

---

### Task 7: Reader shared types/settings and TOC seam

**Files:**
- Create: `web/src/components/reader/types.ts`
- Create: `web/src/components/reader/readerSettings.ts`
- Create: `web/src/components/reader/useReaderToc.ts`
- Create: `web/src/components/reader/ReaderTocSheet.tsx`
- Create: `web/src/components/reader/ReaderTocSheet.test.tsx`
- Modify: `web/src/components/ReaderView.tsx`
- Modify: `web/src/components/ReaderView.test.tsx`
- Modify: `web/src/components/reader/ReaderSettingsSheet.tsx`
- Modify: `web/src/components/reader/ReaderTextSurface.tsx`

**Interfaces:**
- Produces: Reader settings/mode types independent of `ReaderView`.
- Produces: `useReaderToc({chapters,currentChapterId})`.
- Produces: `ReaderTocSheet` with prepared data and `onSelectChapter(id)`.

- [ ] **Step 1: Write failing settings-module tests**

Move existing storage contract expectations into `readerSettings.test.ts`: invalid values normalize, current-root values persist, and storage keys remain byte-for-byte unchanged.

- [ ] **Step 2: Write failing TOC hook/component tests**

Test ascending/descending order, Vietnamese query matching, current chapter unchanged on order toggle, first/latest actions, current item highlight, and focus/scroll anchoring when opened.

- [ ] **Step 3: Verify RED**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/components/reader/ReaderTocSheet.test.tsx src/components/ReaderView.test.tsx
```

Expected: new modules are missing.

- [ ] **Step 4: Extract types/settings without behavior changes**

Move types and persistence helpers, update direct imports, and temporarily re-export public types from `ReaderView` only if an external test/caller still requires them.

- [ ] **Step 5: Implement TOC seam and remove inline drawer JSX/state derivation**

ReaderView keeps only `tocOpen` orchestration or consumes the hook's `open/close`. It passes chapters, preview map, current id and selection callback. The feature owns query/order/filtering.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/components/reader/ReaderTocSheet.test.tsx src/components/ReaderView.test.tsx src/components/reader/ReaderSettingsSheet.test.tsx src/components/reader/ReaderTextSurface.test.tsx
npm --prefix web run typecheck
git diff --check
```

Commit: `git commit -m "refactor(reader): extract table of contents feature"`

---

### Task 8: Reader chrome and quick-controls seam

**Files:**
- Create: `web/src/components/reader/ReaderChrome.tsx`
- Create: `web/src/components/reader/ReaderChrome.test.tsx`
- Create: `web/src/components/reader/ReaderQuickControls.tsx`
- Modify: `web/src/components/ReaderView.tsx`
- Modify: `web/src/components/reader/ReaderSettingsSheet.tsx`
- Modify: `web/src/components/ReaderView.test.tsx`

**Interfaces:**
- Produces: presentational `ReaderChrome` with top/bottom bars and callbacks.
- Produces: `ReaderQuickControls` wrapper around settings/mode availability.
- Consumes: Reader types from Task 7.

- [ ] **Step 1: Write failing interaction tests**

Render `ReaderChrome` directly and assert exit label `Thư viện`, title truncation container, previous/current/next zones, disabled boundaries, TOC/settings callbacks, immersive visibility, and 44px semantic controls.

- [ ] **Step 2: Verify RED and implement components**

Run: `npm --prefix web test -- --maxWorkers=2 src/components/reader/ReaderChrome.test.tsx`

Move existing JSX and accessibility attributes without renaming classes. Keep state/effects in ReaderView until props are stable, then move only quick-control-local state.

- [ ] **Step 3: Verify Reader regression and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/components/reader/ReaderChrome.test.tsx src/components/ReaderView.test.tsx src/components/reader/ReaderSettingsSheet.test.tsx
npm --prefix web run typecheck
git diff --check
```

Commit: `git commit -m "refactor(reader): extract reading controls"`

---

### Task 9: Lazy Reader audio feature

**Files:**
- Create: `web/src/components/reader/useReaderAudio.ts`
- Create: `web/src/components/reader/useReaderAudio.test.tsx`
- Create: `web/src/components/reader/ReaderAudioFeature.tsx`
- Modify: `web/src/components/reader/ReaderAudioBar.tsx`
- Modify: `web/src/components/ReaderView.tsx`
- Modify: `web/src/components/ReaderView.test.tsx`
- Modify: `web/vite.config.ts` only if a deterministic chunk assertion requires no config behavior change

**Interfaces:**
- Produces: `useReaderAudio(options) -> {state, actions, playback}`.
- Produces: default-exported lazy `ReaderAudioFeature`.
- Consumes: API client, selected book/chapter ids, playlist and cache callbacks through explicit options.

- [ ] **Step 1: Write failing hook tests**

Test job submission/polling, safe error conversion, playlist refresh, auto-next, cancel, cached URL precedence, bulk confirmation, and timer cleanup with fake timers and a recording API client.

- [ ] **Step 2: Verify RED and extract the hook**

Run: `npm --prefix web test -- --maxWorkers=2 src/components/reader/useReaderAudio.test.tsx`

Move audio state, derived selectors, callbacks and effects as one coherent feature. Do not leave duplicate polling in ReaderView.

- [ ] **Step 3: Add lazy-boundary test**

Mock dynamic import and assert the audio module is not requested for a closed/unused Reader, then is requested when audio is opened or active playback exists.

- [ ] **Step 4: Implement lazy feature integration**

Use module-scope `lazy(() => import('./reader/ReaderAudioFeature'))` and a small `Suspense` fallback only around the optional feature. `ReaderAudioBar` remains presentational.

- [ ] **Step 5: Verify tests/build chunk and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/components/reader/useReaderAudio.test.tsx src/components/reader/ReaderAudioBar.test.tsx src/components/ReaderView.test.tsx
npm --prefix web run build
rg -n "ReaderAudioFeature" web/dist/assets/*.js
git diff --check
```

Commit: `git commit -m "refactor(reader): lazy-load audio feature"`

---

### Task 10: Reader offline-cache hook

**Files:**
- Create: `web/src/components/reader/useReaderOfflineCache.ts`
- Create: `web/src/components/reader/useReaderOfflineCache.test.tsx`
- Modify: `web/src/components/ReaderView.tsx`
- Modify: `web/src/components/ReaderView.test.tsx`
- Modify: `web/src/state/readerCache.test.ts`

**Interfaces:**
- Produces: `useReaderOfflineCache({apiClient,bookId,chapterId,...})`.
- Returns: manifest/status/loading, current availability, cached content/audio URLs, cache/remove actions.

- [ ] **Step 1: Write failing hook tests**

Cover initial manifest/status load, service-worker update events, current chapter cache/remove, full-book cache/remove, cached audio URL, offline-with-cache and offline-without-cache, unmount cleanup, and stale async response suppression after chapter changes.

- [ ] **Step 2: Verify RED and extract ownership**

Run: `npm --prefix web test -- --maxWorkers=2 src/components/reader/useReaderOfflineCache.test.tsx`

Move all related state/effects/actions from ReaderView. Reuse `web/src/state/readerCache.ts`; do not introduce a second manifest/cache format.

- [ ] **Step 3: Verify full Reader/cache regression and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/components/reader/useReaderOfflineCache.test.tsx src/state/readerCache.test.ts src/components/ReaderView.test.tsx
npm --prefix web run typecheck
git diff --check
```

Commit: `git commit -m "refactor(reader): extract offline cache controller"`

---

### Task 11: CSS layer manifest and test harness

**Files:**
- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/base.css`
- Create: `web/src/styles/shell.css`
- Create: `web/src/styles/components.css`
- Create: `web/src/styles/utilities.css`
- Create: `web/src/test/readStyleSources.ts`
- Create: `web/src/styles.layers.test.ts`
- Modify: `web/src/styles.css`
- Modify: `web/src/pwaMobileStyles.test.js`
- Modify: `web/src/state/readerStyles.test.js`

**Interfaces:**
- Produces fixed order: `tokens, base, shell, components, features, utilities, overrides`.
- Produces a test helper that reads imported style sources rather than assuming one monolith.

- [ ] **Step 1: Write failing layer/import tests**

Assert the entry begins with the exact layer declaration and imports every source once. Assert no non-import feature rule remains in `styles.css` after the task.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix web test -- --maxWorkers=2 src/styles.layers.test.ts`

- [ ] **Step 3: Create layer files and move shared selector families mechanically**

Move variables/reset/typography to tokens/base, workflow shell/navigation to shell, shared buttons/cards/forms/dialogs to components, and helpers to utilities. Put each rule inside its approved `@layer`. Move its responsive rule into the same file near the base section.

- [ ] **Step 4: Update style-source tests without weakening assertions**

`readStyleSources` follows the explicit local import list and concatenates source text for legacy string assertions. Tests must still assert the same concrete declarations.

- [ ] **Step 5: Verify build and mobile E2E baseline, then commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/styles.layers.test.ts src/pwaMobileStyles.test.js src/state/readerStyles.test.js
npm --prefix web run build
npm --prefix web run test:e2e -- --project=chromium
git diff --check
```

Commit: `git commit -m "refactor(css): establish ordered style layers"`

---

### Task 12: Feature CSS extraction and media-query colocation

**Files:**
- Create: `web/src/styles/reader.css`
- Create: `web/src/styles/library.css`
- Create: `web/src/styles/import.css`
- Create: `web/src/styles/operations.css`
- Modify: `web/src/styles.css`
- Modify: `web/src/styles.layers.test.ts`
- Modify: `web/e2e/novel-tnn.spec.ts`

**Interfaces:**
- Produces one authoritative file per feature selector family.
- Enforces that feature media rules reside in the same file and near their base block.

- [ ] **Step 1: Add failing ownership/colocation tests**

Scan all style files and assert known prefixes (`reader-`, library/book-card, import, status/backup/jobs) have one owning feature file. Assert each feature file contains both its base selectors and relevant `@media` blocks. Reject a new global mobile override tail.

- [ ] **Step 2: Move Reader CSS with responsive blocks and verify**

Run Reader unit tests, style tests, Playwright Library→Reader flow at 360x740 and 390x844, and build. Commit only when screenshots/overflow match baseline.

- [ ] **Step 3: Move Library and Import CSS with responsive blocks and verify**

Run their component tests and mobile Playwright flows. Confirm CTA/nav do not overlap and 360px has no horizontal overflow.

- [ ] **Step 4: Move operations/status/jobs CSS and verify**

Run Status/Jobs tests and authenticated Status Playwright. Confirm backup job states remain visible without blocking core status.

- [ ] **Step 5: Verify all style ownership and commit**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 src/styles.layers.test.ts src/pwaMobileStyles.test.js src/state/readerStyles.test.js src/components/ReaderView.test.tsx src/components/ImportPanel.test.tsx src/components/LibraryBooksView.test.tsx src/components/StatusSettingsView.test.tsx
npm --prefix web run test:e2e -- --project=chromium
npm --prefix web run build
git diff --check
```

Commit: `git commit -m "refactor(css): colocate feature responsive styles"`

---

### Task 13: Extract Reader database repository behind compatibility exports

**Files:**
- Create: `app/database/reader_repository.py`
- Create: `tests/test_reader_repository.py`
- Modify: `app/database/db.py`
- Modify: `tests/test_database_db.py`
- Modify: `tests/test_mobile_api_reader.py`
- Modify: `tests/test_mobile_api_reader_ai.py`

**Interfaces:**
- Produces/re-exports existing Reader progress, annotation, AI/dictionary cache, X-Ray entity/mention, and timeline functions unchanged.
- Depends only on `connection.get_connection` and standard-library serialization helpers.

- [ ] **Step 1: Write failing compatibility and transaction tests**

Assert representative facade identities and real behavior for progress upsert, annotation conflict/deletion, cache upsert/read, X-Ray entity and timeline ordering. Add rollback injection for a multi-statement Reader write if present.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_reader_repository.py`

- [ ] **Step 3: Move one cohesive block at a time**

Order: progress/annotations; AI/dictionary caches; X-Ray entities/mentions/timeline. After each movement, import/re-export from `db.py` and run the relevant test subset. Do not move books, chapters, glossary, source, TTS, or import transaction functions.

- [ ] **Step 4: Verify API and DB contracts, then commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_reader_repository.py tests/test_database_db.py tests/test_mobile_api_reader.py tests/test_mobile_api_reader_ai.py app/mobile_api/tests/test_reader_xray_service.py
git diff --check
```

Commit: `git commit -m "refactor(db): extract reader repository"`

---

### Task 14: Content-file service, Reader service, and QA protocol cycle removal

**Files:**
- Create: `app/mobile_api/services/content_file_service.py`
- Create: `app/mobile_api/services/reader_service.py`
- Create: `tests/test_content_file_service.py`
- Create: `tests/test_reader_service.py`
- Modify: `app/mobile_api/services/pipeline_service.py`
- Modify: `app/mobile_api/services/qa_service.py`
- Modify: `tests/test_qa_service.py`
- Modify: `tests/test_mobile_api_reader.py`
- Modify: `tests/test_mobile_api_db_logic.py`

**Interfaces:**
- Produces: `ChapterContentReader` protocol with `db_path`, `get_chapter_source(id)`, and `get_chapter_translation(id)`.
- Produces: `ContentFileService.resolve_artifact_file`, `.get_chapter_source`, `.get_chapter_translation`, `.get_chapter_content`.
- Produces: `ReaderService` for Reader state/annotation/content orchestration using `reader_repository` and `ContentFileService`.
- `PipelineService` delegates existing signatures to these services.

- [ ] **Step 1: Write a failing circular-import contract test**

Import `qa_service` with `pipeline_service` deliberately absent from `sys.modules` and assert `qa_service` does not import the concrete class. Type-check a recording object implementing the protocol through real `QAService.run_deterministic_qa` behavior.

- [ ] **Step 2: Verify RED and introduce the protocol**

Run: `.venv/bin/python -m pytest -q tests/test_qa_service.py -k 'protocol or import'`

Use `typing.Protocol`; remove runtime `from ...pipeline_service import PipelineService`. Keep deterministic QA pure helpers unchanged.

- [ ] **Step 3: Write failing content-file service tests**

Cover current paths, legacy compatibility resolution, blank/missing/escape/symlink handling, file-vs-directory validation, raw/cleaned/translated precedence, HTML payload, and unchanged file hashes.

- [ ] **Step 4: Implement `ContentFileService` and Pipeline delegates**

Move only artifact resolution and chapter source/translation/content reads. Constructor receives `data_dir`, `db_path`, and `legacy_artifact_root`. `PipelineService.__init__` creates it; compatibility methods delegate directly.

- [ ] **Step 5: Write failing Reader service tests**

Cover progress, annotation create/update/delete/sync, and content access through repositories. Use isolated DB and temp data only.

- [ ] **Step 6: Implement `ReaderService` and migrate Reader router dependencies narrowly**

Keep route paths and response models unchanged. `PipelineService` delegates during migration; update only Reader-focused router construction where tests prove compatibility.

- [ ] **Step 7: Verify backend contracts/performance and commit**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_content_file_service.py tests/test_reader_service.py tests/test_qa_service.py tests/test_mobile_api_reader.py tests/test_mobile_api_reader_ai.py tests/test_mobile_api_db_logic.py tests/test_database_performance_contracts.py tests/test_import_transaction_performance_contracts.py
.venv/bin/python -c "from app.mobile_api.services.qa_service import QAService; from app.mobile_api.services.pipeline_service import PipelineService; print('imports-ok')"
git diff --check
```

Commit: `git commit -m "refactor(services): extract reader content seams"`

---

### Task 15: Documentation, full verification, and requirement audit

**Files:**
- Update: `docs/job-architecture.md`
- Update: `docs/backup-restore.md`
- Update: `docs/backup-metadata-sidecars.md`
- Update: `docs/database-lifecycle.md`
- Update: `docs/code-modularity-plan.md`
- Update: `docs/modularization-readiness.md`
- Update: `docs/reader-ux.md`
- Update: `docs/deployment-hardening.md`
- Create: `docs/p2c-background-retention-modularity-implementation-note.md`

**Interfaces:**
- Produces current runbooks and final requirement-by-requirement evidence.

- [ ] **Step 1: Update active operational documentation**

Document `202` backup jobs, polling/cancel/retry rules, in-memory passphrase loss on restart, staging behavior, retention defaults/environment settings, maintenance scheduling, repository facades, Reader modules, CSS layers, and rollback per commit.

- [ ] **Step 2: Add the completion matrix**

The implementation note must map every approved acceptance criterion to authoritative code, test, benchmark/build, or runtime evidence. Mark missing evidence as incomplete; do not infer completion from file existence.

- [ ] **Step 3: Run focused backend verification**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_ops_scripts.py tests/test_backup_job_service.py tests/test_mobile_api_backups.py \
  tests/test_job_service_logic.py tests/test_operational_retention.py tests/test_retention_service.py \
  tests/test_auth_repository.py tests/test_reader_repository.py tests/test_content_file_service.py \
  tests/test_reader_service.py tests/test_qa_service.py tests/test_mobile_api_reader.py \
  tests/test_mobile_api_reader_ai.py tests/test_mobile_api_system_status.py
```

- [ ] **Step 4: Run focused frontend and browser verification**

Run:

```bash
npm --prefix web test -- --maxWorkers=2 \
  src/components/ReaderView.test.tsx \
  src/components/reader/ReaderTocSheet.test.tsx \
  src/components/reader/ReaderChrome.test.tsx \
  src/components/reader/useReaderAudio.test.tsx \
  src/components/reader/useReaderOfflineCache.test.tsx \
  src/components/StatusSettingsView.test.tsx \
  src/styles.layers.test.ts
npm --prefix web run test:e2e -- --project=chromium
npm --prefix web run typecheck
npm --prefix web run build
```

- [ ] **Step 5: Run full project verification**

Run `scripts/verify.sh`. If unbounded Vitest workers fail to start because WSL swap is exhausted, record the exact failure, run the complete frontend suite in deterministic two-worker shards, and do not describe the script itself as passing. Also run `git diff --check` and package checks defined by the repository.

- [ ] **Step 6: Verify operator safety**

Record operator DB size, mtime, SHA-256, integrity, and FK count before and after tests. Tests must use isolated directories and leave operator DB/archive hashes unchanged. Do not run retention apply against the operator DB without a separately reviewed maintenance action.

- [ ] **Step 7: Commit documentation and final evidence**

```bash
git add docs/job-architecture.md docs/backup-restore.md docs/backup-metadata-sidecars.md \
  docs/database-lifecycle.md docs/code-modularity-plan.md docs/modularization-readiness.md \
  docs/reader-ux.md docs/deployment-hardening.md \
  docs/p2c-background-retention-modularity-implementation-note.md
git commit -m "docs: record P2C operability and modularity"
```

## Plan Self-Review Checklist

- [x] Every design acceptance criterion maps to at least one task and explicit verification command.
- [x] Backup archive/restore format remains unchanged.
- [x] Passphrase lifecycle has positive and negative persistence tests.
- [x] Retention has age, count, batching, rollback, active-session and scheduler tests.
- [x] Reader TOC, controls, audio, and offline cache each have a module and direct tests.
- [x] CSS layer order and responsive colocation are mechanically asserted.
- [x] Database extraction uses compatibility re-exports and leaves optimized book/import seams in place.
- [x] QA runtime circular import is explicitly tested and removed.
- [x] No task requires operator DB mutation, paid providers, external queues, or broad schema redesign.
