# P00 Baseline — Novel-TNN

Baseline captured for Plan B P00 on 2026-07-14.

## Repository state

- Working directory: `/mnt/c/users/thenam/documents/novel-tnn`
- Branch: `upgrade-b/00-baseline-and-agent-guidance`
- Commit: `c03dbb4169a100b4f316c8d3abe7d2cac2a6d4b0`
- Python: `.venv/bin/python` 3.11.15
- Node: v22.23.0
- npm: 10.9.8

The baseline was run against a dirty worktree. These files were already modified or untracked before the P00 documentation patch and were not changed by P00:

```text
 M app/ingestion/source_adapters.py
 M app/mobile_api/routers/import_routes.py
 M app/mobile_api/schemas/__init__.py
 M app/utils/stealth_browser.py
 M tests/test_browser_fallback.py
 M tests/test_source_adapters.py
 M web/src/App.tsx
 M web/src/api/client.ts
 M web/src/api/types.ts
 M web/src/components/ImportPanel.tsx
 M web/src/styles/features.css
?? docs/auto-bypass-captcha-system.md
?? docs/upgrade/codex-prompts-modified.md
```

P00 adds only:

```text
AGENTS.md
docs/upgrade/PLAN_B.md
docs/upgrade/BASELINE.md
```

## Verified repository facts

### Backend and production entrypoint

- Backend framework: FastAPI.
- Main app: `app/mobile_api/main.py`.
- Production module entrypoint: `python -m app.mobile_api`.
- Uvicorn wrapper: `app/mobile_api/__main__.py`.
- Local dev scripts: `scripts/start-local.sh`, `scripts/stop-local.sh`.
- Cloudflare/public serve script: `scripts/start-cloudflare.sh`.
- Dockerfile builds the Vite frontend with Node 22, copies `web/dist`, runs Python 3.11, sets `MOBILE_API_SERVE_WEB=1`, and exposes port `7860`.

### Database and migrations

- Database framework: raw `sqlite3`.
- ORM: none.
- Canonical schema: `app/database/schema.py`.
- DB initialization and in-code migrations: `app/database/db.py`.
- Migration mechanism: idempotent SQL/backfill helpers in `init_db()`, not Alembic.
- Current schema version constant observed in code: `2026-07-09-source-catalog-phase8`.

### Package/config

- `pyproject.toml` package: `novel-pipeline`.
- Python requirement: `>=3.11`.
- Dev test dependencies include pytest, pytest-asyncio, httpx, and pyflakes.
- `requirements.txt` includes additional runtime/tooling packages such as Playwright and CAPTCHA-provider clients.
- `web/package.json` scripts include `dev`, `build`, `typecheck`, `test`, `test:e2e`, and `test:watch`.
- CI in `.github/workflows/ci.yml` runs backend compile/script checks and pytest, frontend npm tests/build, and Docker smoke checks.

## Commands run

