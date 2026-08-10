# WS1 Browser Execution Isolation Design

## Goal

Make the dedicated import worker the only production owner of Chromium-based
source access. The public API must validate, enqueue, observe, and translate
durable results, but it must never launch a browser or drain browser-capable
source work locally.

The change preserves the current synchronous `SourcePreview` response used by
the frontend while reducing the API image size and browser-related attack
surface.

## Baseline and confirmed gap

This design targets `main` at
`ccb92fb583d523547e16afea3170bdfd2058f870`.

The repository already has most of the durable execution foundation:

- `ImportJobRepository` persists jobs, task leases, cancellation, retries, and
  ordered events in SQLite;
- `DurableImportWorker` owns production import-job execution and browser
  shutdown;
- `SourceImportTaskPipeline` keeps fetched chapter content in process and
  persists only bounded metadata;
- API and worker Compose services use separate networks, and only the API sees
  the provider-secret volume.

The remaining ownership contradiction is concrete:

| Entry point | Current owner | Browser possible | Durable | Desired owner |
| --- | --- | ---: | ---: | --- |
| `POST /api/import/url/preview` | API `PipelineService` thread | yes | no | worker |
| `POST /api/import/url` | API legacy `JobService` background task | yes | partial legacy job only | worker |
| `POST /api/import/url/fetch` | durable service drained synchronously by API | yes | yes | worker |
| `POST /api/import/jobs` | worker in production; API in local compatibility mode | yes | yes | worker |
| managed-source and catalog health checks | API direct HTTP | no | test record only | API direct HTTP |
| browser/session utilities | process importing and calling them | yes | no | worker only in production |
| Python Reader screenshot smoke | operator/test script | yes | no | test-only, unchanged |

The Dockerfile documents that Chromium belongs to the worker, but installs it
again in the final API target to support the three API execution paths above.

## Scope

Included:

- durable source preview execution;
- migration of legacy URL import/fetch routes to worker-only execution;
- a typed, bounded browser-task result contract;
- atomic result publication tied to the active lease and cancellation state;
- worker timeout, cancellation, restart, and stale-result behavior;
- private-network and redirect policy preservation;
- local development startup of the dedicated worker;
- API and worker Docker targets, Compose ownership, and relevant tests.

Excluded:

- source-adapter redesign;
- new source providers or parsers;
- challenge or CAPTCHA behavior changes;
- live challenge-bypass testing;
- provider API changes;
- production ingress, DNS, Cloudflare, firewall, or deployment changes;
- unrelated import UI redesign;
- replacing SQLite or the existing job engine.

## Approaches considered

### Extend the durable import-job engine — selected

Add explicit operation and result contracts to the existing job repository.
This reuses proven lease, retry, cancellation, recovery, quota, and event
semantics and keeps one source-work scheduler.

### Add a second browser-job queue

This would give previews a clean standalone model, but it would duplicate the
same state machine and create two recovery and observability paths. The added
surface is not justified.

### Call the worker over HTTP or RPC

This could reduce preview latency, but it would make worker availability part
of the API request path and weaken restart durability. It also adds a second
service-authentication boundary without removing the SQLite queue.

## Durable operation contract

Extend durable import jobs with an operation kind:

- `preview`;
- `import_chapters`.

The default for existing rows is `import_chapters`, so the migration remains
backward compatible. A preview job contains exactly one task whose canonical
URL is the validated source URL. Chapter import jobs retain their existing
task layout.

The `import_jobs` table gains bounded, additive fields for
`operation_kind`, `deadline_at`, `correlation_id`, `result_state`,
`result_snapshot_json`, and `result_published_at`. Existing rows are backfilled
with `operation_kind=import_chapters` and an empty result. Initialization uses
the repository's existing idempotent column-existence checks. No new table,
queue, or content-bearing artifact is introduced.

The persisted request envelope contains only:

- schema version;
- operation kind;
- normalized source URL;
- source adapter ID;
- job and task IDs;
- bounded deadline;
- correlation/request ID;
- parser expectation and bounded option flags.

