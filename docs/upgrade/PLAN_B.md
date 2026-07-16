# Plan B Upgrade Program — Novel-TNN

This is the living plan for the Novel-TNN Plan B upgrade. It is intended to let a fresh Codex task understand the program without relying on chat history.

## Current status

- Active milestone: P13 — migrate all remaining dedicated source adapters to the versioned DOM contract; implemented and verified.
- Branch: `upgrade-b/00-baseline-and-agent-guidance`.
- P00 baseline commit: `c03dbb4169a100b4f316c8d3abe7d2cac2a6d4b0`.
- Current implementation commit before P01 edits: `4587885`.
- P01 implementation status: implemented and verified.
- P01 scope stayed limited to fetch contract, error taxonomy, direct call-site conversion, source preview metadata, tests, and this plan update.
- P01 did not add retry, queue, concurrency, SSE, or parser DOM changes.
- P01 removed production use of thread-local bypass metadata and introduced direct `FetchResult` metadata propagation.
- Targeted P01 check: `46 passed, 1 warning` for fetch/browser/source/import URL tests; `scripts/lint.sh` passed.
- Full verification: `scripts/verify.sh` passed with backend `851 passed, 2 warnings`, frontend `705 passed`, and production build passed with the known unresolved `sidebar-scenery.png` asset warning.
- P02 implementation status: implemented and verified.
- P02 scope stayed limited to shared URL policy, DNS/IP validation, redirect validation, fetch resource limits, browser top-level URL validation, tests, and this plan update.
- P02 did not add job queue, retry, concurrency, SSE, parser DOM changes, or frontend behavior.
- Targeted P02 check before full verification: `65 passed, 1 warning` for URL policy/fetch security/browser/source/import URL tests; `scripts/lint.sh` passed.
- Full P02 verification: `scripts/verify.sh` passed with backend `870 passed, 2 warnings`, frontend `705 passed`, and production build passed with the known unresolved `sidebar-scenery.png` asset warning.
- P03 implementation status: implemented and verified.
- P03 scope is limited to the text extraction → normalization → `import_from_text` → stored-file/DB path, typed per-chapter import results, backward-compatible URL fetch metadata, tests, and this plan update.
- P03 does not add idempotency/DB conflict redesign, a job queue, retry/concurrency behavior, or parser DOM work.
- P03 normalizes chapter text once before metadata/hash calculation and storage; URL fetch response `text_length` now represents the actual stored normalized text length.
- Targeted P03 checks covered stored length/hash determinism, empty-content errors, legacy schema defaults, success metadata without chapter text, typed failure metadata, and adjacent P01/P02 fetch regressions.
- Full P03 verification: `scripts/verify.sh` passed with backend `876 passed, 2 warnings`, frontend `705 passed`, and production build passed with the known unresolved `sidebar-scenery.png` asset warning.
- P04 implementation status: implemented and verified.
- P04 scope is limited to canonical source chapter identity, SQLite migration/backfill, and transactional source-backed `import_from_text` upsert semantics.
- P04 does not add job queues, retry, concurrency scheduling, SSE, or parser DOM work.
- Full P04 verification: `scripts/verify.sh` completed after the legacy migration regression was fixed; backend pytest advanced to frontend Vitest and production build without a failing stage. The known build asset warning for `sidebar-scenery.png` remains.
- P05 implementation status: implemented; backend verification complete, frontend full-suite rerun blocked by a pre-existing Vitest stall.
- P05 scope is limited to additive SQLite schema/migration, immutable models, owner-scoped repository operations, optimistic compare-and-set transitions, task-derived counters, and transactional event append.
- P05 does not start or claim work, schedule retry, add API/SSE, or modify the existing `mobile_jobs` worker.
- P05 keeps future import persistence in `import_jobs`, `chapter_tasks`, and `import_job_events`, separate from active `mobile_jobs` behavior.
- Targeted P05 regression: `8 passed, 1 warning` for import-job state/migration plus existing job and legacy migration checks.
- P05 full-check note: the final `scripts/verify.sh` run completed backend pytest (it advanced to Vitest), but Vitest produced only its startup banner for more than ten minutes and was terminated. The P05 diff has no frontend changes; a prior frontend test/build on the unchanged web worktree completed, with the known unresolved `sidebar-scenery.png` build asset warning. Re-run frontend verification in an environment without the observed worker stall before release.
- P06 implementation status: implemented; worker remains sequential and pipeline-injected pending a later real-pipeline integration.
- P06 adds task leases, atomic DB claims, cooperative cancellation, expired-lease recovery, and explicit retryable-task reset. It does not add API routes, SSE, autonomous scheduler threads, retry scheduling, or parallel task execution.
- P07 implementation status: implemented and verified, including the ordered-import deadlock regression fix.
- P07 separates bounded FETCHING/PARSING/VALIDATING callbacks from serialized IMPORTING callbacks so global and per-host network semaphores are released before a task waits for its chapter-order turn.
- Targeted P07 verification: `20 passed in 36.24s`; the three deadlock/cancellation regressions passed in `6.99s`.
- Full P07 backend verification: `892 passed, 2 warnings in 1007.99s (0:16:47)`.
- P07 does not add API routes, SSE, autonomous scheduler threads, real source calls, or source-payload logging.
- P08 implementation status: implemented and verified.
- P08 keeps `launch_persistent_context` as the browser mechanism and adds one lazy, serialized session owner with idle/request/page rotation, health checks, crash restart, and explicit shutdown cleanup.
- P08 hardens cookie state with expiry filtering, corrupt-file rotation, atomic replace, and `0600` permissions; browser profile directories are constrained to `0700` where supported.
- P08 preserves the existing Cloudflare wait/reload path and compatibility wrapper without adding CAPTCHA, fingerprint, proxy, router, SSE, scheduler, or real-source behavior.
- Targeted P08 browser/fetch/lifespan verification: `72 passed, 1 warning in 25.11s` using mocked Playwright only.
- Full P08 backend verification: `909 passed, 2 warnings in 1010.59s (0:16:50)`.
- P09 implementation status: implemented and verified.
- P09 exposes owner-scoped create/get/cancel/retry endpoints and an SSE stream backed by persisted `ImportJobEvent.sequence` cursors.
- P09 keeps GET snapshot as the reconciliation source of truth, supports `Last-Event-ID`/query reconnect, keepalive, terminal close, and disconnect without cancellation.
- P09 moves the compatibility `/api/import/url/fetch` route onto the same durable worker and adds authenticated fetch-streaming transport without changing React UI.
- Targeted P09 backend verification: `43 passed, 1 warning in 103.58s` across the job API, URL compatibility, repository, runtime, and worker suites.
- Targeted P09 client verification: `40 passed in 44.63s` for the API client, including authenticated streaming, cursor reconnect, abort, and typed errors.
- Full P09 backend verification: `927 passed, 2 warnings in 1115.04s (0:18:35)`.
- P09 static verification: backend compile/lint, frontend typecheck, production build, and `git diff --check` passed; the existing unresolved `sidebar-scenery.png` build warning remains.
- P10 implementation status: implemented and verified.
- P10 adds canonical TypeScript job/task/event status contracts, compatibility API aliases, and a standalone `useImportJob` state machine without wiring or redesigning `ImportPanel`.
- P10 keeps GET snapshot authoritative: persisted events only advance an idempotent cursor and trigger snapshot reconciliation.
- P10 resumes the latest non-terminal job from a versioned localStorage key, reconnects SSE with exponential backoff/cursor headers, and falls back to bounded polling.
- Targeted P10 verification: `56 passed in 25.24s` across API client and import-job hook tests; frontend typecheck passed.
- Full P10 frontend verification: `81 test files passed`, `724 tests passed in 545.78s`.
- P10 lint/typecheck, production build, and `git diff --check` passed; the existing unresolved `sidebar-scenery.png` build warning remains.
- P11 implementation status: implemented and verified.
- P11 connects URL chapter selection to the P10 durable job hook, keeps preview/source policy and bypass badges, and leaves paste/file/ebook workflows unchanged.
- P11 pages source selection at 25 rows and task progress at 20 rows, with visible-page selection and full-preview chapter-range selection.
- P11 exposes safe task stage/status/fetch/length/operation/error metadata, cancel/retry/resume/return actions, reconnecting state, live progress, focus management, and responsive 44px controls.
- Targeted P11 verification: `7 passed in 50.40s` for the durable ImportPanel job UX; the CSS ownership regression suite passed `13 tests in 44.13s`.
- Full P11 frontend verification: `82 test files passed`, `731 tests passed in 543.02s`.
- P11 Chromium regression smoke: the existing mocked Import wizard flow passed `1 test in 12.7s`.
- P11 lint/typecheck and production build passed. The existing unresolved `sidebar-scenery.png` build warning remains; no P11 runtime dependency was added.
- P12 reuses Python's standard-library `html.parser`; no production dependency was added.
- P12 introduces ordered selector fallbacks, typed content validation, canonical P03 normalization/hash reuse, and safe regex-fallback telemetry.
- The default `69shuba` and `69shumi` entries now use versioned DOM adapters for `69shuba.com`, `69shuba.cx`, `69shux.com`, `69shumi.com`, and `69shumi.net`, while preserving adapter ids and compatibility.
- Sanitized local fixture plus source/import regression verification: `56 passed in 12.68s`.
- P12 tests make no live source or browser calls. Full backend verification: `960 passed, 2 warnings in 1538.47s (0:25:38)`.
- P13 migrates the remaining 12 dedicated adapters across 16 domains to the P12 DOM contract. The actual registry has 20 dedicated domains, not the 17-domain planning list: `biquge.tw`, `uukanshu.cc`, and `xbanxia.cc` are additional and included.
- P13 preserves the generic catch-all intentionally, but it is not a source-specific versioned DOM adapter.
- P13 keeps regex fallback only for the P12 fixture-proven `69shuba` and `69shumi` layouts; all newly migrated adapters return typed `parse_failed` on selector mismatch.
- P13 registry contract verification: `46 passed in 3.81s`; broader adapter/fetch/source regression verification: `113 passed, 1 warning in 19.13s`.
- Full P13 backend verification: `1006 passed, 2 warnings in 1677.20s (0:27:57)`. The two warnings remain existing `passlib/crypt` and `jieba/pkg_resources` deprecations.

