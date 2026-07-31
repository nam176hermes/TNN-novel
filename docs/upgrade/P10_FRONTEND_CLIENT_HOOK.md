# P10 — Frontend Import Job Client and Hook

## Scope

P10 builds the typed frontend service boundary for the durable import API from
P09. It deliberately does not connect the hook to `ImportPanel`, alter layout,
or add a production dependency. P11 owns the larger ImportPanel migration.

## Type contract

`web/src/api/types.ts` now exposes canonical names for:

- `ImportJobStatus` and `ImportJob`;
- `ChapterTaskStatus`, `ChapterTaskStage`, and `ChapterTask`;
- `ImportJobEventType` and `JobEvent`;
- `ImportJobCreateRequest` and `ImportJobAcceptedResponse`;
- `JobEventSubscription` and reconnect options.

The P09 names `ImportJobAccepted`, `ImportJobTaskSummary`,
`ImportJobSnapshot`, `ImportJobEvent`, and `ImportJobEventStream` remain aliases
so current callers continue to typecheck.

## API client

The canonical import-job client surface is:

```text
createImportJob(request)
getImportJob(jobId)
cancelImportJob(jobId)
retryFailedTasks(jobId)
subscribeJobEvents(jobId, listener, { cursor, lastEventId })
```

`subscribeJobEvents` continues to use authenticated `fetch`, a streamed
`ReadableStream`, and an internal `AbortController`. Reconnect can send both
the query cursor and `Last-Event-ID`. The P09 methods
`retryFailedImportTasks` and `openImportJobEventStream` delegate to the new
canonical names.

## Hook state machine

`useImportJob` exposes these phases:

```text
idle → creating → queued → running → terminal
                         ↘ reconnecting
                         ↘ error
```

Its main operations are `createJob`, `refreshSnapshot`, `cancelJob`,
`retryFailedTasks`, `resumeJob`, and `clearJob`.

Key consistency rules:

- GET `/api/import/jobs/{job_id}` is the only source of mutable job/task state.
- An SSE event only advances the monotonic cursor and requests a new snapshot.
- Events with the wrong job id, duplicate sequence, or an older sequence are
  ignored without changing state.
- Concurrent snapshot requests use last-request-wins reconciliation so an old
  response cannot overwrite a newer request.
- Terminal snapshots abort the active stream and remove the persisted resume
  id.

## Reconnect and polling

The hook performs an initial snapshot reconciliation before subscribing.
Unexpected stream closure uses bounded exponential backoff and reconnects with
the latest cursor in both supported forms. After the configured number of SSE
failures, the hook polls snapshots until terminal state. Polling failures are
bounded before entering the typed `error` phase. Authentication failures invoke
the optional auth callback immediately.

## Refresh persistence

Only the latest non-terminal job id is stored in
`novel-import-job-id-v1`. No snapshot, task metadata, URL, event data, HTML,
chapter content, token, cookie, or secret is stored. Storage access is guarded
so private-browsing/storage failures do not break the active session.

## Error mapping

`mapImportJobError` maps typed backend codes such as URL policy failures,
timeouts, rate limits, user verification, content/parser failures, quota,
duplicate, cancellation, and job ownership/state errors to safe Vietnamese
domain messages. It does not surface provider details or source payloads.

## Verification coverage

- Reducer progression through every P10 phase.
- Duplicate and out-of-order event idempotency.
- Create, snapshot reconciliation, and terminal event flow.
- SSE reconnect with cursor and `Last-Event-ID`.
- Polling fallback after SSE failure.
- Cancel/retry API usage and authoritative snapshot reconciliation.
- Page-refresh resume from versioned localStorage.
- Typed error-code mapping.
- P09 API method compatibility.

Verified results:

- Targeted API client and hook tests: `56 passed in 25.24s`.
- Full frontend suite: `81 test files passed`, `724 tests passed in 545.78s`.
- Repository lint wrapper and frontend typecheck passed.
- Production build passed with the pre-existing unresolved
  `sidebar-scenery.png` asset warning.
- `git diff --check` passed.
