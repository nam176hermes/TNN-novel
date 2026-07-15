# Plan B Upgrade Program — Novel-TNN

This is the living plan for the Novel-TNN Plan B upgrade. It is intended to let a fresh Codex task understand the program without relying on chat history.

## Current status

- Active milestone: P02 — URL security and fetch resource limits.
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
- Current schema version constant observed in code: `2026-07-09-source-catalog-phase8`.

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

### P03 — URL preview and chapter fetch ownership

- Make URL preview/chapter fetch outcomes bounded and idempotent.
- Ensure each request has one owner and clear retry semantics.
- Keep import commit behavior backward compatible.

### P04 — Managed source lifecycle and rate policy

- Add or enforce source lifecycle states such as verified, degraded, blocked, and reverify required.
- Enforce per-source delay/concurrency/cooldown where already modeled.
- Avoid broad scheduler rewrites.

### P05 — Import job ownership and retry semantics

- Clarify import job lifecycle and retry/cancel behavior.
- Ensure failure states are durable and user-visible.
- Keep duplicate handling explicit.

### P06 — Import UX for duplicates and verification-required states

- Surface duplicate book conflicts clearly.
- Surface `user_verification_required` as an operator action, not an internal exception.
- Keep current import workflows.

### P07 — Source catalog health

- Make source health checks current and time-bound.
- Track last success, failure streak, and degraded status.
- Avoid permanent trust from stale checks.

### P08 — Browser/session containment

- Constrain legacy browser/session behavior.
- Ensure cookies are never logged or committed.
- Do not add stealth expansion or CAPTCHA automation.

### P09 — Operational observability

- Add useful operational events and dashboards for source/import failures.
- Keep private data out of logs and UI.

### P10 — Import artifact integrity

- Verify metadata-to-file consistency for imported artifacts.
- Provide dry-run reports for missing or invalid artifacts.
- Do not auto-delete or regenerate without explicit confirmation.

### P11 — Frontend import/mobile cleanup

- Reduce mobile overflow and improve touch targets.
- Keep one source of truth for import loading/error states.
- Do not redesign unrelated desktop flows.

### P12 — Backend test matrix expansion

- Add targeted tests for source outcomes, import jobs, challenge states, and logging safety.
- Preserve isolated temp DB/data behavior.

### P13 — Frontend and E2E smoke coverage

- Add or update Vitest/Playwright coverage for import, duplicate, verification-required, and mobile states where practical.

### P14 — Runbooks and operator docs

- Document source import troubleshooting, provider limits, verification-required handling, and safe support steps.

### P15 — Release gate

- Align CI/release requirements with local verification.
- Document rollback and version/commit evidence.

### P16 — Final Plan B verification

- Run full verification.
- Confirm no safety boundary regressions.
- Produce final status and remaining limitations.

## Milestone dependencies

| Milestone | Depends on | Notes |
|---|---|---|
| P00 | none | Establishes baseline and working rules. |
| P01 | P00 | Needs baseline and safety contract. |
| P02 | P01 | Logging/interface work depends on canonical outcomes. |
| P03 | P01, P02 | URL preview/fetch ownership needs normalized result states. |
| P04 | P01 | Source lifecycle uses source status contract. |
| P05 | P03 | Import job ownership depends on preview/fetch ownership. |
| P06 | P01, P05 | UX needs backend states and job semantics. |
| P07 | P04 | Health lifecycle builds on managed source policy. |
| P08 | P02 | Browser/session containment needs isolated interface and safe logging. |
| P09 | P05, P07 | Observability needs stable job/source events. |
| P10 | P05 | Artifact integrity attaches to import job outputs. |
| P11 | P06 | Frontend cleanup follows stable import states. |
| P12 | P01-P10 | Expands backend tests after contracts stabilize. |
| P13 | P06, P11 | UI/E2E tests need stable UX. |
| P14 | P01-P13 | Runbooks should reflect implemented behavior. |
| P15 | P12, P13 | Release gate depends on stable tests. |
| P16 | P15 | Final verification closes the program. |

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
| Source/import safety | Challenge, blocked, timeout, unsupported, duplicate, retry, and redaction tests | no secrets/content in output |
| Mobile UI changes | Vitest and Playwright where practical | viewport, touch-target, overflow notes |

## Current known risks

- The worktree was dirty before P00, including import/source/browser/frontend files.
- P00 baseline had one failing source adapter test and a pyflakes failure; P01 full verification now passes.
- Legacy browser/captcha/proxy/cookie utilities exist and conflict with the desired Plan B safety posture if expanded.
- `docs/upgrade/codex-prompts-modified.md` contains older Plan B prompt text that preserves bypass-style behavior; future tasks must follow this document and root `AGENTS.md` instead.
- Large files such as `pipeline_service.py`, `db.py`, `ImportPanel.tsx`, `client.ts`, and `types.ts` increase regression risk.

## Update rules for future PRs

Every Plan B PR should update this file's current status and decision log when behavior, commands, or milestone status changes. If a milestone changes API behavior, update the test matrix and affected docs in the same PR.