It must not contain raw HTML, chapter content, cookies, provider credentials,
refresh tokens, arbitrary environment values, or unbounded caller data.

### Browser terminal result

Browser-capable operations publish one of these typed terminal states:

- `COMPLETED`;
- `FAILED`;
- `BLOCKED`;
- `CANCELLED`;
- `TIMED_OUT`.

This browser outcome is stored in a versioned result envelope rather than
changing the existing public import-job status vocabulary. Chapter jobs keep
their existing `queued`, `running`, `succeeded`, `partially_succeeded`,
`failed`, and `cancelled` values.

The preview result uses an explicit allowlist and size limit. Allowed values
include normalized source metadata, chapter titles and URLs, adapter/version,
fetch method, status code, attempt count, elapsed time, byte count, final URL,
and boolean flags required by the existing response. No generic mapping is
persisted without typed validation.

## Architecture

The API remains the authenticated command and query boundary. It validates
URLs and ownership, creates durable work, and observes SQLite state. It never
imports or calls the browser runtime for source operations.

The import worker remains the sole executor. It claims one logical task using
the existing lease token, runs direct HTTP and browser fallback inside the
worker process, parses the response, and publishes an allowlisted result.

Repository publication is a compare-and-set transaction that verifies:

- the task lease token and owner still match;
- the job and task versions are current;
- cancellation has not been requested;
- the result slot is not already terminal;
- the deadline has not expired.

A stale or duplicate worker may finish local parsing, but it cannot publish or
overwrite the winning result.

## Request flows

### Source preview

1. Authenticate and validate the submitted URL, including DNS resolution and
   private-network policy.
2. Create and enqueue one durable `preview` job.
3. Poll SQLite for a bounded period. The API never calls `run_job`.
4. The worker claims the task and invokes the existing adapter preview path.
5. Direct HTTP runs first; a blocked response may use the existing worker-owned
   browser fallback without changing challenge behavior.
6. The worker atomically publishes the typed result.
7. The API reads the result, adds Managed Source status, and returns the same
   `SourcePreview` schema currently consumed by the frontend.

### Asynchronous chapter import

`POST /api/import/jobs` continues returning `202`. The API only creates and
enqueues. The worker performs every fetch, parse, validation, and import stage.

### Legacy URL import

`POST /api/import/url` becomes a compatibility adapter over the same durable
chapter-import creation path. It returns the existing `JobResponse` without
starting the legacy `JobService` background coroutine.

### Legacy synchronous URL fetch

`POST /api/import/url/fetch` creates the same durable chapter-import job and
waits for a bounded result without draining it in the API. On completion it
maps durable task metadata back to `URLFetchResponse`. On timeout it requests
durable cancellation and returns a typed error instead of executing locally.

### Local development

Local startup launches the API and import worker as separate processes over
the same local SQLite database. Browser-capable source jobs are never handled
by an API background task. Non-browser application jobs are outside this
workstream.

## Error and cancellation contract

Errors remain sanitized and actionable:

| Condition | Browser state | HTTP behavior |
| --- | --- | --- |
| invalid URL, source, or private target | no job or `FAILED` before execution | `400` with stable source-policy code |
| required worker unavailable or heartbeat stale | `CANCELLED` if already queued | `503 worker_unavailable` |
| user verification or protected-source block | `BLOCKED` | existing safe source status with stable code |
| operation deadline exceeded | `TIMED_OUT` | `504 browser_task_timed_out` |
| upstream/browser failure | `FAILED` | `502 browser_task_failed` |
| explicit user cancellation | `CANCELLED` | existing job snapshot contract |
| client disconnect while waiting synchronously | cancellation requested | no continued publication |

Cancellation is checked before browser launch, between stages, after retry
backoff, and in the publication transaction. A timeout first records durable
cancellation/terminal metadata and only then returns the HTTP error.

Worker crashes leave leases recoverable. Recovery may repeat an external read,
but compare-and-set publication prevents duplicate durable results or chapter
publication.

Logs, events, and HTTP errors may contain stable codes, retryability, source or
adapter identifiers, bounded timing, and correlation IDs. They must not contain
raw exceptions, sensitive URL query values, HTML, chapter text, cookies,
credentials, provider-secret paths, or private filesystem paths.

