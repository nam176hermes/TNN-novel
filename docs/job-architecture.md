# Job Architecture and Recovery

Novel-TNN uses a SQLite-backed, in-process job runner. It is designed for a
single operator and avoids external queue dependencies.

## Current Architecture

- FastAPI request handlers create job rows in `mobile_jobs`.
- System-backup creation returns `202 Accepted` after creating a `backup` job;
  archive work does not run in the request handler.
- `JobTracker.start_background_task()` claims a queued job with a SQLite lease.
- The claimed coroutine runs in the current API process.
- Long blocking work is offloaded with `asyncio.to_thread()` where practical.
- A heartbeat extends the lease while a job is running.
- Startup and job reads mark stale claimed/running jobs as interrupted.
- Provider attempts are stored in `job_attempts`.
- Sanitized lifecycle logs are stored in `job_logs`.

The stale and heartbeat thresholds are configurable:

- `JOB_STALE_AFTER_SECONDS`, default `300`
- `JOB_HEARTBEAT_INTERVAL_SECONDS`, default `30`

This is not Celery, Redis, or a multi-process durable queue. If the process dies,
the running coroutine is lost. The persisted job state lets the operator see the
failed step and retry safely.

## State Model

`mobile_jobs.status` remains the backward-compatible API status used by existing
frontend code:

- `queued`
- `retrying`
- `running`
- `completed`
- `failed`
- `cancelled`
- `interrupted`

`mobile_jobs.state` is the canonical durable state:

- `QUEUED`
- `CLAIMED`
- `LOADING_SOURCE`
- `CLEANING_TEXT`
- `SPLITTING_CHUNKS`
- `TRANSLATING`
- `QA_CHECKING`
- `GLOSSARY_EXTRACTING`
- `SAVING_CHAPTER`
- `GENERATING_TTS`
- `EXPORTING`
- `PREPARING_BACKUP`
- `WRITING_BACKUP`
- `VALIDATING_BACKUP`
- `ENCRYPTING_BACKUP`
- `PUBLISHING_BACKUP`
- `COMPLETED`
- `FAILED`
- `CANCELED`
- `STALE_INTERRUPTED`
- `RETRYING`

Terminal jobs cannot transition back to running states. Retry creates a new job
attempt instead of mutating the failed job back into a live job.

Allowed state transitions are intentionally narrow:

- `QUEUED` or `RETRYING` may be claimed or directly enter a running step for
  in-memory/manual tracker compatibility. They may also complete empty, fail,
  cancel, or be marked stale.
- `CLAIMED` may enter any running step or terminal state.
- Import jobs may move between `LOADING_SOURCE` and `SAVING_CHAPTER`.
- Translation jobs may remain `TRANSLATING`, then move to QA/glossary/save or a
  terminal state. They cannot jump back to `QUEUED`, `RETRYING`, or
  `LOADING_SOURCE` in-place.
- QA/glossary/save/TTS/export steps may continue forward within their workflow
  or enter a terminal state.
- `COMPLETED`, `FAILED`, `CANCELED`, and `STALE_INTERRUPTED` are terminal.

Operator retry/duplicate actions create a separate job row. They do not revive a
terminal job row in place.

## Step Progress

Jobs persist:

- current book and chapter id
- current chunk index and total chunk estimate when available
- current canonical step
- provider and model
- retry count
- started, updated, completed, failed, and finished timestamps
- cancel request flag
- last safe error message
- optional internal error reference id

Chunk totals for translation jobs are best-effort estimates unless the deeper
translation pipeline exposes exact chunk callbacks.

## Async Boundaries

Request handlers must not run long work directly. Translation, QA, TTS, and
source import work run through background jobs. Blocking sync work is offloaded
to worker threads from async job coroutines.

Sync code that must invoke an async API uses `app.utils.asyncio_bridge.run_coro_sync`.
It calls `asyncio.run()` only when there is no active event loop; inside an
active event loop it runs the coroutine in a dedicated thread. This prevents the
runtime error:

