# PR9 Cross-Tracker Backup Cancellation Recovery Plan

> **Execution:** Use `superpowers:subagent-driven-development` with a fresh implementer. Apply strict RED/GREEN TDD and independent review after each task.

**Goal:** Make database-backed backup cancellation correct when the cancellation request and the owning backup coordinator run in different trackers/processes, without weakening PR9's atomic sticky-cancellation guarantees.

**Root cause:** A non-owner `JobTracker.cancel_job()` has no local asyncio task and currently generic-terminalizes a queued backup before the owner can claim it and record `backup_job_terminal`. Separately, `BackupJobCoordinator._cancel_requested()` reads only the owner's cached `JobStatus`, so a remote durable cancellation can be missed while waiting for the directory lock or while the provider emits no progress callbacks.

## Global constraints

- A database-backed backup's owning coordinator is responsible for its dedicated terminal event.
- A non-owner tracker must persist cancellation intent but must not infer ownership from the absence of a local asyncio task and must not generic-terminalize the backup.
- The coordinator must consult durable database state before backup work and from the cooperative provider cancellation callback.
- Terminal status and the exactly-one `backup_job_terminal` event must agree on `cancelled`, `completed`, or `failed`.
- Preserve the atomic sticky cancellation and telemetry reconciliation already implemented in PR9.
- Preserve in-memory tracker behavior and non-backup cancellation behavior.
- No sleeps as synchronization, no production/operator database mutation, and no deploy, restart, push, or merge.

## Task 1: Add deterministic cross-tracker RED regressions

**Files:**

- Modify `tests/test_backup_job_service.py`

Add two tests using one owner `JobTracker(db_path=...)` and a distinct remote `JobTracker(db_path=...)`:

1. **Queued/pre-claim cancellation:** the remote tracker cancels immediately after the owner schedules the backup. Assert the owner records exactly one warning `backup_job_terminal` with `result=cancelled`, backup work never starts, and the final durable/cache state is `cancelled / CANCELED / cancel_requested=True`.
2. **Lock-wait/running cancellation:** hold the coordinator directory lock or provider deterministically, cancel through the remote tracker, then release it. Use a provider that does not emit progress callbacks. Assert provider cancellation is observed before publication/completion, exactly one cancelled event is recorded, and no completed/info event exists.

Run both tests before production edits and record behavioral RED output. Import/fixture failures do not count as RED.

## Task 2: Make backup cancellation ownership-aware and durable

**Files:**

- Modify `app/mobile_api/services/job_service.py`
- Modify `app/mobile_api/services/backup_job_service.py`
- Modify tests only as required by Task 1 or focused regressions

Implement the smallest ownership-safe behavior:

- For a database-backed backup, `JobTracker.cancel_job()` always persists cancellation intent and never terminalizes merely because this tracker has no local task. A locally owned task may continue through its cooperative coordinator path.
- `BackupJobCoordinator._cancel_requested()` reads the durable mobile-job row when `db_path` exists, treats durable `cancel_requested` or cancelled status as authoritative, and reconciles the owner's cached flag.
- The coordinator checks durable cancellation before entering archive work; the provider's `cancel_check` uses the same durable-aware function.
- Keep exactly-once terminal-event behavior and ensure an atomic cancellation-won save cannot be followed by a completed/info event.

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python -m pytest -q -s \
  tests/test_backup_job_service.py
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python -m pytest -q -s \
  tests/test_job_service_logic.py tests/test_database_db.py
```

Commit the focused fix after GREEN evidence and self-review.

## Task 3: Final verification

With temporary dependency symlinks validated and removed afterward, run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/lint.sh
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s
git diff --check
git diff --check "$(git merge-base main HEAD)..HEAD"
```

Require an independent whole-branch review of the PR9 diff. PR9 is ready only when all gates pass, the worktree is clean, and temporary symlinks are absent.
