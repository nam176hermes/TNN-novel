# P14 — Observability and load protection

## Scope

P14 adds bounded, in-process operational instrumentation and limits around the
existing import engine. It does not add a new worker, scheduler, router outside
the authenticated source-health summary, browser bypass behavior, or external
telemetry dependency.

## Safe structured events

`app/observability.py` emits `novel_observability=<json>` records through the
standard logger. Event fields are limited to operational correlation metadata:

- `job_id`, `task_id`, `adapter_id`, `adapter_version`, `fetch_method`;
- `error_code`, `attempts`, `elapsed_ms`, `response_bytes`,
  `parsed_text_length`, `operation`, and `worker_id`.

URLs are reduced to scheme, host, optional port, and path. Query strings,
fragments, and userinfo are removed. Fields or values that can contain a
cookie, Authorization header, token, API key, password, HTML, raw content, or
chapter text are replaced with `[redacted]`. Do not pass source payloads to
the observability API.

## Metrics

The bounded `InMemoryMetrics` collector supports only these labels:
`adapter_id`, `adapter_version`, `fetch_method`, `error_code`, `operation`,
`status`, `stage`, and `state`. It rejects `job_id`, task ids, URLs, and other
unbounded labels. It caps series and latency samples and records P50/P95 from
the retained samples.

Metrics include fetch/request outcomes and latency, response bytes, parsed text
length, parser failures by adapter version, import jobs/tasks/retries/cancels,
import operation results, browser launches/restarts, and global active-job/
queue-depth gauges. They are process-local by design and reset on restart;
exporting them to a durable monitoring backend is deliberately deferred to
deployment work.

## Circuit breaker

The breaker key is `(adapter_id, fetch_method)`. It is `closed`, `open`, or
`half_open`; one half-open probe is admitted after cooldown. Only transient
source failures (`connect_timeout`, `read_timeout`, `rate_limited`,
`source_unavailable`, and `browser_crash`) count toward opening it. Parse,
content, validation, duplicate, cancellation, and verification failures do not
trip the breaker.

Configuration is read from the existing mobile API settings and applied to the
shared process collector:

| Setting | Default | Meaning |
|---|---:|---|
| `SOURCE_CIRCUIT_FAILURE_THRESHOLD` | 3 | Relevant failures inside the window before opening. |
| `SOURCE_CIRCUIT_WINDOW_SECONDS` | 60 | Rolling failure window. |
| `SOURCE_CIRCUIT_COOLDOWN_SECONDS` | 30 | Open duration before one half-open probe. |

Transitions and rejections produce bounded metrics and redacted structured
events. The source task pipeline checks the breaker before network work.

## Server-side import limits

| Setting | Default | Enforcement point |
|---|---:|---|
| `IMPORT_JOB_MAX_CHAPTERS` | 200 | Job creation and request validation. |
| `IMPORT_JOB_MAX_ACTIVE_PER_USER` | 4 | Owner-scoped job creation. |
| `IMPORT_JOB_MAX_RETRIES_PER_TASK` | 3 | P07 retry policy. |
| `IMPORT_JOB_MAX_BYTES_PER_CHAPTER` | 5 MiB | After fetch metadata, before in-memory chapter retention/import. |
| `IMPORT_JOB_MAX_DURATION_SECONDS` | 3600 | Before job execution and between task stages. |

An oversized chapter becomes typed `content_invalid`; duration expiry fails
remaining queued/retry tasks with `job_duration_exceeded`. The implementation
does not persist chapter text in metrics, job events, or quota records.

## Source health view

`GET /api/source-catalog/health` requires the existing authenticated user and
returns aggregate counts only: total, supported, unhealthy, last check time,
and status counts. It deliberately contains no URLs, source payloads, or check
details. Per-source inspection remains behind the authenticated catalog routes.

## Initial alert and response runbook

Configure the deployment monitoring layer to alert on the following sustained
conditions. The exact receiver is deployment-specific; P14 does not introduce
an external notification provider.

| Signal | Initial threshold | First response |
|---|---|---|
| API readiness | readiness fails for 2 minutes | Check API logs, database connectivity, disk, and restart only under the existing runbook. |
| Disk | less than 15% free | Stop creating large artifacts, inspect backups/audio/export storage, use a dry-run cleanup path only. |
| Backup freshness | no successful off-site backup within SLA (initially 24 hours) | Verify latest checksum and run the documented backup job; do not delete old backups automatically. |
| Failed/stale import work | any failed job requiring attention, or queue depth nonzero for 15 minutes without an active worker | Use the job snapshot/events, retry only typed retryable failures, or cancel deliberately. |
| Source circuit | breaker open for more than 5 minutes | Inspect redacted adapter/fetch metrics and source health; wait for cooldown or perform one manual verification. |
| Repeated source failure | three relevant failures for one adapter/method in 5 minutes | Confirm source availability and rate limits; do not add bypass or automatic CAPTCHA handling. |

During incident handling, retain only safe metadata in tickets and logs. Never
paste cookies, provider keys, raw HTML, full URLs with queries, or chapter text.

## Verification

- Unit tests cover redaction, bounded metric labels/percentiles, circuit state
  transitions, quota rejection/byte/duration limits, worker metrics, adapter
  parser/fetch metrics, browser lifecycle metrics, and source-health auth.
- Full backend verification passed with `1020 passed, 2 warnings in 1563.87s`.
  The warnings are the existing `passlib/crypt` and `jieba/pkg_resources`
  deprecations. Backend lint/compile checks, frontend typecheck, production
  build, and `git diff --check` passed.
- The full frontend Vitest run remains an environment release blocker: 49 test
  files / 508 tests passed, but Vitest reported 33 fork-worker startup timeouts.
  A single-worker diagnostic stalled without reporter output and was stopped.
  P14 has no frontend-code changes; rerun the suite where Vitest workers can
  start reliably before release.