## Image and process boundary

After all production callers are migrated:

- remove `playwright install --with-deps chromium` and
  `PLAYWRIGHT_BROWSERS_PATH` from the API Docker target;
- retain Chromium installation and profile/cookie paths only in the worker;
- keep frontend serving, health checks, ffmpeg, and other API functionality
  unchanged;
- retain separate API and browser-egress networks;
- retain the API-only provider-secret volume overlay;
- add executable-level image assertions instead of source-text-only checks.

No production Compose project is started or changed by this workstream.
Container verification uses isolated project names, ports, volumes, networks,
and temporary data.

## Test strategy

Implementation follows strict red-green-refactor cycles.

### Contract and unit tests

- API preview enqueues and polls; a test fails if it calls
  `PipelineService.preview_source_url` locally.
- Legacy URL routes do not call `JobService.start_import_url_job` or
  `_run_import_job_until_idle` in the API.
- Typed preview serialization rejects sensitive or oversized fields.
- Lease/version mismatch and cancellation reject result publication.
- Timeout, unavailable worker, blocked source, and generic failure map to the
  documented safe contracts.

### SQLite integration tests

- API creation, worker claim, result publication, and unchanged preview
  response operate over one temporary database.
- direct HTTP block triggers browser fallback once in the worker fixture;
- private IPv4, loopback, link-local, CGNAT, private IPv6, and public-to-private
  redirects are blocked before browser navigation;
- cancellation prevents final publication;
- worker lease expiry/restart does not double-publish;
- stale results cannot overwrite a newer logical request;
- challenge integration regressions pass without behavioral expansion;
- provider-secret configuration is absent from worker inputs.

Tests use fake adapters, local fixtures, and loopback-only synthetic services.
They make no paid provider request and do not contact third-party novel sites.

### Container and Compose tests

- build both Docker targets;
- prove the API image has no executable Chromium or Playwright browser binary;
- prove the worker image can launch its installed Chromium against a local
  synthetic page;
- render Compose and prove the worker cannot resolve the provider-secret
  volume/path;
- run one isolated API-plus-worker preview flow with temporary data;
- record API and worker image sizes before and after when Docker is available.

### Full verification

Run the repository gates applicable to the final tree:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run test:e2e -- --project=chromium
scripts/lint.sh
scripts/verify.sh --with-e2e
git diff --check
```

An unavailable gate is reported as unavailable, never converted to a pass.

## Delivery sequence

1. Characterize API/worker ownership and add failing contract tests.
2. Add the typed durable operation/result envelope and atomic publication.
3. Execute preview jobs in the worker and preserve the public response.
4. Migrate legacy URL import/fetch paths to worker-only execution.
5. Make local startup run the dedicated worker.
6. Remove Chromium from the API image and add isolated image/Compose tests.
7. Run focused and full verification and review all security invariants.

Each coherent stage receives a focused commit only after its tests pass. No
push, merge, deploy, restart, DNS/Cloudflare change, production configuration
mutation, or production database action occurs without separate authorization.

## Definition of done

- no production API path directly launches Chromium or drains browser-capable
  source work;
- the API Docker image contains no Chromium runtime;
- the import worker is the canonical browser executor;
- the current preview response contract remains compatible;
- timeout, cancellation, retry, crash recovery, and stale publication behavior
  are deterministic and tested;
- private-network and redirect protections remain enforced;
- provider secrets remain unavailable to the worker;
- protected challenge behavior is unchanged;
- targeted, full, frontend, E2E, container, and Compose gates pass or any
  environmental limitation is reported exactly;
- image-size evidence is recorded when measurable;
- production remains untouched.

## Rollback and compatibility

The database additions are backward compatible and default existing jobs to
`import_chapters`. Rolling application code back leaves the added columns or
result records unused; no user chapter content is rewritten.

The public preview and legacy import response shapes remain unchanged. The
operational change is that a running worker becomes required for
browser-capable source operations. Readiness and error messages make that
dependency explicit rather than silently falling back to browser execution in
the API.
