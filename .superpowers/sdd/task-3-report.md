# Task 3 report

## Status

Implemented. Backend lifecycle and persistence tests pass in focused runs; frontend TypeScript validation passes. Required broad Pytest and Vitest commands were attempted but hit the known WSL/DrvFS uninterruptible I/O stall, as detailed under concerns.

## Commits

- `feat(backups): track creation in background jobs` (current Task 3 commit)

## Files changed

- `app/mobile_api/job_states.py`
- `app/mobile_api/routers/backups.py`
- `app/mobile_api/services/backup_job_service.py`
- `app/mobile_api/services/backup_service.py`
- `app/mobile_api/services/job_service.py`
- `tests/test_backup_job_service.py`
- `web/src/App.tsx`
- `web/src/api/client.test.ts`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/components/StatusSettingsView.test.tsx`
- `web/src/components/StatusSettingsView.tsx`
- `.superpowers/sdd/task-3-report.md`

## Backend RED / GREEN

- RED secret store: `ModuleNotFoundError: app.mobile_api.services.backup_job_service`.
- GREEN secret store: 3 passed.
- RED coordinator: `ImportError: cannot import name 'BackupJobCoordinator'`.
- RED encrypted-cancel cleanup: the published plain archive still existed after `BackupCancelled`.
- GREEN focused lifecycle/service suite: `11 passed in 9.39s`.
- GREEN protected backup API regression: `8 passed in 24.50s` (one pre-existing passlib deprecation warning).
- GREEN relevant JobTracker cancellation regression: `1 passed, 30 deselected in 12.50s` (same warning).

## Frontend RED / GREEN

- RED: `npm --prefix web run typecheck` reported missing `SystemBackupJobStart`, `backupJob`, and `onCancelBackup` contracts.
- GREEN: `npm --prefix web run typecheck` completed successfully.
- Added client coverage for the 202 job response and Status coverage for progress, cancellation, terminal error, and independently visible inventory.

## Secret non-persistence evidence

- `BackupSecretStore` is locked, process-local, one-time, expiring, explicitly discardable, slot-backed, repr-safe, and rejects serialization.
- The persisted SQLite job is reloaded in the test and contains only option booleans plus the terminal safe filename; the submitted secret value is absent from `to_record()` JSON.
- The coordinator catches worker exceptions without logging exception text, persists only fixed safe errors, and discards credentials on success, cancellation, expiry, and failure.
- The API audit event contains only job id and queued result. The frontend keeps the prompt value in function-local request data, not React state.

## Job lifecycle / cancel / single-directory evidence

- The start method creates and returns the job id before the scheduled blocking service begins.
- Jobs use the shared `JobTracker`, type `backup`, total `6`, and explicit backup states through completion.
- Cooperative backup cancellation sets `cancel_requested` without cancelling the asyncio wrapper around a still-running worker thread; the Task 2 callback observes the flag before the directory lock releases.
- An `asyncio.Lock` keyed by resolved backup directory held maximum concurrent service calls at one in the test.
- Success persists a basename-only `backup_filename`. Encryption cancellation removes the interim plain archive and sidecar.

## Self-review

- Reused the existing tracker, task, polling, and cancellation APIs; no queue, registry, dependency, schema, retention, Reader, CSS, provider, or operator database work was added.
- Listing/download authentication, response formats, sidecar gating, and backup archive formats are unchanged.
- Added the missing valid state edge for an unencrypted backup (`VALIDATING_BACKUP -> PUBLISHING_BACKUP`). Encrypted work ignores the interim plain-publication callback until encryption begins.
- `git diff --check` and frontend typecheck pass.

## Concerns

- The required full backend command stalled in uninterruptible DrvFS I/O after partial progress; it was terminated, then the changed backend surfaces were verified in focused passing runs above.
- The exact required Vitest command and a single-thread threads-pool retry both stalled before collection under DrvFS and were terminated with a 60-second bound. No stale Pytest/Vitest workers were left. Runtime frontend test completion therefore remains an environment-limited verification gap; TypeScript validation is green.

## Fix: cancellation drain and App orchestration coverage

### Status

- Fixed the review finding that external asyncio cancellation could release the backup-directory lock while `asyncio.to_thread` work was still running.
- Added App-level proof that a polled backup completion reloads the inventory exactly once and does not retain or render the submitted encryption value.

### Backend RED / GREEN

- RED: `test_external_wrapper_cancel_holds_directory_lock_until_worker_exits` observed `service.call_count == 2` while the first worker was still blocked; expected `1`. The old coordinator had already released its lock and discarded its credential.
- GREEN targeted: `1 passed, 11 deselected in 6.53s`.
- GREEN focused coordinator suite: `12 passed in 9.52s`.
- GREEN combined coordinator and protected backup API suite: `20 passed, 1 warning in 27.65s`; the warning is the pre-existing passlib `crypt` deprecation.

### Cancellation and terminal-ordering evidence

- The coordinator now retains an explicit asyncio task for the thread worker and awaits it through `asyncio.shield`.
- External cancellation sets a process-local cooperative event and the tracker's durable `cancel_requested` flag, then drains the real worker under the same directory lock before re-propagating cancellation.
- Repeated task cancellation while draining cannot release the lock early. The tracker wrapper only persists `cancelled` after the worker exits.
- The focused test proves the first job stays non-terminal, the credential store is not discarded, and the second same-directory job does not enter until the first worker is released. Final cleanup and maximum concurrency of one are also asserted.

### Frontend RED / GREEN

- The new App orchestration test forces the SSE request to fail, advances the existing fallback poll to a completed backup job, and asserts exactly one post-completion `listSystemBackups()` reload.
- It verifies the submitted encryption value is present only in the POST body and absent from rendered content, local storage, and session storage after resolution.
- The first focused App-only Vitest attempt hit the intermittent DrvFS collection stall and was terminated by the 60-second bound.
- GREEN required frontend retry: `2 test files passed`, `18 tests passed`, duration `37.69s` for `src/App.test.tsx` and `src/components/StatusSettingsView.test.tsx`.
- GREEN TypeScript: `npm --prefix web run typecheck` exited `0`.

### Concerns

- DrvFS test startup remains intermittently slow, but the required frontend test set completed successfully on the bounded retry. No stale test workers remain.
