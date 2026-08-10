# WS1 Browser Execution Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dedicated import worker the only production executor of browser-capable source preview and chapter-import work while preserving the current HTTP response contracts.

**Architecture:** Extend the existing durable SQLite import-job engine with a typed operation/result envelope. The API validates, enqueues, waits, reads, and maps results; the worker claims leases, performs direct HTTP/browser fallback, and atomically publishes a bounded terminal result. Legacy URL routes become compatibility adapters over the same queue, and the API image loses Chromium.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, raw `sqlite3`, pytest/httpx, Bash, Docker/Compose, GitHub Actions, React/Vite compatibility tests.

## Global Constraints

- Work only from branch `codex/ws1-browser-execution-isolation`, based on `ccb92fb583d523547e16afea3170bdfd2058f870`.
- Preserve the public `SourcePreviewResponse`, `JobResponse`, `ImportJobAcceptedResponse`, and `URLFetchResponse` shapes.
- Keep migrations additive, idempotent, and backward compatible. Do not touch an operator database.
- Never persist raw HTML, chapter text, cookies, authorization data, provider credentials, secret paths, or arbitrary environment values in the job/result envelope.
- Never call `ImportJobService.run_job`, `_run_import_job_until_idle`, `PipelineService.preview_source_url`, or a browser helper from an API request/background task.
- Preserve `validate_public_http_url`, redirect validation, source allowlisting, CAPTCHA/challenge semantics, and current retry rules.
- Use temporary databases and isolated Docker project/container/image names. Do not start, restart, or inspect the production Compose project.
- Do not push, merge, deploy, change DNS/Cloudflare/firewall state, or mutate production data in this plan.
- Run the smallest RED test first, implement only the behavior that makes it GREEN, then run the task-level regression group before committing.

## Planned Interface Map

The following interfaces are the intended stable seams. Keep these names and directions unless a failing test proves a narrower signature is necessary.

```python
# app/import_contracts.py
class ImportOperationKind(str, Enum):
    PREVIEW = "preview"
    IMPORT_CHAPTERS = "import_chapters"

class BrowserResultState(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"

class PreviewChapterResult(BaseModel):
    chapter_number: int
    title: str
    url: str

class PreviewPolicyResult(BaseModel):
    source_id: str = ""
    label: str = ""
    delay_seconds: int = 0
    max_concurrency: int = 1
    retry_limit: int = 0

class PreviewBrowserPayload(BaseModel):
    adapter_id: str
    adapter_label: str
    adapter_version: str = ""
    parser_method: str = ""
    source: str
    source_url: str
    title: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    chapters: list[PreviewChapterResult] = Field(default_factory=list)
    policy: PreviewPolicyResult | None = None
    bypass_used: bool = False
    bypass_method: str = ""
    fetch_method: str = ""
    fetch_status_code: int | None = None
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0
    fetch_bytes_received: int = 0
    fetch_final_url: str = ""
    fetch_cookies_refreshed: bool = False
    fetch_cache_hit: bool = False

class BrowserTaskResult(BaseModel):
    schema_version: Literal[1] = 1
    correlation_id: str
    state: BrowserResultState
    payload: PreviewBrowserPayload | None = None
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    http_status: int | None = None

encode_browser_result(result: BrowserTaskResult) -> str
decode_browser_result(value: str) -> BrowserTaskResult | None
```

```python
# app/database/import_jobs.py
class BrowserResultPublicationRejected(RuntimeError):
    code: str

class ImportJobRepository:
    def publish_browser_result(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        task_id: int,
        lease_token: str,
        lease_owner: str,
        expected_job_version: int,
        expected_task_version: int,
        result: BrowserTaskResult,
        now: datetime | None = None,
    ) -> ImportJob

    def expire_browser_job(
        self,
        job_id: str,
        owner_user_id: str,
        *,
        error_code: str = "browser_task_timed_out",
        now: datetime | None = None,
    ) -> ImportJob
```

```python
# app/mobile_api/services/import_job_wait_service.py
class ImportJobWaitError(RuntimeError):
    code: Literal["worker_unavailable", "browser_task_timed_out", "client_disconnected"]

async def wait_for_terminal_import_job(
    service: ImportJobService,
    *,
    job_id: str,
    owner_user_id: str,
    request: Request,
    timeout_seconds: float,
    poll_seconds: float,
) -> ImportJob
```

Preview payload limits are part of the contract: at most 5,000 chapters, 2,000 UTF-8 characters per scalar string, and 1 MiB for the final canonical JSON envelope. All Pydantic models use `ConfigDict(extra="forbid")`; oversized or unknown fields fail validation rather than being silently persisted.

---

### Task 1: Add the typed durable operation and result envelope

**Files:**

- Create: `app/import_contracts.py`
- Modify: `app/database/schema.py`
- Modify: `app/database/db.py`
- Modify: `app/database/import_jobs.py`
- Create: `tests/test_browser_task_contract.py`
- Modify: `tests/test_import_job_repository.py`