## Goals

Plan B upgrades Novel-TNN toward a safer and more reliable private single-operator production system while preserving current workflows:

- Import from text, ebook, and supported sources.
- Translation jobs and provider usage.
- Glossary, QA, and review workflows.
- Reader, TTS/audio, export, backup, and PWA/offline operations.
- Mobile usability improvements without changing backend business workflows.
- Safer source/import handling when a provider site presents challenges.
- Clear production readiness through tests, runbooks, and release gates.

## Non-goals

- No SaaS or multi-tenant conversion.
- No RBAC/tenant isolation redesign.
- No database replacement while single-operator SQLite remains appropriate.
- No native Android wrapper unless separately approved.
- No broad UI rewrite outside scoped milestones.
- No production dependency additions unless explicitly approved.
- No destructive cleanup, data deletion, DB reset, or archive deletion without explicit approval.
- No new CAPTCHA evasion, fingerprint spoofing, proxy rotation, or automatic CAPTCHA solving.

## Safety boundaries

- Challenges, CAPTCHA, bot walls, and interactive verification requirements must be surfaced as `user_verification_required`.
- Do not expand legacy stealth/browser/cookie/proxy behavior.
- Do not log cookies, Authorization headers, provider keys, proxy credentials, passphrases, raw HTML, chapter text, or private paths.
- Keep protected downloads, path traversal protections, manifest validation, authentication, and private asset checks intact.
- Preserve backward compatibility unless the milestone explicitly authorizes an API change.
- One prompt maps to one PR-sized change. Stop at the milestone boundary.

