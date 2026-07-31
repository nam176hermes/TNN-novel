# AGENTS.md — Novel-TNN

Repository-level guidance for Codex tasks in Novel-TNN. This file overrides the machine-wide defaults for this repo.

## Scope and working rule

- Keep each prompt scoped as one PR-sized change. Do not start the next milestone unless the user explicitly asks.
- Preserve existing behavior and API compatibility unless the prompt explicitly authorizes a breaking change.
- Do not mix product work, cleanup, refactors, and production fixes in the same patch.
- Preserve user changes. If the worktree is dirty, document unrelated files and avoid touching them.

## Repository map

- `app/`: Python backend, ingestion, storage, translation, TTS, export, CLI, and mobile API.
- `app/mobile_api/main.py`: FastAPI application entrypoint and SPA/static mounting.
- `app/mobile_api/routers/`: FastAPI route modules.
- `app/mobile_api/schemas/`: Pydantic request/response schemas.
- `app/mobile_api/services/`: API-facing service layer, including import/job/pipeline services.
- `app/ingestion/`: source adapters, parsing, ebook/text ingestion.
- `app/database/`: SQLite schema, initialization, in-code migrations, repositories/helpers.
- `app/utils/`: runtime utilities such as browser/session helpers, cookies, proxy pool, async bridge.
- `scripts/`: local, Cloudflare, verification, backup, and operational scripts.
- `tests/`: backend pytest suite.
- `app/mobile_api/tests/`: API pytest suite when present.
- `web/`: React/Vite frontend.
- `web/src/api/`: frontend API client and shared TypeScript types.
- `web/src/components/`: React components, including `ImportPanel.tsx`.
- `.github/workflows/`: CI jobs for backend, frontend, and Docker smoke checks.
- `docs/upgrade/`: Plan B upgrade baseline, roadmap, and milestone notes.

## Environment and setup

Use Python 3.11 and Node 22. The current baseline was verified with `.venv/bin/python` 3.11.15, Node 22.23.0, and npm 10.9.8.

Backend setup:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

Frontend setup:

```bash
npm --prefix web ci
```

## Local run commands

Local dev:

```bash
scripts/start-local.sh
scripts/stop-local.sh
```

Cloudflare/public local serve:

```bash
CLOUDFLARE_HOSTNAME=novel-tnn.tradingcompanydirect.com scripts/start-cloudflare.sh
scripts/stop-local.sh
```

Production container smoke:

```bash
docker build -t novel-pipeline:local .
docker run --rm -p 7860:7860 -e DATA_DIR=/data novel-pipeline:local
```

The backend production entrypoint is:

```bash
python -m app.mobile_api
```

The Docker image sets `MOBILE_API_SERVE_WEB=1`, serves the built SPA, and exposes port `7860`.

## Validation commands

Set this before local validation unless the task explicitly tests `.env` behavior:

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
```

Small backend/static checks:

```bash
.venv/bin/python -m compileall -q app scripts tests
for script in scripts/*.sh; do bash -n "$script"; done
scripts/check-environment.sh
```

Backend lint/typecheck wrapper:

```bash
scripts/lint.sh
```

Backend tests:

```bash
.venv/bin/python -m pytest -q -s
```

Frontend checks:

```bash
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

Full verification:

```bash
scripts/verify.sh
git diff --check
```

Always report commands run, exit status, and any pre-existing failures. Do not claim completion without fresh evidence from the current turn.

## Database and migration conventions

- The app uses raw `sqlite3`; there is no ORM and no Alembic migration stack.
- Canonical schema lives in `app/database/schema.py`.
- Initialization and in-code migrations live in `app/database/db.py`.
- Migrations must be idempotent and backward compatible.
- Use `CREATE TABLE IF NOT EXISTS`, column-existence checks, and explicit backfills.
- Do not reset, delete, compact, or rewrite production/user databases without explicit approval.
- Tests must use isolated temporary data directories/databases.
- Do not modify the operator database during docs-only or baseline phases.

## API and frontend conventions

- Backend routes belong under `app/mobile_api/routers/`.
- Request/response models belong in `app/mobile_api/schemas/`.
- Service logic belongs in `app/mobile_api/services/` or domain services under `app/`.
- Keep frontend API calls in `web/src/api/client.ts` and shared types in `web/src/api/types.ts`.
- When changing an API contract, update backend schema, frontend type, client method, and tests in the same PR.
- Keep backward compatibility unless the prompt explicitly authorizes a breaking API change.

## Import/source safety rules

- Preserve and stabilize existing browser session management (Playwright persistent context). Improve lifecycle, isolation, and recovery around it; do not replace the working mechanism.
- When a site challenge, CAPTCHA, bot wall, or verification step is detected, represent it as `user_verification_required` in the user-facing/import contract for cases the browser session cannot resolve automatically.
- Do not log or persist raw challenge pages, cookies, proxy credentials, API keys, book content, chapter content, or private source payloads.

## Secrets and logging

- Never commit `.env`, cookies, tokens, credentials, provider keys, proxy URLs with credentials, private keys, or generated secret files.
- Keep `.env.example` sanitized.
- Logs must not include secrets, cookies, Authorization headers, passphrases, raw HTML payloads, full chapter text, or private file paths.
- API/UI responses must not expose absolute filesystem paths or secrets.

## Testing and reporting

- Add or update tests for behavior changes when a test harness exists.
- For docs-only changes, run `git diff --check` at minimum and report broader baseline results if gathered.
- If a relevant check cannot be run, state why.
- Mention unrelated failures separately from failures introduced by the current patch.
- End each milestone report with files changed, commands run, pass/fail status, and remaining risks.
