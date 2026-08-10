# PR9 Daily-job Cancellation Design

## Goal

Make cancellation of a database-backed daily translation job durable: once cancellation is requested, the job remains `cancelled` / `CANCELED` and the daily worker starts no subsequent chapter.

## Scope

This PR changes only the daily-job cancellation path in `JobService` and its focused regression coverage. It does not alter translation provider behavior, retry policy, TTS, backup jobs, import jobs, job schemas, or public API contracts.

## Current failure mode

`JobService._run_daily_job()` reads cancellation through the tracker's in-memory `JobStatus`. A cancellation written durably by another tracker or process can therefore be invisible to the running worker. The worker may start another chapter and eventually attempt to mark the job `completed`.

The canonical job-state graph already rejects `CANCELED -> COMPLETED` when the in-memory state is current, but that protection is insufficient when the worker holds a stale cached job record.

## Design

### Durable cancellation read

For a tracker backed by SQLite, the daily worker's cancellation check reads the persisted mobile-job record and treats either of these conditions as cancellation:

- `cancel_requested` is true;
- persisted status is `cancelled` or `canceled`.

For an in-memory tracker, the existing `JobStatus.cancel_requested` behavior remains unchanged.

### Daily worker control flow

The worker checks cancellation:

1. before starting each chapter;
2. immediately after the current chapter returns;
3. immediately before the final `completed` transition.

When cancellation is observed, the worker records `cancelled` / `CANCELED` through the normal tracker transition and returns from the coroutine. It must not use a `break` that can fall through to the completion update.

The current in-flight translation is cooperative only when its provider accepts a cancellation callback. This PR guarantees that no later chapter begins; it does not claim to roll back work already completed by the current provider call.

## Regression test

Add one required RED-first async test in `tests/test_job_service_logic.py`:

- create a SQLite-backed daily job with two pending chapters;
- let the first chapter start and complete;
- write the cancellation request through a separate durable database path so the running tracker's cache is stale;
- await the worker;
- assert only the first chapter was invoked;
- assert the persisted final status/state are `cancelled` / `CANCELED`;
- assert no successful transition to `completed` occurred after cancellation.

The test must fail on the pre-fix code because the second chapter runs or the job reaches `completed`. Production code is changed only after that failure is observed.

## Error handling and compatibility

- A missing job still causes the worker to return without work.
- Database read failures follow the existing job failure path and expose only the sanitized daily-job failure message.
- Cancellation remains idempotent.
- Existing callers and response schemas do not change.

## Validation

Run, in order:

1. the new focused test and capture the expected RED result;
2. the same focused test after the minimal fix;
3. all job-service tests;
4. backend lint/typecheck wrapper;
5. full backend test suite when the focused gates are green;
6. `git diff --check`.

## Definition of done

- The required regression test is demonstrated RED before production changes.
- A durable cancellation visible only in SQLite stops the daily worker before the next chapter.
- The final persisted status/state remain `cancelled` / `CANCELED`.
- No unrelated job behavior or API contract changes.