- [ ] **Step 1: Write RED contract tests for the allowlisted result models**

Add `test_preview_result_round_trip_preserves_only_the_public_contract`,
`test_preview_result_rejects_unknown_sensitive_and_oversized_fields`, and
`test_browser_terminal_state_requires_payload_only_for_completed_preview`.

The successful fixture must include every current `SourcePreviewResponse` fetch field. The rejection cases must cover `html`, `content`, `cookie`, `authorization`, a 2,001-character title, 5,001 chapters, and a serialized envelope larger than 1 MiB.

- [ ] **Step 2: Run the contract tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_task_contract.py
```

Expected: collection/import failure because `app.import_contracts` does not exist.

- [ ] **Step 3: Implement the typed models and canonical serializer**

Create the enums and models from the interface map. `PreviewBrowserPayload` must enumerate the current preview response fields explicitly, excluding API-owned managed-source fields. `encode_browser_result` must serialize with sorted keys and compact separators, measure UTF-8 bytes, and raise `ValueError("browser result exceeds 1048576 bytes")` above the limit. `decode_browser_result("")` returns `None`; invalid stored JSON raises `ValueError` without echoing input.

State validation rules:

- `COMPLETED` requires a preview payload and empty error fields;
- `FAILED` and `BLOCKED` require a stable non-empty `error_code`, allow a bounded safe message, and forbid payload;
- `CANCELLED` and `TIMED_OUT` require a stable error code and forbid payload;
- every result requires the durable job's bounded correlation ID;
- `error_code` is limited to `[a-z0-9_]{1,96}`, `error_message` to 2,000 characters, and `http_status` to 400–599 when present.

- [ ] **Step 4: Write RED schema/migration tests**

Extend `test_init_db_migrates_legacy_database_with_import_job_tables` and add
`test_new_import_jobs_default_to_chapter_operation_with_empty_result` and
`test_preview_job_round_trips_deadline_correlation_and_result_fields`.

Assert these six additive columns exist: `operation_kind`, `deadline_at`, `correlation_id`, `result_state`, `result_snapshot_json`, `result_published_at`. Assert the legacy row becomes `import_chapters` and retains all pre-existing data.

- [ ] **Step 5: Run repository tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_import_job_repository.py -k 'legacy_database or operation or result_fields'
```

Expected: assertions fail because the columns and `ImportJob` attributes do not exist.

- [ ] **Step 6: Add the additive schema and repository mapping**

Add the columns to canonical `CREATE TABLE import_jobs` and `_ensure_import_job_tables`:

```sql
operation_kind TEXT NOT NULL DEFAULT 'import_chapters',
deadline_at TEXT NOT NULL DEFAULT '',
correlation_id TEXT NOT NULL DEFAULT '',
result_state TEXT NOT NULL DEFAULT '',
result_snapshot_json TEXT NOT NULL DEFAULT '',
result_published_at TEXT NOT NULL DEFAULT ''
```

Extend `ImportJob` and `_job_from_row` with `operation_kind: ImportOperationKind`, `deadline_at: str`, `correlation_id: str`, `result_state: BrowserResultState | None`, `result_snapshot: BrowserTaskResult | None`, and `result_published_at: str`. Decode the snapshot through `decode_browser_result` and reject a non-empty `result_state` that disagrees with the decoded envelope. Extend `ImportJobRepository.create_job` with keyword-only `operation_kind`, `deadline_at`, and `correlation_id`; validate the enum, truncate correlation IDs to 128 characters, and leave result fields empty. Existing callers must compile unchanged because the operation default is `IMPORT_CHAPTERS`.

- [ ] **Step 7: Run GREEN and task regression tests**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_task_contract.py tests/test_import_job_repository.py
.venv/bin/python -m compileall -q app tests
git diff --check
```

Expected: all pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add app/import_contracts.py app/database/schema.py app/database/db.py app/database/import_jobs.py tests/test_browser_task_contract.py tests/test_import_job_repository.py
git commit -m "feat: add durable browser task contract"
```

---

### Task 2: Make browser-result publication atomic and cancellation-safe

**Files:**

- Modify: `app/database/import_jobs.py`
- Modify: `tests/test_import_job_repository.py`
- Create: `tests/test_browser_result_publication.py`

- [ ] **Step 1: Write RED transaction tests**

Create helpers that make one `preview` job, one task, transition the job to `running`, and claim the task. Add these exact tests:

- `test_active_lease_atomically_publishes_preview_result_and_terminal_events`;
- `test_stale_lease_or_owner_cannot_publish_browser_result`;
- `test_stale_job_or_task_version_cannot_publish_browser_result`;
- `test_cancel_requested_wins_over_late_completed_result`;
- `test_expired_deadline_cannot_publish_completed_result`;
- `test_duplicate_identical_publication_is_idempotent_but_different_result_cannot_overwrite`;
- `test_two_workers_can_publish_only_one_terminal_result`;
- `test_expire_browser_job_records_timeout_and_invalidates_running_lease`.