## Verified current architecture

### Backend

- Framework: FastAPI.
- Main app: `app/mobile_api/main.py`.
- Production module entrypoint: `python -m app.mobile_api`.
- Uvicorn launch wrapper: `app/mobile_api/__main__.py`.
- Docker runtime: Python 3.11 slim with built Vite SPA copied into `web/dist`, `MOBILE_API_SERVE_WEB=1`, `DATA_DIR=/data`, port `7860`.
- Local dev script: `scripts/start-local.sh`.
- Cloudflare/public serve script: `scripts/start-cloudflare.sh`.

### Database

- Database engine: SQLite.
- ORM: none. The code uses raw `sqlite3`.
- Canonical schema: `app/database/schema.py`.
- Initialization and in-code migrations: `app/database/db.py`.
- Migration style: idempotent DDL/backfill helpers during `init_db()`, not Alembic.
- Current schema version constant observed in code: `2026-07-14-import-idempotency-phase4`.

### Import/source path

- Source adapters: `app/ingestion/source_adapters.py`.
- Import routes: `app/mobile_api/routers/import_routes.py` under `/api/import`.
- Import services include `PipelineService`, `EbookImportService`, and `JobService`.
- Frontend import UI: `web/src/components/ImportPanel.tsx`.
- Frontend API client/types: `web/src/api/client.ts`, `web/src/api/types.ts`.
- Existing utility files include `stealth_browser.py`, `captcha_solver.py`, `proxy_pool.py`, `cookie_store.py`, and `asyncio_bridge.py`.
- Important safety note: these utilities currently contain legacy browser/captcha/proxy/cookie capabilities. Plan B must not add new bypass behavior. Future milestones should constrain and expose challenge states as `user_verification_required`.

### Frontend

- Framework: React + Vite + TypeScript.
- Package root: `web/`.
- Scripts: `dev`, `build`, `typecheck`, `test`, `test:e2e`, `test:watch`.
- API surface: `web/src/api/client.ts` and `web/src/api/types.ts`.
- Large active UI components include `ImportPanel.tsx` and reader/status/library components.