```text
asyncio.run() cannot be called from a running event loop
```

## Cancel

Cancel requests set `mobile_jobs.cancel_requested = 1` first. Running jobs check
the flag between major steps and chunks. Translation and TTS also pass
cancel-check callbacks into their chunk loops where supported. If the in-process
task still exists, the tracker also cancels it so the job can stop promptly.
Partial outputs are left in place and the job moves to `cancelled` / `CANCELED`.

Backup cancellation is stricter than the generic partial-output rule. The
archive builder checks cancellation between bounded member operations and
keeps partial names in a private staging directory. Cancellation before final
publication leaves no final archive or sidecar. If cancellation arrives while
a blocking worker thread is active, the coordinator drains that worker before
releasing the per-backup-directory lock or discarding its in-memory secret.

Cancel is cooperative. A provider HTTP call or other blocking function already
running in a worker thread may finish its current call before noticing cancel.
The worker preserves `CANCELED` if the cancel flag was already set.

## Retry

Translation retry uses the failed/interrupted job's saved targets and config.
Completed chapters with existing translated output are skipped. Retry increments
`retry_count`, preserves the previous safe error, and records lifecycle logs.

Retry does not overwrite completed translated chapters. Manually edited
translations are treated as completed if the translated text path exists and the
chapter has a translated-like status. TTS failed-chunk retry only resets failed
or QA-failed chunks; completed chunk files are reused. Export is still a
request/download service rather than a durable export job, so partial export
retry is limited to regenerating the file through the export endpoint.

Backup jobs are not accepted by the translation retry endpoint. To retry a
plain backup, submit a new authenticated `POST /api/system/backups`; the new
job receives a collision-resistant filename and cannot overwrite a completed
archive. To retry an encrypted/secrets backup, submit a new request and enter
the passphrase again. The passphrase is intentionally unavailable after the
original process or job ends.

## Backup Credential Lifecycle

Persisted backup job parameters contain only booleans for included modules and,
after success, a safe archive filename. A backup passphrase is kept in a
locked, process-local, take-once store with a short expiry. It is not written to
SQLite, job logs, audit details, API responses, or error messages.

Restarting the API loses that store by design. A queued/running encrypted
backup is then interrupted or fails with a fixed safe credential-expired
message. There is no automatic encrypted retry: the authenticated operator must
queue a new backup and supply the passphrase again.

## Restart Recovery

On startup and job reads, stale queued/retrying/running jobs are marked:

- `status = interrupted`
- `state = STALE_INTERRUPTED`
- safe message: `Job interrupted before completion. Please retry the job.`

The app does not automatically resume a stale coroutine after restart. The
operator must retry or duplicate the job so completed outputs can be skipped
safely.

Fresh running jobs with a valid lease and recent heartbeat are not marked stale.
Terminal jobs are ignored by stale recovery even if their timestamps are old.

## Logs

`job_logs` records sanitized lifecycle events:

- job creation
- claim/transition
- cancel request
- invalid transition rejection
- failure/interruption

Logs must not store provider keys, auth headers, raw stack traces, local paths,
private book text, or raw prompts. Detailed debugging remains in server logs.

Job log messages and detail values are truncated to 500 characters before
storage. The logs endpoint is authenticated and bounded to at most 100 entries
per request, with `limit` and `offset` query parameters for pagination.

There is no automatic log-retention purge yet. For long-lived deployments,
schedule a small maintenance task to remove old `job_logs` rows after backup, or
replace the in-process runner with a queue that has built-in retention policy.

## Known Limitations

- The runner is still in-process and single-operator oriented.
- Process restart does not resume archive construction; encrypted backup
  credentials are deliberately lost and must be resubmitted.
- Exact translation chunk progress is estimated until the translation engine
  exposes chunk callbacks.
- Cancel is cooperative and cannot kill an already-running provider request in a
  worker thread.
- Export is not yet modeled as a durable background job.
- A true multi-worker durable queue would still be needed for public SaaS scale.