The concurrent test must use two repository instances and a `ThreadPoolExecutor`. Assert exactly one canonical snapshot, one `browser_result_published` event, cleared lease fields, terminal task/job states, and monotonically increasing events.

- [ ] **Step 2: Run the publication tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_result_publication.py
```

Expected: failures because publication methods and exception type do not exist.

- [ ] **Step 3: Implement one compare-and-set publication transaction**

Implement `BrowserResultPublicationRejected` with safe codes `stale_lease`, `cancelled`, `deadline_exceeded`, `already_published`, and `wrong_operation`.

`publish_browser_result` must use `BEGIN IMMEDIATE`, load the owner-scoped job and task, and reject before writing unless all are true:

- `operation_kind == preview`;
- task belongs to the job and is `running`;
- `lease_token` and `lease_owner` both match;
- current job/task versions match `expected_job_version` and `expected_task_version`;
- job is `running`, no cancellation is requested, and the deadline is in the future;
- the result correlation ID matches the job correlation ID;
- the result slot is empty.

Before enforcing the active-lease checks, return the current row without a new event when the slot already contains the byte-identical canonical result. Reject any different existing result as `already_published`.

Map result to existing terminal rows in the same transaction:

| Browser state | Task status/stage | Job status |
| --- | --- | --- |
| `COMPLETED` | `succeeded/succeeded` | `succeeded` |
| `BLOCKED` | `user_verification_required/user_verification_required` | `failed` |
| `FAILED` | `failed/failed` | `failed` |
| `CANCELLED` | `cancelled/cancelled` | `cancelled` |
| `TIMED_OUT` | `failed/failed` | `failed` |

Use the versions read inside the transaction in both compare-and-set `UPDATE` statements with `WHERE version = ?`, clear the lease fields, set `finished_at`, set result fields, and append bounded `browser_result_published`, `task_transitioned`, and `job_transitioned` events before commit. Events contain state/code/correlation only, never payload.

If an identical result is already present, return the current row without adding an event. A different result raises `already_published`.

- [ ] **Step 4: Implement timeout and cancellation terminalization**

`expire_browser_job` must atomically:

- no-op if a terminal result already exists;
- set `cancel_requested_at` if empty;
- set `TIMED_OUT` with a safe error envelope;
- terminalize queued or running preview tasks as `failed/failed` with `browser_task_timed_out` and clear leases;
- set the existing job status to `failed` and append one timeout event.

Update `request_cancel` so a preview job with no result receives a `CANCELLED` result and all preview task leases are invalidated in the same transaction. Preserve the existing gradual cancellation behavior for `import_chapters` jobs.

- [ ] **Step 5: Run GREEN and race regressions**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_result_publication.py tests/test_import_job_repository.py tests/test_import_job_worker.py -k 'publish or lease or cancel or recover or two_worker or legacy_database'
git diff --check
```

Expected: all pass repeatedly; run the concurrent publication test five times.

- [ ] **Step 6: Commit Task 2**

```bash
git add app/database/import_jobs.py tests/test_import_job_repository.py tests/test_browser_result_publication.py
git commit -m "feat: publish browser results atomically"
```

---

### Task 3: Execute preview operations only in the durable worker

**Files:**

- Create: `app/services/browser_preview_task_pipeline.py`
- Create: `app/services/source_task_pipeline.py`
- Modify: `app/services/source_import_task_pipeline.py`
- Modify: `app/services/import_job_service.py`
- Modify: `app/services/import_job_factory.py`
- Modify: `app/import_worker.py`
- Create: `tests/test_browser_preview_worker.py`
- Modify: `tests/test_import_job_worker.py`

- [ ] **Step 1: Write RED worker success/error tests**

Add fake `PipelineService` implementations and these tests:

Add these exact tests:

- `test_worker_claims_preview_and_publishes_typed_completed_result`;
- `test_worker_maps_verification_required_to_blocked_result`;
- `test_worker_maps_safe_source_failure_without_persisting_exception_or_html`;
- `test_cancel_after_preview_execution_before_publish_wins`;
- `test_crash_before_publish_recovers_lease_and_publishes_once`;
- `test_chapter_import_pipeline_behavior_is_unchanged`.

The success test must assert that only the worker-side fake's `preview_source_url` is called. The crash test must use a first repository wrapper that raises `SystemExit` immediately before publication, expire the lease in the temp database, then run a second worker and assert one terminal event/snapshot.