### CI

- `.github/workflows/ci.yml` runs backend compile/script checks and pytest, frontend npm tests/build, and Docker smoke checks.
- CI uses Python 3.11 and Node 22.

## Target architecture

Plan B target architecture keeps the existing single-operator app but tightens ownership and operational safety:

- Source/import outcomes use explicit status contracts, including `user_verification_required`.
- Source fetch and browser/session behavior are behind narrow interfaces with safe logging.
- Import preview/commit/job flows are idempotent, bounded, and testable.
- Managed source health is lifecycle-based, not permanently trusted after one success.
- Reader and import frontend states are independently loadable and mobile-safe.
- Operations surfaces show actionable status, not raw internals.
- Backend and frontend APIs remain typed and backward compatible.
- Verification commands and release gates are consistently documented and run.

## Milestones

### P00 — Baseline and agent guidance

- Survey repo structure and actual commands.
- Run baseline checks.
- Create root `AGENTS.md`.
- Create this Plan B living document.
- Create `docs/upgrade/BASELINE.md`.
- No production feature changes.

### P01 — Source challenge contract

- Define canonical source fetch status values, including `user_verification_required`.
- Ensure challenge/CAPTCHA/bot-wall outcomes do not masquerade as successful fetches.
- Preserve existing import compatibility.
- Do not add bypass, spoofing, proxy rotation, or auto-solving.

### P02 — URL security and fetch resource limits

- Add shared URL policy for source fetches.
- Validate scheme, userinfo, port, canonical hostname/IDNA, DNS/IP class, redirect targets, and adapter/source domain boundaries.
- Keep direct HTTP redirects manual and re-validated.
- Bound response bytes and connect/read/total timeouts.
- Validate browser top-level navigation before `page.goto`.
- Do not add job queue, retry, frontend work, SSE, or parser DOM changes.

### P03 — Per-chapter import result correctness and metadata

- Follow chapter text from extraction through canonical normalization, `import_from_text`, stored artifact, and DB record.
- Return immutable typed chapter-import metadata including stored length, content hash, operation, and warnings.
- Extend URL fetch per-chapter results with typed error/fetch/timing metadata while preserving legacy `success` and `error` fields.
- Do not add idempotency/DB conflict redesign, a job queue, retry/concurrency behavior, or parser DOM work.

### P04 — Source chapter idempotency

- Define canonical source chapter identity as the resolved canonical book identity, adapter id, and canonical chapter URL.
- Add backward-compatible canonical URL/content/revision fields with a safe legacy-data backfill.
- Upsert source-backed chapter imports: `created`, `skipped_duplicate`, or `updated`.
- Keep the book resolution and chapter mutation in one SQLite transaction; resolve unique races as idempotent outcomes.
- Reuse the P02 URL policy for canonicalization without migration-time network I/O.
- Do not add job queues, retry/concurrency scheduling, SSE, or parser DOM work.

### P05 — Persistent import-job models

- Add additive SQLite tables for import jobs, per-chapter tasks, and monotonic events without replacing `mobile_jobs`.
- Define durable job/task status and stage state machines, with explicit retry as the sole terminal-task requeue operation.
- Keep reads/transitions owner-scoped, use optimistic compare-and-set versions, and derive import-job counters from tasks in the same transaction.
- Filter HTML/content/cookie/token/secret fields from configuration snapshots and event payloads.
- Do not start workers, claim tasks, schedule retry, add HTTP/SSE, or change parser behavior.

### P06 — Sequential import-job worker core

- Activate P05 jobs through an injected, sequential pipeline: `fetching → parsing → validating → importing → terminal`.
- Claim one task atomically with a durable lease; use SQLite as the scheduling source of truth.
- Support cooperative cancel, expired-lease recovery, and an explicit retry operation only for failed retryable tasks.
- Keep P04 as the idempotency boundary for any real import integration.
- Do not add API/SSE, autonomous scheduler threads, retry scheduling, or task concurrency.

### P07 — Retry, bounded concurrency, and ordered import

- Classify retryable fetch failures with deterministic backoff/time budgets.
- Bound direct/browser work and queue capacity; keep DB importing serialized by chapter order.
- Preserve cancellation, durable retry metadata, and task failure isolation.
- Retry-After is carried on typed source errors and overrides exponential delay.
- Do not add router/API/SSE, scheduler threads, or real source calls.

### P08 — Browser/session containment

