# P16 — Independent release review

**Reviewed revision:** `58ee0a8 feat(ops): isolate import browser worker deployment` plus the P16 fixes in this worktree.  
**Review date:** 2026-07-16.  
**Scope:** independent maintainer/security review of P00–P15; no product feature, router, API, dependency, or architectural expansion.

## Executive summary

The Plan B implementation has a strong backend foundation for a private,
single-operator deployment. The full backend suite is green and the durable
import path has evidence for typed fetch results, URL policy enforcement,
idempotent storage, durable jobs, retry/concurrency behavior, browser-session
lifecycle, SSE, DOM adapters, quotas/observability, and worker recovery.

P16 found and fixed three concrete defects:

1. P04 URL canonicalization used the default DNS resolver despite being used by
   startup migration/backfill. It now uses the shared URL policy with
   `resolver=None`, so migration canonicalization cannot perform network I/O.
2. A real HTTP `429` response did not propagate `Retry-After` to the P07 retry
   policy. The typed source error now carries a bounded parsed delay.
3. The legacy CAPTCHA utility printed raw exceptions/provider payloads. It now
   emits fixed redacted log messages, with regression coverage.

This is **not production-ready**. The decision is **NO-GO** until the release
gates and safety conditions below are resolved.

## Architecture review

| Milestone | Result | Evidence / review conclusion |
|---|---|---|
| P01 typed fetch contract | Pass | Immutable `FetchResult`, typed `FetchErrorCode`, safe error details, and HTML compatibility wrapper are present. No production thread-local bypass helper remains. |
| P02 URL policy and limits | Pass | Shared policy validates scheme, credentials, ports, IDNA/DNS/IP classes, redirects, content type, byte and timeout limits; browser navigation is guarded. |
| P03 normalized chapter metadata | Pass | One normalizer feeds stored text, length, and hash; metadata API does not return chapter text. |
| P04 identity/idempotency | Pass with P16 fix | SQLite upsert/transaction tests are green. Migration canonicalization is now explicitly network-free. |
| P05 persistent jobs | Pass | SQLite import jobs/tasks/events, owner scoping, counters, optimistic transitions, and migration coverage are present. |
| P06 durable worker/recovery | Pass | Lease claim, cancellation, recovery, and explicit retry semantics are covered with fake pipelines. |
| P07 bounded retry/concurrency | Pass with limitation | The runner releases network semaphores before ordered DB import; per-host, cancellation, retry, ordering, and isolation tests pass. The configured retry time budget is measured within a stage retry loop, so cross-stage wall-clock budgeting should be tightened in a follow-up. |
| P08 browser session manager | Pass under mock | Persistent Playwright context, lazy lifecycle, locking, cookie/profile handling, crash recovery, and sync wrapper pass mocked tests. No real browser was launched. |
| P09 job API/SSE | Pass | Owner isolation, create/get/cancel/retry, event order/reconnect/terminal behavior, and legacy URL route are covered. |
| P10/P11 frontend job state/UI | Partially verified | Types, API client, hook, and ImportPanel job UX typecheck/build, but Vitest did not complete; runtime client/UI behavior is not release-certified. |
| P12/P13 DOM adapters | Pass under fixtures | All registered dedicated adapters are covered by sanitized local fixture/contract tests; no live-layout check was run. |
| P14 observability/quotas | Pass under tests | Redaction, bounded labels, circuit breaker, quotas, source health, and retention tests pass. Metrics remain process-local by design. |
| P15 deployment hardening | Partially verified | Code/static tests pass, but no Docker image, Compose startup, or container health validation could run because Docker is unavailable. |

## Validation record

| Command | Result |
|---|---|
| `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest tests/ --tb=short` | `1026 passed, 2 warnings in 1647.85s (0:27:27)` |
| Focused P01–P15 scenarios: job API/SSE, cancellation/retry/recovery, idempotency, SSRF, runner, browser, DOM, observability, deployment static, and legacy URL route | `164 passed, 1 warning in 443.95s (0:07:23)` |
| `tests/test_browser_session_manager.py` | `17 passed, 1 warning in 12.58s` |
| P04/P05 migration and database performance checks | `6 passed in 17.47s` |
| P16 fetch/retry runtime regression checks | `11 passed in 3.54s` |
| P16 CAPTCHA log-redaction checks | `3 passed in 1.92s` |
| `python -m compileall -q app scripts tests`; shell syntax; `scripts/check-environment.sh`; `scripts/lint.sh`; `git diff --check` | Pass. Environment check emitted the existing `jieba/pkg_resources` deprecation warning. |
| `npm --prefix web run typecheck && npm --prefix web run build` | Pass. Build warns that `sidebar-scenery.png` remains a runtime-resolved asset. |
| `cd web && npx vitest run --pool=threads` | **Not passed:** printed only the Vitest startup banner for about ten minutes, then was stopped (`exit 130`). A targeted P10/P11 Vitest invocation showed the same startup-only stall and was stopped. |
| `docker --version && docker compose version` | **Not run:** `/bin/bash: line 1: docker: command not found`. |