- [ ] **Step 2: Run worker tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_preview_worker.py
```

Expected: import/attribute failures because preview dispatch and result-aware worker finalization do not exist.

- [ ] **Step 3: Add a preview-specific staged pipeline**

Implement `BrowserPreviewTaskPipeline` with an in-memory, lock-protected `dict[int, PreviewBrowserPayload]` and `release_task(task_id)`.

- `FETCHING`: load the job, assert `preview`, call `PipelineService.preview_source_url(job.source_url)`, and validate the returned mapping into `PreviewBrowserPayload`.
- `PARSING`: no external I/O; require that the typed payload exists.
- `VALIDATING`: re-run Pydantic validation and envelope-size validation.
- `IMPORTING`: return `BrowserTaskResult(state=COMPLETED, payload=typed_payload, correlation_id=job.correlation_id)` and release in-memory state after publication.

It must check `cancel_check()` before any call and must not persist the mapping itself.

Implement `SourceTaskPipeline` as a dispatcher that reads `job.operation_kind`: delegate chapter work to the unchanged `SourceImportTaskPipeline` and preview work to `BrowserPreviewTaskPipeline`. Both delegates expose `release_task`.

- [ ] **Step 4: Make `ImportJobService` result-aware**

Change the protocol return type to `TaskImportOutcome | BrowserTaskResult | None`. Add `operation_kind`, `deadline_at`, and `correlation_id` keyword parameters to `create_job` and pass them to the repository.

For preview jobs:

- run the same fetch/parse/validate/import stage sequence under the existing lease renewal and retry loop;
- compare `deadline_at` with current UTC before browser launch and between stages; call `expire_browser_job` rather than entering the pipeline when it is expired;
- publish success through `publish_browser_result`, never through the generic `transition_task` success path;
- map `USER_VERIFICATION_REQUIRED` to `BLOCKED`, other `SourceAdapterError` values to `FAILED`, duration expiry to `TIMED_OUT`, and unexpected exceptions to `FAILED/internal_error` with the fixed message `Browser task failed`;
- if publication rejects with `cancelled` or `deadline_exceeded`, invoke the repository's existing cancellation/expiry reconciliation and do not emit a success metric;
- release pipeline memory in `finally`.

Keep chapter-import branches byte-for-byte behaviorally compatible and continue using their existing transitions and ordered import gate.

- [ ] **Step 5: Wire the dispatcher only through the shared factory**

Update `create_import_job_service` so API and worker repositories share the same policy configuration, but the injected worker pipeline is `SourceTaskPipeline`. Do not add a browser call to the factory. `DurableImportWorker` continues to be the only production caller of `run_job`.

- [ ] **Step 6: Run GREEN and full durable-worker regressions**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q \
  tests/test_browser_preview_worker.py \
  tests/test_import_job_worker.py \
  tests/test_import_job_runtime.py \
  tests/test_import_job_observability.py
.venv/bin/python -m compileall -q app tests
git diff --check
```

Expected: all pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add app/services/browser_preview_task_pipeline.py app/services/source_task_pipeline.py app/services/source_import_task_pipeline.py app/services/import_job_service.py app/services/import_job_factory.py app/import_worker.py tests/test_browser_preview_worker.py tests/test_import_job_worker.py
git commit -m "feat: run source previews in import worker"
```

---

### Task 4: Preserve synchronous preview through enqueue-and-wait

**Files:**

- Create: `app/mobile_api/services/import_job_wait_service.py`
- Modify: `app/mobile_api/config.py`
- Modify: `.env.example`
- Modify: `app/mobile_api/routers/import_routes.py`
- Modify: `tests/test_mobile_api_import_url.py`
- Modify: `tests/test_runtime_readiness.py`
- Create: `tests/test_browser_preview_api_worker_integration.py`

- [ ] **Step 1: Write RED API ownership tests**

Replace direct-pipeline preview fakes with a temporary-database service and add:

Add these exact async tests:

- `test_preview_endpoint_enqueues_worker_job_and_preserves_response_contract`;
- `test_preview_endpoint_never_calls_api_pipeline_preview`;
- `test_preview_endpoint_returns_503_when_worker_missing_or_stale`;
- `test_preview_endpoint_maps_blocked_failed_and_timed_out_results`;
- `test_preview_disconnect_requests_durable_cancellation`;
- `test_preview_result_keeps_managed_source_enrichment_in_api`.

The happy-path test must run `DurableImportWorker.run_once()` in a separate thread/service over the same temp SQLite file. Override only the worker-runtime dependency to report `queue_claim_capable=True`; do not override the route with a direct preview pipeline.

The no-local-call test installs a `PipelineService.preview_source_url` sentinel that raises `AssertionError`; the response must still come from a pre-published worker result.

- [ ] **Step 2: Run API preview tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_mobile_api_import_url.py tests/test_browser_preview_api_worker_integration.py -k 'preview'
```

Expected: direct preview tests fail because the route still calls `pipeline.preview_source_url` in an API thread.

- [ ] **Step 3: Add bounded wait configuration and worker capability dependency**

Add validated settings:

```python
import_preview_wait_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
import_job_sync_wait_timeout_seconds: float = Field(default=3600.0, gt=0, le=7200)
import_job_wait_poll_seconds: float = Field(default=0.10, gt=0, le=2)
```