- Keep `launch_persistent_context` and reuse one lazy session instead of launching Playwright for every chapter.
- Serialize page control per session; use P07's global browser limit as the outer concurrency boundary.
- Rotate on idle TTL, request/page ceilings, failed health checks, browser crashes, or a corrupt profile.
- Atomically persist unexpired cookies with private permissions and rotate malformed state without logging it.
- Disable downloads, close unexpected popups, and validate top-level navigation through P02 URL policy with injectable DNS resolution.
- Preserve the existing Cloudflare wait/reload behavior and compatibility wrapper without adding stealth or CAPTCHA behavior.

### P09 — Durable import job API and SSE

- Expose owner-scoped create/get/cancel/retry operations for the P05–P07 import engine.
- Stream persisted safe events in sequence order with reconnect cursor, keepalive, and terminal close.
- Keep GET snapshot authoritative and ensure client disconnect never cancels durable work.
- Route legacy synchronous URL fetch through the same job engine without breaking its response contract.
- Add authenticated fetch/AbortController transport and typed client errors; do not change UI.

### P10 — Frontend import job client and state hook

- Complete typed frontend contracts for import jobs, chapter tasks, statuses, stages, events, and mutation responses.
- Preserve P09 client methods while adding canonical `retryFailedTasks` and `subscribeJobEvents` names.
- Add an isolated `useImportJob` state machine for create/resume/reconcile/cancel/retry without redesigning `ImportPanel`.
- Treat GET snapshot as authoritative and persisted SSE sequence only as an idempotent reconnect cursor.
- Resume the latest non-terminal job from minimal versioned browser storage, reconnect SSE with bounded backoff, and fall back to polling.

### P11 — Durable ImportPanel job UX

- Replace blocking URL chapter fetch in production wiring with P10 `useImportJob` create/reconcile/cancel/retry/resume behavior.
- Keep URL preview, source policy, chapter selection, bypass badge, and legacy callback compatibility.
- Show aggregate and per-chapter progress with safe fetch-method and error labels.
- Bound source and task DOM size through pagination, visible-page selection, and chapter-range selection.
- Keep reconnecting distinct from failure and provide live-region/focus/touch-target/mobile behavior.
- Do not redesign paste/file/ebook or unrelated desktop flows.

### P12 — DOM parser framework and 69shuba-family migration

- Add a versioned DOM parser contract covering domain policy, P02 URL canonicalization, preview/chapter parsing, normalization, validation, and content hashing.
- Use ordered selector fallbacks for metadata, chapter links/content, and junk-removal selectors.
- Detect status-200 challenge/error pages, empty/short content, chapter-list misclassification, and abnormal boilerplate.
- Migrate the `69shuba` and `69shumi` family domains while preserving adapter ids and backward-compatible result fields.
- Retain regex extraction only as a selector-mismatch fallback with safe adapter/version/target telemetry.
- Verify exclusively with sanitized local fixtures; do not call live sources.

### P13 — Migrate remaining source adapters

- Move every remaining registered source to the P12 versioned parser contract.
- Add sanitized local fixtures and parameterized contract tests per adapter.
- Keep regex fallback only where fixture evidence proves it remains necessary.
- Document the process for adding and versioning a source adapter.

### P14 — Observability and load protection

- Add bounded-cardinality structured logs and metrics for jobs, tasks, adapters, parser versions, fetch methods, errors, latency, and operations.
- Enforce redaction, quotas, and per-adapter/fetch-method circuit breakers.
- Add authenticated source-health reporting and an initial alert/runbook specification.

### P15 — Deployment hardening

- Separate API and durable import/browser worker entrypoints in production.
- Harden containers, lifecycle, health checks, resource limits, browser egress, secret injection, startup recovery, and rollback/runbooks.
- Verify crash recovery and idempotent work continuation in an isolated deployment environment.

### P16 — Independent final review

- Review P00-P15 as a maintainer/security reviewer without adding new product features.
- Run the complete backend, frontend, migration, mock-source, SSE, recovery, SSRF, concurrency, and redaction matrix.
- Produce `docs/upgrade/RELEASE_REPORT.md` and an evidence-based GO / GO WITH CONDITIONS / NO-GO decision.

## Milestone dependencies

