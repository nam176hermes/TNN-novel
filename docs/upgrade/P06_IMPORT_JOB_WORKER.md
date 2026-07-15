# P06 — Sequential Import Job Worker

## Scope

P06 activates the P05 import-job records through a small, injected pipeline
interface.  It intentionally provides no HTTP route, SSE stream, autonomous
background thread, retry scheduler, or parallel execution.

## Durable worker contract

- `ImportJobService` creates jobs/tasks, records enqueue requests, exposes
  owner-scoped reads/cancel/retry operations, and runs one task at a time.
- `ImportJobRepository.claim_next_task()` claims one queued task under
  `BEGIN IMMEDIATE` and assigns a task lease. The lease is refreshed between
  stages, and a second worker cannot claim the same row.
- The worker records `fetching`, `parsing`, `validating`, `importing`, then a
  terminal stage as task events in the existing transaction-safe event stream.
- The pipeline is injected with `run_stage(stage, task, cancel_check)`.  P06
  does not call a real source or browser; a later integration is responsible
  for adapting the P01-P04 fetch/import contract to this protocol.

## Cancellation, recovery, and retry

- Cancel is durable and idempotent.  Queued work is terminally cancelled;
  claimed work observes the durable flag before and after every stage.
- A lease-expired running task is requeued by `recover_interrupted_jobs()` with
  recovery events.  The job is reopened only through this recovery operation.
- `retry_failed_tasks()` only resets failed tasks that carry `retryable=true`.
  Successful, cancelled, and verification-required tasks never restart there.
- P04 remains the idempotency boundary for a real importer.  P06 preserves the
  canonical task identity across recovery and does not create a second task.

## Migration and rollback

P06 extends `chapter_tasks` additively with `retryable`, `lease_token`,
`lease_owner`, and `lease_expires_at`, plus a lease-expiry index.  Database
initialization uses column-existence checks, so existing databases require no
data rewrite.

Rollback is code rollback only: the additive columns and index may remain
unused by the P05 code.  Do not delete job/task/event records or attempt a
schema rebuild as part of rollback.

## Validation

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
.venv/bin/python -m pytest -q tests/test_import_job_worker.py tests/test_import_job_repository.py
scripts/lint.sh
.venv/bin/python -m pytest -q
git diff --check
```