Document sanitized defaults in `.env.example`.

Add `get_import_worker_runtime()` in the route module, backed by `inspect_worker_runtime` with `data_dir=get_data_dir()`, `db_path=get_db_path()`, `api_identity=get_runtime_identity(component="api")`, `required=True`, and the configured heartbeat maximum age. It exposes only `WorkerRuntimeStatus`; tests can override it without touching files or clocks.

- [ ] **Step 4: Implement the reusable async waiter**

`wait_for_terminal_import_job` must poll `service.get_job` through `asyncio.to_thread`, check `request.is_disconnected()` each iteration, and never call `run_job`.

- terminal job: return it;
- disconnect: `service.request_cancel`, then raise `ImportJobWaitError("client_disconnected")`;
- deadline: call `repository.expire_browser_job` for preview or `service.request_cancel` for chapter imports, then raise `ImportJobWaitError("browser_task_timed_out")`;
- sleep only `poll_seconds`, using `asyncio.sleep`.

- [ ] **Step 5: Replace preview execution with durable enqueue-and-wait**

In `preview_source_url`:

1. authenticate owner with `get_current_user`;
2. validate/canonicalize URL and source policy before creating a job;
3. fail `503` with `{code: worker_unavailable, retryable: true, message: "Import worker is unavailable"}` when the runtime dependency is not claim-capable;
4. create a `preview` job with one task, a UUID correlation ID, and an absolute UTC deadline;
5. enqueue and wait with the helper;
6. decode the typed result and map states to the approved HTTP contract;
7. convert chapters to plain dictionaries, set `chapter_count=len(chapters)`, add managed-source fields in the API, and return `SourcePreviewResponse`.

HTTP mapping:

| Result/wait condition | HTTP/code |
| --- | --- |
| `COMPLETED` | 200, unchanged body |
| `BLOCKED` | existing source status/code and retryability |
| `FAILED` | 502 `browser_task_failed` unless the stored stable source code has a narrower existing status |
| `TIMED_OUT` | 504 `browser_task_timed_out` |
| worker missing/stale/release mismatch | 503 `worker_unavailable` |

Never log the submitted query string or persisted payload.

- [ ] **Step 6: Run GREEN and readiness regressions**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q \
  tests/test_mobile_api_import_url.py \
  tests/test_browser_preview_api_worker_integration.py \
  tests/test_runtime_readiness.py
git diff --check
```

Expected: all pass and the old thread-offload assertion is removed/replaced by a durable-worker assertion.

- [ ] **Step 7: Commit Task 4**

```bash
git add app/mobile_api/services/import_job_wait_service.py app/mobile_api/config.py .env.example app/mobile_api/routers/import_routes.py tests/test_mobile_api_import_url.py tests/test_runtime_readiness.py tests/test_browser_preview_api_worker_integration.py
git commit -m "feat: proxy source previews through durable worker"
```

---

### Task 5: Migrate all URL compatibility routes off API execution

**Files:**

- Modify: `app/mobile_api/routers/import_routes.py`
- Modify: `app/mobile_api/config.py`
- Modify: `app/mobile_api/routers/health.py`
- Modify: `app/mobile_api/services/operational_metrics_service.py`
- Modify: `compose.yaml`
- Modify: `tests/test_mobile_api_import_jobs.py`
- Modify: `tests/test_mobile_api_import_url.py`
- Modify: `tests/test_operational_metrics.py`
- Modify: `tests/test_runtime_readiness.py`
- Modify: `tests/test_deployment_hardening.py`

- [ ] **Step 1: Write RED route-ownership tests**

Add or replace tests with:

Add these exact tests:

- `test_jobs_endpoint_always_leaves_execution_to_worker`;
- `test_retry_failed_endpoint_never_schedules_api_background_runner`;
- `test_legacy_url_endpoint_returns_durable_job_without_jobservice`;
- `test_legacy_url_fetch_waits_for_external_worker_without_draining`;
- `test_legacy_url_fetch_timeout_cancels_job_and_returns_safe_504`;
- `test_import_routes_have_no_api_job_drain_helper`.

Use sentinels that raise if `JobService.start_import_url_job`, `ImportJobService.run_job`, or `BackgroundTasks.add_task` receives the durable runner. Preserve current request validation, verified-managed-source checks, audit metadata, and response fields.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_mobile_api_import_jobs.py tests/test_mobile_api_import_url.py -k 'jobs_endpoint or retry_failed or legacy_url or no_api_job_drain'
```

Expected: failures because the three local execution paths still exist.

- [ ] **Step 3: Convert `/api/import/url` to the durable service**

Keep verified Managed Source validation and `_validated_url_import_payload`. Convert validated chapters to the same canonical task dictionaries used by `/api/import/jobs`, call `ImportJobService.create_job` with `operation_kind=ImportOperationKind.IMPORT_CHAPTERS` plus the validated owner/source/source URL/tasks/config snapshot, enqueue, and return `JobResponse(job_id=job.id, status="pending", message="URL import job started")`. Add owner authentication. Remove the `JobService` dependency and do not schedule a task.

