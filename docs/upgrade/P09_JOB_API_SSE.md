# P09 — Durable Import Job API and SSE

## Scope

P09 exposes the P05–P07 durable URL import engine through FastAPI and adds an
authenticated fetch-streaming client transport. It does not change the React
UI, add an autonomous scheduler, call a source in tests, or persist source
content in job metadata/events.

## API contract

All routes require the authenticated owner from `get_current_user`. A job
owned by another user is returned as typed `job_not_found` (HTTP 404) so the
API does not disclose cross-owner existence.

| Method | Route | Result |
|---|---|---|
| `POST` | `/api/import/jobs` | HTTP 202 with `job_id`, queued status, and total |
| `GET` | `/api/import/jobs/{job_id}` | Authoritative job snapshot and safe task summaries |
| `GET` | `/api/import/jobs/{job_id}/events` | `text/event-stream` of persisted events |
| `POST` | `/api/import/jobs/{job_id}/cancel` | Idempotent cancellation snapshot |
| `POST` | `/api/import/jobs/{job_id}/retry-failed` | Idempotent retry request snapshot |

Create uses the existing URL chapter-selection shape. The server canonicalizes
the book and chapter URLs, rejects unsupported/cross-book/duplicate chapters,
and applies `IMPORT_JOB_MAX_CHAPTERS` (default 200). Owner identity is never
accepted from request JSON.

Typed failures use FastAPI's `detail` envelope:

```json
{
  "detail": {
    "code": "job_not_found",
    "retryable": false,
    "message": "Import job not found"
  }
}
```

## Execution and source-of-truth rules

- SQLite `import_jobs`, `chapter_tasks`, and `import_job_events` remain the
  scheduling and reconciliation source of truth.
- FastAPI `BackgroundTasks` only triggers `ImportJobService.run_job`; it does
  not own state and a disconnected HTTP/SSE client does not cancel the job.
- `SourceImportTaskPipeline` keeps extracted chapter text in memory between
  FETCHING/PARSING/VALIDATING and the serialized IMPORTING stage. Only hashes,
  lengths, methods, timings, identifiers, and safe errors are persisted.
- The compatibility route `/api/import/url/fetch` now creates and runs the
  same durable job synchronously, then renders the existing
  `URLFetchResponse` shape.
- The GET snapshot must be fetched after reconnect or a mutation response;
  SSE is an ordered notification stream, not a replacement state store.

## SSE wire format

The persisted `ImportJobEvent.sequence` is the SSE `id`:

```text
id: 7
event: import_job_event
data: {"sequence":7,"job_id":"...","task_id":12,"type":"task_transitioned","data":{"status":"running","stage":"fetching"},"created_at":"..."}

```

- Reconnect cursor: `Last-Event-ID` header or `?cursor=<sequence>`; when both
  are present the larger cursor wins.
- Events are emitted in ascending sequence order and only after the cursor.
- `: keepalive` comments are sent while a job remains non-terminal.
- The stream closes after all persisted events for a terminal job are sent.
- Event payload sanitization remains enforced by
  `sanitize_import_job_payload`; HTML, content, cookies, tokens, secrets, and
  authorization material are not event fields.

## Frontend transport (no UI changes)

`ApiClient` now provides create/get/cancel/retry methods and
`openImportJobEventStream`. The stream uses `fetch`, bearer headers,
`ReadableStream`, and an internal `AbortController`; its handle exposes
`abort()` and `done`. Typed backend errors are preserved on `ApiError.code`
and `ApiError.retryable` without parsing human-readable messages.

## Verification coverage

- Create/get/cancel/retry and idempotency.
- Owner isolation on snapshot, SSE, cancel, and retry.
- URL policy and chapter quota.
- Persisted SSE order, reconnect by query/header, keepalive, disconnect, and
  terminal completion.
- Legacy `/api/import/url/fetch` behavior through the durable engine.
- Authenticated fetch streaming, split SSE chunks, cursor, and abort.
- Existing import job repository/worker and URL import regressions.

Verified results for this milestone:

- Targeted backend: `43 passed, 1 warning in 103.58s`.
- API client: `40 passed in 44.63s`.
- Full backend: `927 passed, 2 warnings in 1115.04s (0:18:35)`.
- Backend compile/lint, frontend typecheck, production build, and
  `git diff --check` passed. The production build retains the pre-existing
  unresolved `sidebar-scenery.png` asset warning.

## Remaining boundary

P09 intentionally does not introduce an autonomous database polling scheduler.
An accepted/queued job is durable, and the request schedules an immediate
in-process run; a future operational milestone may add an independent process
launcher without changing this API contract.