| Milestone | Depends on | Notes |
|---|---|---|
| P00 | none | Establishes baseline and working rules. |
| P01 | P00 | Needs baseline and safety contract. |
| P02 | P01 | Logging/interface work depends on canonical outcomes. |
| P03 | P01, P02 | URL preview/fetch ownership needs normalized result states. |
| P04 | P02, P03 | Canonical URLs and normalized content hashes are prerequisites for idempotent source imports. |
| P05 | P03 | Import job ownership depends on preview/fetch ownership. |
| P06 | P04, P05 | Sequential worker relies on idempotent import identity and durable job/task state. |
| P07 | P04, P05, P06 | Retry/concurrency relies on durable tasks, leases, and idempotent import. |
| P08 | P02, P07 | Browser containment needs URL policy and the outer global browser concurrency limit. |
| P09 | P05, P07 | Observability needs stable job/source events. |
| P10 | P09 | The frontend state machine requires the durable job snapshot and persisted SSE contract. |
| P11 | P10 | ImportPanel cleanup consumes the stable P10 hook instead of owning transport state. |
| P12 | P01, P02, P03 | Uses typed source errors, shared URL policy, and canonical normalization/hash semantics. |
| P13 | P12 | Remaining adapters consume the versioned DOM parser contract and fixture conventions. |
| P14 | P05-P13 | Observability and quotas require stable jobs, workers, browser lifecycle, APIs, UI, and parsers. |
| P15 | P05-P14 | Deployment isolation depends on the durable worker and operational contracts. |
| P16 | P00-P15 | Final independent verification closes the complete program. |

## Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-07-14 | Keep SQLite/raw `sqlite3` for Plan B. | Current product is private single-operator; no evidence justifies DB replacement in this program. |
| 2026-07-14 | Treat in-code migrations as the current migration system. | No Alembic or ORM migration framework is present. |
| 2026-07-14 | Do not add CAPTCHA evasion, fingerprint spoofing, proxy rotation, or auto CAPTCHA solving. | Safety boundary for source import work; challenges must become operator-visible states. |
| 2026-07-14 | Use `user_verification_required` for challenge states. | Keeps import truthful and avoids hidden bypass behavior. |
| 2026-07-14 | Keep API backward compatibility by default. | Existing frontend, tests, and operator workflows depend on current contracts. |
| 2026-07-14 | One prompt equals one PR-sized milestone. | Reduces regression risk and keeps verification meaningful. |
| 2026-07-14 | P01 fetches return immutable `FetchResult` metadata; `fetch_public_html()` remains as a deprecated compatibility wrapper returning HTML. | Removes thread-local side-channel state while preserving legacy HTML callers. |
| 2026-07-14 | P01 source preview keeps `bypass_used`/`bypass_method` for compatibility and adds direct fetch metadata fields. | Existing UI/API clients remain compatible while new callers can read typed metadata. |
| 2026-07-14 | P01 source adapter errors keep string `detail` in HTTP responses and add fetch error code/retryable headers. | Avoids breaking old clients while removing the need to parse error strings for converted routes. |
| 2026-07-14 | P02 centralizes source URL checks in `app/security/url_policy.py`. | Preview, chapter, redirect, and browser navigation need one canonical policy and injectable DNS resolver for tests. |
| 2026-07-14 | P02 direct HTTP keeps `allow_redirects=False` and validates every redirect target before following. | Prevents public-to-private and cross-adapter redirects without adding retry/queue behavior. |
| 2026-07-14 | P02 keeps URL query/userinfo out of error details via redacted URL handling. | Fetch errors must carry typed codes without leaking credential/query-bearing URLs. |
| 2026-07-14 | P03 canonicalizes chapter Unicode and whitespace before source hashing and persistence. | Length and hash must describe the exact stored chapter text, not an intermediate extraction value. |
| 2026-07-14 | P03 uses immutable `ChapterImportResult` with mapping compatibility for legacy callers. | New typed metadata is available without breaking existing dictionary-style import consumers. |
| 2026-07-14 | P03 retains legacy URL fetch `success` and `error` fields while adding typed metadata defaults. | Existing clients can deserialize old and new responses during the transition. |
| 2026-07-14 | P04 treats `(resolved book id, adapter_id, canonical_chapter_url)` as a source chapter identity. | `book_id` is the durable result of the existing canonical `book_key` resolver; including adapter and canonical URL avoids chapter-number-only duplicate decisions. |
| 2026-07-14 | P04 backfill leaves legacy identity collisions intact and marks the non-canonical row rather than deleting data. | A migration must not silently merge or delete operator records merely to create a unique index. |
| 2026-07-14 | P04 uses `BEGIN IMMEDIATE` around source-backed book resolution and chapter upsert. | SQLite serializes concurrent writers and lets a second matching import return `skipped_duplicate`, not HTTP 500. |
| 2026-07-14 | P05 introduces import job persistence beside, rather than inside, `mobile_jobs`. | Existing translation/TTS worker lifecycle remains stable while a later import worker gains a bounded migration seam. |
| 2026-07-14 | P05 transitions, task-derived counters, and events share one SQLite transaction with optimistic versions. | A persisted state cannot report counters/events that disagree with the task transition that produced it. |
| 2026-07-14 | P05 strips sensitive payload keys before persisting job config/events. | Durable operational metadata must not become a second store for content, cookies, or secrets. |
| 2026-07-15 | P06 uses per-task leases and `BEGIN IMMEDIATE` claims rather than an in-memory queue. | SQLite remains the source of truth across worker restarts while P06 stays single-task sequential. |
| 2026-07-15 | P06 exposes retry only as an explicit reset of failed `retryable` tasks. | No automatic retry/backoff policy is introduced before its separate milestone. |
| 2026-07-15 | P08 owns Playwright persistent context lifecycle in `BrowserSessionManager`; sync callers use one dedicated daemon event-loop thread. | Playwright async objects retain loop affinity while the legacy synchronous API reuses a process/session instead of relaunching per chapter. |
| 2026-07-15 | P08 checks idle/request/page/health rotation lazily at session use and performs explicit FastAPI/atexit cleanup. | The milestone forbids a scheduler thread; lazy checks provide bounded lifetime without an autonomous timer. |
| 2026-07-15 | P08 rotates malformed cookie/profile state and logs only redacted URLs plus exception type. | Recovery metadata must not expose cookies, query secrets, HTML, content, or private paths. |
| 2026-07-15 | P09 treats the authenticated `user_id` (username fallback only for auth-bypass compatibility) as the owner on every import-job route. | Ownership is server-derived; cross-owner existence is hidden behind a typed 404. |
| 2026-07-15 | P09 uses persisted event sequence as SSE id and GET snapshot as the reconciliation source of truth. | Reconnect remains deterministic and event delivery cannot become a second mutable state store. |
| 2026-07-15 | P09 uses FastAPI background tasks only as an immediate run trigger while SQLite remains the durable queue. | Client disconnect does not cancel work and no autonomous scheduler is added in this milestone. |
| 2026-07-15 | P09 keeps fetched source text in the worker's in-memory stage cache and persists only safe task metadata. | Durable config/events must not contain chapter text, HTML, cookies, tokens, or secrets. |
| 2026-07-15 | P10 uses GET snapshot as the only mutable frontend job truth; events only advance a monotonic cursor and request reconciliation. | Duplicate or out-of-order SSE delivery cannot double-apply counters or regress task state. |
| 2026-07-15 | P10 stores only the latest non-terminal `job_id` under a versioned localStorage key. | Page refresh can resume safely without persisting task payloads, source data, HTML, content, cookies, or secrets. |
| 2026-07-15 | P10 adds canonical client names as wrappers while retaining P09 method names. | P11 can use a clear API without breaking existing callers during migration. |
| 2026-07-15 | P11 production wiring uses the P10 durable client; the old blocking URL chapter callback remains an optional compatibility fallback only. | The operator sees immediate job acceptance and recoverable progress while existing external ImportPanel callers do not break. |
| 2026-07-15 | P11 paginates source chapters and task details instead of adding a virtualization dependency. | Fixed pages bound DOM size, preserve simple checkbox semantics, and meet the milestone without changing the dependency graph. |
| 2026-07-15 | P11 displays a conservative `Đã lưu` operation when P09 omits the optional operation field. | The UI must not invent `created` versus `updated`; a future additive snapshot field can provide the exact P04 outcome without breaking the client. |
| 2026-07-16 | P12 uses Python's standard-library `html.parser` instead of importing transitive `lxml` or adding a parser dependency. | The repository had no declared general-purpose HTML parser dependency; the scoped selector subset is sufficient and keeps installation reproducible. |
| 2026-07-16 | P12 centralizes canonical text normalization/hash in a neutral ingestion module and preserves the existing import-metadata import path. | DOM extraction and P03 persistence metadata must calculate the same deterministic stored-text hash without breaking callers. |
| 2026-07-16 | `69shuba` and `69shumi` keep their existing adapter ids/domains while moving to versioned DOM selector configs. | Registry, persisted identity, telemetry, and existing callers remain backward compatible. |
| 2026-07-16 | Regex extraction is allowed only after a DOM selector mismatch and emits telemetry containing adapter id, adapter version, and target type only. | Challenge, missing, and invalid content must remain typed failures; logs must not contain URLs, HTML, or chapter text. |
| 2026-07-16 | P13 treats the runtime registry as source of truth: 20 dedicated domains rather than the 17-domain planning list. | `biquge.tw`, `uukanshu.cc`, and `xbanxia.cc` were already registered and must receive the same safety/fixture coverage as the listed domains. |
| 2026-07-16 | Only 69shuba-family adapters retain a regex fallback. | P12 has fixture evidence for those fallback layouts; P13 selector mismatches are typed failures until an equivalent fixture proves a compatibility path is needed. |