- [ ] **Step 4: Remove all API draining branches**

- `/api/import/jobs`: remove `BackgroundTasks`; always create/enqueue and return 202.
- `/api/import/jobs/{id}/retry-failed`: reset durable tasks only; the worker will claim them.
- `/api/import/url/fetch`: create/enqueue, call `wait_for_terminal_import_job`, and map stored task metadata to the unchanged `URLFetchResponse`.
- Delete `_run_import_job_until_idle`, `get_job_service`, and unused imports.

On synchronous fetch timeout, request cancellation and return `504 import_job_timed_out`. Worker-unavailable is `503 worker_unavailable`. Do not return partial content-bearing data.

- [ ] **Step 5: Remove the in-process execution mode**

Delete `import_job_run_in_api` from `MobileSettings` and remove `IMPORT_JOB_RUN_IN_API` from Compose. Make readiness and operational metrics call `inspect_worker_runtime` with their existing data/database/identity/heartbeat arguments and `required=True` unconditionally. Update affected tests to expect the worker to be required in every runtime mode.

This is an intentional operational change but not an HTTP shape change: local startup will gain a worker in Task 6.

- [ ] **Step 6: Run GREEN route/readiness/metrics regressions**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q \
  tests/test_mobile_api_import_jobs.py \
  tests/test_mobile_api_import_url.py \
  tests/test_operational_metrics.py \
  tests/test_runtime_readiness.py \
  tests/test_deployment_hardening.py
rg -n 'IMPORT_JOB_RUN_IN_API|import_job_run_in_api|_run_import_job_until_idle|start_import_url_job' app compose.yaml tests
git diff --check
```

Expected: pytest passes; `rg` returns no production matches (test names may mention the removed behavior only if asserting absence).

- [ ] **Step 7: Commit Task 5**

```bash
git add app/mobile_api/routers/import_routes.py app/mobile_api/config.py app/mobile_api/routers/health.py app/mobile_api/services/operational_metrics_service.py compose.yaml tests/test_mobile_api_import_jobs.py tests/test_mobile_api_import_url.py tests/test_operational_metrics.py tests/test_runtime_readiness.py tests/test_deployment_hardening.py
git commit -m "refactor: delegate URL imports to durable worker"
```

---

### Task 6: Run and manage the dedicated worker in local workflows

**Files:**

- Modify: `scripts/start-local.sh`
- Modify: `scripts/start-cloudflare.sh`
- Modify: `scripts/stop-local.sh`
- Modify: `scripts/status-local.sh`
- Modify: `docs/local-development.md`
- Modify: `tests/test_environment_scripts.py`

- [ ] **Step 1: Write RED script-contract tests**

Add tests that parse the scripts and assert:

Add `test_local_start_launches_worker_before_waiting_for_api_readiness`,
`test_cloudflare_start_launches_the_same_worker_process`,
`test_local_stop_and_status_manage_import_worker_pid`, and
`test_local_docs_describe_api_worker_and_web_as_separate_processes`.

Required artifacts are `import-worker.pid` and `import-worker.log` under the existing runtime directory. Tests must also assert no script exports `IMPORT_JOB_RUN_IN_API=1`.

- [ ] **Step 2: Run script tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_environment_scripts.py -k 'worker or local_start or cloudflare_start'
```

Expected: failures because only API/Web PIDs exist.

- [ ] **Step 3: Start the worker as a separate process**

In both start scripts:

- resolve the same Python interpreter and `DATA_DIR` as the API;
- start `python -m app.import_worker` with `start_detached`/`setsid` before starting the API;
- write `import-worker.pid`, append to `import-worker.log`, and preserve restrictive umask behavior;
- treat a live PID as idempotently running;
- wait for the heartbeat file to become fresh for at most `IMPORT_WORKER_START_TIMEOUT` (default 45 seconds) without printing its contents.

The API readiness wait then proves the worker release/heartbeat matches.

- [ ] **Step 4: Add stop/status ownership**

`stop-local.sh` stops Web, API, then worker using the existing explicit PID-file helper. `status-local.sh` reports the worker PID and runs `python -m app.import_worker --healthcheck`; it must not display heartbeat JSON or filesystem secrets.

Update local docs with start, status, stop, log locations, and the statement that source preview/import now requires the separate worker.

