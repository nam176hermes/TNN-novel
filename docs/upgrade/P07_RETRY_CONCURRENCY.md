# P07 — Retry, bounded concurrency, and ordered import

- `RetryPolicy` classifies fetch errors, applies capped exponential backoff with
  injected jitter, honors `retry_after_seconds`, and enforces attempt/time budgets.
- Retry state is durable: `waiting_retry`, `next_attempt_at`, and a sanitized
  `task_retry_scheduled` event. Cancellation is checked before/after backoff.
- `BoundedTaskRunner` limits direct work globally (4), per host (1), browser
  work globally (1), and accepts at most 64 queued tasks.
- `ImportJobService.run_job()` claims a bounded batch, runs independent stages
  through the runner, and uses an ordered gate so `IMPORTING` proceeds by
  `(chapter_number, task_id)`. A failed earlier task releases its turn.
- No router, SSE, scheduler thread, source call, or source payload logging was
  added. The injected pipeline remains the boundary for real fetch/import work.

## Deadlock regression fix

The bounded runner uses separate network and import callbacks. Global and
per-host semaphores cover only FETCHING/PARSING/VALIDATING and are released
before the ordered IMPORTING callback waits on its chapter turn. This prevents
a fast later chapter from holding the host slot while an earlier chapter is
still waiting to fetch. Regression coverage verifies both semaphore release
and the three-chapter out-of-order case.

## Verification

- Deadlock/cancellation regressions: `3 passed in 6.99s`.
- Import-job runtime, worker, and repository tests: `20 passed in 36.24s`.
- Full backend suite: `892 passed, 2 warnings in 1007.99s (0:16:47)`.
