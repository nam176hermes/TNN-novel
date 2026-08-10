# WS1 Browser Execution Isolation

WS1 moves every browser-capable source preview and URL chapter import out of
the API process and into the durable import worker. The public preview and
legacy URL response contracts remain compatible; the execution owner and
durable coordination changed.

## Final request flows

### Source preview

1. `POST /api/import/url/preview` validates the public source URL, source
   allowlist, DNS result, and worker readiness.
2. The API creates and enqueues a durable `preview` import job with a bounded
   correlation ID and deadline, then polls SQLite for a terminal result. It
   never calls the source adapter or browser.
3. The import worker claims the preview task, performs direct HTTP and at most
   one browser fallback for a blocked attempt, validates the typed bounded
   result, and publishes it through an atomic lease/version compare-and-set.
4. The API validates the stored typed result again, enriches managed-source
   policy fields in the API process, and maps it to the existing
   `SourcePreviewResponse`.

Terminal preview outcomes map to stable API behavior:

| Outcome | API behavior |
| --- | --- |
| worker missing, stale, release-mismatched, or unable to claim | `503 worker_unavailable` |
| validated completed result | existing synchronous preview response |
| source verification/challenge | stored safe source error, normally `user_verification_required` |
| source failure | stored safe source code/status, or `502 browser_task_failed` for an internal failure |
| deadline expired | `504 browser_task_timed_out` |
| durable cancellation won | `409 browser_task_cancelled` |
| client disconnected while waiting | `499 client_disconnected`, after durable cancellation |

Every initial URL and every redirect is revalidated before browser fallback.
Only globally routable IP targets are accepted; private IPv4, IPv6, CGNAT,
link-local, loopback, metadata, multicast, reserved, and unspecified targets
are rejected.

### URL chapter import compatibility routes

`POST /api/import/url` and `POST /api/import/url/fetch` validate and enqueue
the existing `import_chapters` operation. The dedicated worker owns chapter
fetch/browser fallback and persistence. The synchronous `/url/fetch` adapter
only waits and maps durable task rows into the existing `URLFetchResponse`;
timeout and disconnect use `import_job_timed_out` and `client_disconnected`.
No API request handler or API background task drains the queue or runs an
import stage.

## Durable schema and compatibility

WS1 adds six columns to `import_jobs`:

- `operation_kind`, defaulting to `import_chapters`;
- `deadline_at`;
- `correlation_id`;
- `result_state`;
- `result_snapshot_json`;
- `result_published_at`.

The migration is additive and idempotent. Existing rows backfill naturally to
`import_chapters`, and the existing job/task/event tables and public response
shapes remain intact. Stored browser results are allowlisted Pydantic models:
unknown fields, raw HTML/content, cookies, authorization data, secret-bearing
config keys, overlong values, more than 5,000 chapters, or an envelope larger
than 1 MiB are rejected or removed before persistence. Publication requires a
live task lease, matching owner/job/task versions, a future deadline, no
cancellation, and a correlation ID matching the durable job.

Rollback requires no destructive database migration: stop/drain or cancel WS1
preview jobs, stop the WS1 API and worker, and start the prior application
image while leaving the additive columns in place. Do not drop or rewrite the
SQLite database. A prior binary will continue to create chapter-import rows
using the schema defaults; WS1-only preview results should not be processed by
that binary.

## Local operation

The normal local launcher now starts the worker before declaring the API
ready:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/start-local.sh
scripts/stop-local.sh
```

For separate terminals, with the same `DATA_DIR`:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 python -m app.import_worker
NOVEL_PIPELINE_IGNORE_DOTENV=1 python -m app.mobile_api
```

The Cloudflare launcher also starts and health-checks the worker before the
API. PID files and bounded logs live under `DATA_DIR/logs/runtime`; startup
failure cleans up only processes owned by that invocation.

## Image and secret ownership

The production Dockerfile has distinct `api` and `import-worker` targets. The
API target has no Playwright Chromium. Only the worker target installs and can
launch Chromium. The historical target-less `docker build .` ends at the
browser-free `production` alias of `api`.

Compose gives API and worker separate DNS networks. Provider API keys,
`MOBILE_API_SECRET`, `MOBILE_API_ADMIN_PASSWORD`, and the named
`provider-secrets` volume are API-only. The worker receives import limits,
source-circuit settings, browser paths, and shared application data, but no
provider/API credential environment keys or provider-secret volume. Durable
job config, events, and results are independently sanitized so a caller cannot
smuggle provider secret names or values through the queue.

The authoritative Task 7 Docker smoke built and inspected both targets,
launched Chromium as the unprivileged worker user against an in-memory page,
and reported:

- API image: `324154426` bytes;
- import-worker image: `678568245` bytes.

## Certification evidence

The final security suite uses fake DNS, local HTML, synthetic secret canaries,
temporary SQLite databases, and monkeypatched external browser/network seams.
It never resolves or requests a real novel site. Its six named invariants cover
private/CGNAT/redirect rejection, exactly-once worker fallback, stale-result
correlation, provider-secret persistence, and the legacy API response fixture.

The first Task 8 RED run had two narrow failures: CGNAT could reach fallback,
and `*_API_KEY` config keys could enter the durable snapshot. After the minimal
guards, the six exact invariants passed, and the complete three-file invariant
group passed `35` tests. Focused WS1 backend certification collected and passed
`152` tests.

Final repository evidence, run serially with no overlapping Novel-TNN test or
browser process, was:

- backend: `1560 passed`, `429 warnings`, `486.90s` inside the final verify run
  (an independent full run also passed in `526.84s`);
- frontend unit: `86` files and `784` tests passed in `31.30s` inside verify;
- frontend typecheck: exit `0`;
- production frontend build: `1858` modules transformed, built in `1.11s`;
- Chromium E2E: `19 passed` in `26.7s`;
- compileall, shell syntax, environment validation, lint/typecheck, `pip check`,
  browser availability, frontend build, and `scripts/verify.sh --with-e2e`:
  exit `0`.

The backend warnings are pre-existing dependency/test-setting warnings:
Passlib imports Python's deprecated `crypt` module, and test authentication
uses an HMAC key shorter than PyJWT's recommended 32 bytes. No Task 8 assertion
or gate was skipped.

The worktree intentionally had no `.env`. Therefore the first default local
environment check stopped with the expected `.env is missing` diagnostic. The
final verify used the script's supported production-validation path with an
external mode-`0600` synthetic env file; the checker validated metadata and
required fields without sourcing or printing values. The synthetic file was
outside the repository and removed after verification. No required Docker or
E2E gate was unavailable: Task 7 supplied the authoritative real-Docker gate,
and Task 8 reran the browser E2E gate twice, including inside final verify.

Task 7's Docker isolation smoke was the authoritative container gate. It left
no task-prefixed containers, images, networks, volumes, or temporary paths.
Docker reported two pre-existing high-severity frontend npm audit findings;
WS1 changed no frontend dependency or lockfile.

## Remaining operational risks

- Compose network separation prevents service-name reachability, but the host
  firewall/runbook must enforce destination-level browser egress policy.
- API and worker coordinate through one SQLite file and shared data volume;
  operators must retain tested backup, filesystem ownership, and single-host
  deployment discipline.
- Browser challenge completion may still require operator interaction and a
  fresh worker-local browser profile; WS1 preserves the
  `user_verification_required` outcome rather than bypassing a challenge.
- Rollback should occur only after preview work is drained or cancelled so an
  older binary never sees an in-flight WS1-only operation.

No production deployment, production Compose operation, DNS/Cloudflare change,
operator-database migration, or production-data mutation was executed while
implementing or certifying WS1.