## Test matrix

| Area | Commands / coverage | Required reporting |
|---|---|---|
| Python syntax/scripts | `.venv/bin/python -m compileall -q app scripts tests`; `for script in scripts/*.sh; do bash -n "$script"; done`; `scripts/check-environment.sh` | pass/fail and warnings |
| Backend lint/type wrapper | `scripts/lint.sh` | pyflakes/typecheck results |
| Backend tests | `.venv/bin/python -m pytest -q -s` | pass/fail/skip count, failing tests |
| Frontend unit tests | `npm --prefix web test` | pass/fail file and test counts |
| Frontend typecheck | `npm --prefix web run typecheck` | pass/fail |
| Frontend build | `npm --prefix web run build` | pass/fail and build warnings |
| Full verification | `scripts/verify.sh` | first failing stage and cause |
| Diff hygiene | `git diff --check` | pass/fail |
| API contract changes | Backend schema tests plus frontend type/client tests | compatibility notes |
| Source/import safety | Challenge, blocked, timeout, unsupported, duplicate, stored text length/hash, typed failure metadata, and redaction tests | no secrets/content in output |
| P05 import persistence | State transitions, explicit task retry, cancel idempotency, owner isolation, derived counters, monotonic events, and legacy migration | no worker/API/SSE side effects |
| P06 import worker | Sequential success, partial failure, cancel before/during stage, expired lease recovery, atomic claim, explicit retry, and fake-pipeline idempotency simulation | no real source/browser calls or parallel execution |
| P08 browser/session | Mocked persistent-context reuse, per-session serialization, idle/request/health/crash restart, popup/download/navigation containment, cookie expiry/atomic permissions/corrupt recovery, compatibility wrapper, and application shutdown | no real browser/source calls and no cookie/query/content in logs |
| P09 import API/SSE | Create/get/cancel/retry, owner isolation, quota/URL validation, ordered persisted events, cursor/header reconnect, keepalive, disconnect, terminal close, legacy route, client fetch stream/abort, and typed errors | no Internet calls, no source content in snapshot/events, GET snapshot remains authoritative |
| P10 frontend import state | Typed job/task/event contracts, reducer phases, idempotent cursor, snapshot reconciliation, SSE reconnect/backoff, polling fallback, cancel/retry, resume storage, and typed error mapping | no ImportPanel redesign, no source payload or secret persistence |
| P11 ImportPanel job UX | Selected-chapter create, progress reconciliation, partial result, cancel/retry, refresh resume, reconnecting, fetch badges, operation/error copy, source/task pagination, range selection, focus and live-region behavior | no blocking fetch in production wiring, no thousand-row checkbox/task DOM, no source payload or secret rendering |
| P12 DOM parser | Sanitized 69shuba-family fixtures for preview/chapter extraction, relative/absolute links, entities/Unicode, junk removal, selector fallback, regex fallback, 404, status-200 challenge, empty/short content, chapter-list misclassification, boilerplate ratio, and all five allowed domains; then full backend pytest | no Internet/browser calls; typed errors preserved; fallback telemetry contains no URL, HTML, or chapter content |
| P13 all dedicated adapters | Parameterized normal fixture and status-200 challenge coverage for 12 remaining adapters / 16 domains; inventory assertion for all 20 dedicated domains and fallback allowlist assertion | no Internet/browser calls; P13 selectors have no regex fallback; generic catch-all is explicitly excluded |
| Mobile UI changes | Vitest and Playwright where practical | viewport, touch-target, overflow notes |

## Current known risks

- The worktree was dirty before P00, including import/source/browser/frontend files.
- P00 baseline had one failing source adapter test and a pyflakes failure; P01 full verification now passes.
- Legacy CAPTCHA/proxy utilities remain present but P08 does not expand them; future work must continue treating challenge handling as a constrained compatibility path.
- P09 triggers accepted jobs in-process; durable queued state survives, but there is still no autonomous polling worker that starts orphaned queued jobs without an operational trigger.
- `docs/upgrade/codex-prompts-modified.md` contains older Plan B prompt text that preserves bypass-style behavior; future tasks must follow this document and root `AGENTS.md` instead.
- P13 validates all dedicated adapters against sanitized local fixtures only. Live-layout validation remains outside CI; regex fallback is limited to the P12-proven 69shuba-family compatibility seam.
- Large files such as `pipeline_service.py`, `db.py`, `ImportPanel.tsx`, `client.ts`, and `types.ts` increase regression risk.

## Update rules for future PRs

Every Plan B PR should update this file's current status and decision log when behavior, commands, or milestone status changes. If a milestone changes API behavior, update the test matrix and affected docs in the same PR.