- [ ] **Step 5: Run GREEN shell and environment checks**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_environment_scripts.py
for script in scripts/*.sh; do bash -n "$script"; done
scripts/check-environment.sh
git diff --check
```

Expected: all pass. Do not actually start the user's local services as part of this task.

- [ ] **Step 6: Commit Task 6**

```bash
git add scripts/start-local.sh scripts/start-cloudflare.sh scripts/stop-local.sh scripts/status-local.sh docs/local-development.md tests/test_environment_scripts.py
git commit -m "ops: start import worker in local workflows"
```

---

### Task 7: Remove Chromium from API image and prove the container boundary

**Files:**

- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Create: `scripts/smoke-browser-execution-isolation.sh`
- Create: `tests/test_browser_execution_isolation_images.py`
- Modify: `tests/test_deployment_hardening.py`
- Modify: `.github/workflows/ci.yml`

> This task changes CI. Selecting this implementation plan for execution is the explicit approval required by repository policy for the scoped Docker-job update below.

- [ ] **Step 1: Write RED source and smoke-script contract tests**

Add tests:

Add `test_api_docker_target_has_no_browser_install_or_browser_path`,
`test_worker_docker_target_is_the_only_chromium_owner`,
`test_compose_keeps_worker_off_provider_secret_volume_and_api_dns`,
`test_isolation_smoke_uses_disposable_names_and_cleanup_trap`, and
`test_ci_builds_both_targets_and_runs_isolation_smoke`.

Parse target-specific Dockerfile sections, not just whole-file substrings. The API section must have zero `playwright install`, `chromium`, or `PLAYWRIGHT_BROWSERS_PATH` references.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_execution_isolation_images.py tests/test_deployment_hardening.py
```

Expected: API-target assertion fails because it still installs Chromium; smoke script/CI assertions fail because they do not exist.

- [ ] **Step 3: Remove API browser capability**

Delete `PLAYWRIGHT_BROWSERS_PATH`, `playwright install --with-deps chromium`, and `/ms-playwright` ownership from the `api` target. Retain them only in `import-worker`. Keep API web assets, ffmpeg, non-root user, healthcheck, read-only filesystem, and command unchanged.

In Compose, retain separate `api-egress` and `browser-egress` networks and the API-only `provider-secrets` overlay. Add no provider-key/API-key environment keys to the worker.

- [ ] **Step 4: Implement the isolated executable-level smoke**

`scripts/smoke-browser-execution-isolation.sh` must:

- require Docker and `docker compose`, derive a unique prefix from PID plus random hex, and install an EXIT trap that removes only exact containers/networks/volumes/temp paths bearing that prefix;
- build explicit `--target api` and `--target import-worker` tags;
- run the API image with `command -v chromium`, `command -v chromium-browser`, and the Playwright executable path check, failing if any executable browser exists;
- run the worker image as user `novel` and launch Playwright Chromium against `page.set_content('<h1>worker-browser-ok</h1>')`, assert the text, then close it;
- render Compose with dummy `.invalid` public settings and inspect only service names, target images, networks, mounts, and environment key names;
- assert worker mounts do not include the named provider-secret volume and worker environment keys contain none of `REMOTE_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `MOBILE_API_SECRET`, or `MOBILE_API_ADMIN_PASSWORD`;
- print image byte sizes from `docker image inspect .Size` for API and worker without printing environment values.

The script must not contact third-party sources, bind a public port, run the production project name, or read `.env`.

- [ ] **Step 5: Update the Docker CI job**

Build both named targets. Run the isolation smoke, then run the existing API readiness/frontend smoke against the explicit API image. Keep `if: always()` exact-container cleanup. Do not alter Python/frontend gates.

- [ ] **Step 6: Run GREEN static checks and Docker smoke when available**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_browser_execution_isolation_images.py tests/test_deployment_hardening.py tests/test_environment_scripts.py
bash -n scripts/smoke-browser-execution-isolation.sh
scripts/smoke-browser-execution-isolation.sh
git diff --check
```

Expected: all pass. If Docker is unavailable, record the exact daemon/tool error; do not mark the executable smoke as passed.

- [ ] **Step 7: Commit Task 7**

```bash
git add Dockerfile compose.yaml scripts/smoke-browser-execution-isolation.sh tests/test_browser_execution_isolation_images.py tests/test_deployment_hardening.py .github/workflows/ci.yml
git commit -m "build: isolate Chromium to import worker"
```

---

### Task 8: Certify security, recovery, compatibility, and full gates

**Files:**

- Create: `tests/test_browser_execution_isolation_security.py`
- Modify: `tests/test_source_adapters.py`
- Modify: `tests/test_browser_preview_api_worker_integration.py`
- Create: `docs/upgrade/WS1_BROWSER_EXECUTION_ISOLATION.md`

- [ ] **Step 1: Write the final RED invariant tests**

Add tests that exercise the full seams, not implementation text alone:

Add these exact tests:

- `test_private_ipv4_ipv6_cgnat_and_link_local_targets_never_reach_browser_fallback`;
- `test_public_to_private_redirect_is_rejected_before_browser_fallback`;
- `test_blocked_direct_fetch_invokes_browser_fallback_exactly_once_in_worker`;
- `test_stale_worker_result_cannot_overwrite_newer_preview_request`;
- `test_provider_secret_names_and_values_never_enter_worker_job_or_result`;
- `test_api_worker_preview_contract_matches_legacy_preview_fixture`.

Use fake DNS resolvers, local HTML fixtures, and monkeypatched fallback functions only. Do not resolve or request real novel sites. The provider-secret test uses synthetic canary values and scans only the temporary database/events/result JSON.

- [ ] **Step 2: Run invariant tests and confirm any remaining RED gaps**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q \
  tests/test_browser_execution_isolation_security.py \
  tests/test_source_adapters.py \
  tests/test_browser_preview_api_worker_integration.py
```

Expected before final fixes: any missing guard fails with a narrow assertion. If all are already GREEN because Tasks 1–7 completed the behavior, record that this is characterization coverage and make no production-code change.

- [ ] **Step 3: Make only the minimal invariant fixes**

Allowed fixes are limited to:

- validating every redirect before `_call_stealth_fallback`;
- rejecting a result whose correlation ID does not match the durable job;
- applying typed result validation before persistence and after read;
- removing secret-bearing keys from durable config/events.

Do not redesign adapters or expand challenge bypass behavior.

- [ ] **Step 4: Write the WS1 completion note**

Document in `docs/upgrade/WS1_BROWSER_EXECUTION_ISOLATION.md`:

- final request flows and error codes;
- schema additions and rollback compatibility;
- local API/worker commands;
- image ownership and provider-secret boundary;
- tests run, image sizes, unavailable gates, and remaining operational risks;
- explicit statement that no production deployment or database migration was executed.

- [ ] **Step 5: Run focused backend certification**

Run:

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
.venv/bin/python -m pytest -q \
  tests/test_browser_task_contract.py \
  tests/test_browser_result_publication.py \
  tests/test_browser_preview_worker.py \
  tests/test_browser_preview_api_worker_integration.py \
  tests/test_browser_execution_isolation_security.py \
  tests/test_import_job_repository.py \
  tests/test_import_job_worker.py \
  tests/test_mobile_api_import_jobs.py \
  tests/test_mobile_api_import_url.py \
  tests/test_source_adapters.py \
  tests/test_runtime_readiness.py \
  tests/test_operational_metrics.py \
  tests/test_deployment_hardening.py \
  tests/test_browser_execution_isolation_images.py
```

Expected: all pass.

- [ ] **Step 6: Run repository-wide verification**

Run:

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
.venv/bin/python -m compileall -q app scripts tests
for script in scripts/*.sh; do bash -n "$script"; done
scripts/lint.sh
.venv/bin/python -m pytest -q -s
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run test:e2e -- --project=chromium
scripts/verify.sh --with-e2e
git diff --check
```

Expected: all pass. Record exact counts, durations, warnings, and any environmental limitation. A skipped/unavailable Docker or E2E gate is not a pass.

- [ ] **Step 7: Run ownership and secret scans**

Run:

```bash
rg -n 'preview_source_url\(|fetch_source_chapter\(|fetch_with_stealth|_run_import_job_until_idle|IMPORT_JOB_RUN_IN_API|import_job_run_in_api' app/mobile_api app/services scripts compose.yaml Dockerfile
rg -n 'REMOTE_API_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|OPENROUTER_API_KEY|OPENAI_API_KEY|MOBILE_API_SECRET|MOBILE_API_ADMIN_PASSWORD' compose.yaml
git status --short
```

Manually classify each remaining match. Acceptable matches are worker pipeline construction, adapter implementation, API-only Compose keys, and test/operator browser tooling. There must be no API route/background execution match and no worker secret key.

- [ ] **Step 8: Commit Task 8**

```bash
git add tests/test_browser_execution_isolation_security.py tests/test_source_adapters.py tests/test_browser_preview_api_worker_integration.py docs/upgrade/WS1_BROWSER_EXECUTION_ISOLATION.md
git commit -m "test: certify browser execution isolation"
```

- [ ] **Step 9: Final branch review**

Run:

```bash
git log --oneline ccb92fb583d523547e16afea3170bdfd2058f870..HEAD
git diff --stat ccb92fb583d523547e16afea3170bdfd2058f870..HEAD
git diff --check ccb92fb583d523547e16afea3170bdfd2058f870..HEAD
git status --short
```

Expected: eight focused implementation commits after the design/plan commits, no unrelated files, clean worktree, and no secret/generated artifact.

## Spec Coverage Checklist

- Durable preview operation and additive migration: Tasks 1–2.
- Typed bounded result with no HTML/content/secrets: Tasks 1, 2, 8.
- Atomic lease/version/cancel/deadline publication: Task 2.
- Worker-owned preview/browser fallback: Task 3.
- Compatible synchronous preview response: Task 4.
- Legacy URL import/fetch worker delegation: Task 5.
- Required worker readiness and local startup: Tasks 4–6.
- API image without Chromium; worker with launchable Chromium: Task 7.
- Private-network, redirect, challenge, stale-result, and secret boundaries: Task 8.
- Full backend/frontend/E2E/container evidence and rollback note: Tasks 7–8.