The two full-backend warnings are existing deprecations from `passlib/crypt`
and `jieba/pkg_resources`; neither is a P16 failure.

## Required scenario coverage

- SSE reconnect/cursor, cancel/retry/resume, duplicate concurrent import,
  worker crash/lease recovery, SSRF redirect blocking, and bounded concurrency
  are included in the green focused/backend suites.
- The available mock-source infrastructure is sanitized HTML fixtures and fake
  pipelines, rather than a standalone local HTTP source E2E harness. DOM
  parser/adapter contract tests passed without Internet access.
- Browser lifecycle/navigation tests are mocked; no real browser or external
  source was launched, as required by P16.

## Migration and rollback readiness

`init_db()` migration-up is idempotent and migration tests preserve legacy rows,
add P04/P05 fields, and verify that request connections do not run migrations.
P04 URL canonicalization no longer resolves DNS during backfill.

There is deliberately no executable destructive down migration. The supported
rollback is application/image rollback against the additive SQLite schema:

1. Stop API and worker; take and verify a SQLite backup.
2. Deploy the previous compatible application image.
3. Keep newly added columns/tables/indexes in place; old code ignores them.
4. Do not drop columns or rebuild SQLite tables as an incident shortcut.

This is adequate only when the documented additive-schema compatibility is
preserved. A destructive schema downgrade requires a separately approved,
offline restore/rebuild procedure and was not verified in P16.

## Production defaults to review

| Area | Default |
|---|---|
| Direct fetch | global concurrency 4; per-host concurrency 1 |
| Browser fetch | global concurrency 1; persistent context; max queue 64 |
| HTTP fetch | connect timeout 10s; read timeout 20s; total timeout 30s; max redirects 5; max response 5,000,000 bytes |
| Retry | max attempts 3; base delay 1s; max delay 30s; jitter ratio 0.2; per-stage budget 120s |
| Job quotas | 200 chapters/job; 4 active jobs/owner; 3 retries/task; 5 MiB/chapter; 3600s/job |
| Circuit breaker | threshold 3; window 60s; cooldown 30s |
| Worker | poll 1s; heartbeat stale after 45s; production Compose disables in-API execution |
| Retention | operational events 90 days / 50,000 rows; cleanup batch 500 every 21,600s |

## Monitoring and alert checklist

Before a production release, confirm that the operator can see and alert on:

- API readiness and version; worker heartbeat; SQLite reachability; disk free
  space and database size.
- Active/queued/failed/stale/cancelled jobs, task retries, queue depth, and
  duration-limit failures.
- Fetch bytes/latency, parse failures by adapter/version, circuit transitions,
  source-health degradation, and browser launch/restart counters.
- Backup success/age/checksum/off-site copy plus a scheduled restore drill.
- Redacted logs only: no cookie, token, authorization header, API key, raw
  HTML, chapter text, or private artifact path.

## Remaining risks and release blockers

1. **Docker/Compose was not verified.** Build targets, Compose startup, API and
   worker healthchecks, actual API restart, worker crash recovery, tmpfs, and
   host firewall enforcement must pass on the deployment host.
2. **Frontend Vitest does not complete.** Typecheck/build are green, but the
   P10/P11 state-machine and ImportPanel runtime tests remain uncertified.
3. **Legacy anti-bot code conflicts with Plan B's safety decision.** The source
   tree retains proxy rotation, fingerprint spoofing, and automatic CAPTCHA
   solver paths; `.env.example` exposes their configuration. P16 fixed their
   unsafe logging but did not change behavior. Disable/remove these paths from
   production before release, and make unresolved challenges return
   `user_verification_required`.
4. **No live provider or live-source validation was run.** P12/P13 use local
   fixtures, and P16 intentionally did not call the Internet or launch a real
   browser.
5. **No automated schema down migration exists.** Follow the additive rollback
   procedure above; do not claim a tested destructive downgrade.
6. **Retry budget scope.** P07's 120s retry budget is applied per stage loop,
   not as one end-to-end task clock; tighten it before treating a long
   multi-stage import as fully bounded.

## Release decision

**NO-GO.**

The backend is healthy enough to continue hardening, but a production release
must wait for all of the following: a passing Vitest run, successful Docker
build/Compose/health/recovery verification on the deployment host, removal or
explicit production disablement of the legacy anti-bot behavior, and an
operator-verified monitoring/backup/firewall checklist.