All backend commands used:

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
```

### Environment/static backend checks

Command:

```bash
.venv/bin/python -m compileall -q app scripts tests
for script in scripts/*.sh; do bash -n "$script"; done
scripts/check-environment.sh
```

Result: pass, exit code 0.

Notes:

- Environment check passed.
- Warning observed from `jieba/_compat.py` about deprecated `pkg_resources`.

### Backend lint wrapper

Command:

```bash
scripts/lint.sh
```

Result: fail, exit code 1.

Failure:

```text
app/utils/stealth_browser.py:24:1: 'app.utils.cookie_store.load_cookies' imported but unused
```

`scripts/lint.sh` stops at pyflakes, so its frontend typecheck stage was not reached in this run.

### Backend tests

Command:

```bash
.venv/bin/python -m pytest -q -s
```

Result: fail, exit code 1.

Summary:

```text
1 failed, 845 passed, 2 warnings in 1022.89s (0:17:02)
```

Failing test:

```text
tests/test_source_adapters.py::test_fetch_public_html_reports_cloudflare_challenge_as_blocked_source
Failed: DID NOT RAISE <class 'app.ingestion.source_adapters.SourceBlockedError'>
```

Warnings observed:

- passlib `crypt` deprecation warning.
- jieba `pkg_resources` deprecation warning.

The reference material mentioned 33 backend tests passing. The actual current backend pytest baseline is not 33 tests; it is 845 passed and 1 failed.

### Frontend typecheck

Command:

```bash
npm --prefix web run typecheck
```

Result: pass, exit code 0.

### Frontend production build

Command:

```bash
npm --prefix web run build
```

Result: pass, exit code 0.

Warning:

```text
./assets/reference-ui/sidebar-scenery.png referenced in ./assets/reference-ui/sidebar-scenery.png didn't resolve at build time, it will remain unchanged to be resolved at runtime
```

Build notes:

- 1850 modules transformed.
- Built in 22.98s.
- Largest observed chunks included `ReaderView`, `ImportPanel`, and app index bundles.

### Frontend tests

Command:

```bash
npm --prefix web test
```

Result: pass, exit code 0.

Summary:

```text
Test Files 80 passed (80)
Tests 705 passed (705)
Duration 514.09s
```

### Full verification

Command:

```bash
scripts/verify.sh
```

Result: fail, exit code 1.

Failure:

```text
app/utils/stealth_browser.py:24:1: 'app.utils.cookie_store.load_cookies' imported but unused
```

`scripts/verify.sh` passed its environment stage and stopped at pyflakes.

### Diff whitespace check

Command:

```bash
git diff --check
```

Result: pass, exit code 0.

## Baseline summary

| Check | Result |
|---|---|
| Compileall/scripts/environment | Pass |
| Backend lint wrapper | Fail |
| Backend pytest | Fail: 1 failed, 845 passed |
| Frontend typecheck | Pass |
| Frontend build | Pass with warning |
| Frontend tests | Pass: 705 tests |
| Full verify | Fail |
| `git diff --check` | Pass |

## Differences between prior documentation and code reality

- Prior reference said there were 33 backend tests passing. Current pytest reports 845 passed and 1 failed.
- The repo does not use an ORM or Alembic; migrations are raw SQLite and in-code.
- Existing code includes legacy browser/captcha/proxy/cookie utilities. Plan B safety rules require no new CAPTCHA evasion, fingerprint spoofing, proxy rotation, or auto CAPTCHA solving.
- Existing frontend source/import types include fields such as `bypass_used` and `bypass_method`; these should not be expanded in Plan B and should be handled carefully in later compatibility work.
- `docs/upgrade/codex-prompts-modified.md` contains older prompt text that preserves bypass-style behavior. It conflicts with the current P00 safety boundary and should not be treated as controlling guidance.
- `requirements.txt` and `pyproject.toml` do not describe exactly the same dependency surface; `requirements.txt` includes additional browser/CAPTCHA-related packages.

## Technical risks found

- Dirty worktree means baseline reflects HEAD plus pre-existing uncommitted changes.
- `app/utils/stealth_browser.py` currently fails pyflakes because `load_cookies` is imported but unused.
- The failing source-adapter test indicates the current Cloudflare/challenge path can avoid raising the expected `SourceBlockedError` under test conditions.
- Legacy stealth/browser/captcha/proxy behavior is a safety and maintenance risk if expanded instead of constrained.
- `app/utils/captcha_solver.py` uses direct provider integrations and should be reviewed for safe logging before any production hardening work.
- Cookie storage defaults outside the repo; cookies must never be logged, copied into docs, or committed.
- Very large files increase regression risk:
  - `app/mobile_api/services/pipeline_service.py`
  - `app/database/db.py`
  - `web/src/components/ImportPanel.tsx`
  - `web/src/api/client.ts`
  - `web/src/api/types.ts`
- Frontend build has an unresolved static asset reference warning.
- Frontend tests are slow on this Windows-mounted path; the observed Vitest run took 514.09s.

## P01 architecture decisions to preserve

- Keep raw SQLite and in-code migrations unless explicitly authorized otherwise.
- Keep source/import API backward compatible where possible.
- Normalize challenge/CAPTCHA/bot-wall outcomes to `user_verification_required`.
- Do not add or expand CAPTCHA evasion, fingerprint spoofing, proxy rotation, or automatic CAPTCHA solving.
- Do not log secrets, cookies, raw HTML, full content payloads, or private paths.
- Treat existing dirty logic changes as separate from P00.
- Fix or account for the current lint/test baseline before claiming later milestones are clean.
