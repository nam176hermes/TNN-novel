# Full Project Audit Implementation Note

## Repository Baseline
- Repository root: `/mnt/c/Users/thenam/Documents/Novel-TNN`
- Git status at audit start: no commits yet on `master`
- Working tree state at audit start: all project files untracked after the root move
- Current branch: `master`
- Current commit: none available because the repository has no commits yet
- Destination repo retained its `.git` directory during the source move

## Runtime Environment
- OS path context: Windows-mounted filesystem under WSL
- Python: `Python 3.12.3` on the host shell; `.venv/bin/python` reports `Python 3.11.15`
- Node: `v22.23.0`
- npm: `10.9.8`
- ffmpeg: installed, `6.1.1`
- ffprobe: installed, `6.1.1`
- Disk space on `C:` mount: 388G available at audit start
- Virtual environment exists at `.venv`
- Frontend dependencies exist at `web/node_modules`

## Architecture Summary
- Backend: FastAPI + SQLite + service-layer modules under `app/mobile_api/services`
- CLI/orchestration: `app/main.py` and `scripts/*.sh`
- Frontend: Vite + React + TypeScript under `web/src`
- Storage: `data/pipeline.db` plus `data/raw`, `data/cleaned`, `data/translated`, `data/audio`, `data/exports`, `data/glossary`, `data/logs`
- Deployment model: local dev, local dashboard, and Cloudflare/public-deploy mode

## Major Entry Points
- CLI: `python -m app.main`
- Mobile API: `python -m app.mobile_api`
- Local bootstrap: `scripts/start-local.sh`
- Public bootstrap: `scripts/start-cloudflare.sh`
- Verification: `scripts/verify.sh`
- Frontend dev server: `npm --prefix web run dev`
- Frontend build: `npm --prefix web run build`
- Frontend tests: `npm --prefix web test`

## Database and Storage Summary
- Primary database: `data/pipeline.db`
- Database size at audit start: about 47 MB
- Observed record counts:
  - `books`: 15
  - `chapters`: 4175
  - `glossary_terms`: 3111
  - `translation_jobs`: 0
  - `translated chapters`: 4159
  - `audio files`: 8
- SQLite schema is created and evolved in `app/database/schema.py` and `app/database/db.py`

## Test Baseline
- `git diff --check`: passed
- `npm --prefix web run typecheck`: passed
- `npm --prefix web run build`: passed
- `npm --prefix web test` and integration run: at least one failing integration test in `web/src/App.integration.test.tsx`
- Backend pytest execution using the available shell `pytest`: multiple failures, mostly due missing runtime dependencies in the active Python environment and one import failure from `fastapi/starlette`
- `scripts/verify.sh`: failed early because `python -m pyflakes` is not executable in the current environment

## Environment and Dependency Constraints
- `.venv/bin/python -m pytest` fails because the `pytest` package is not runnable as a module in this environment
- `.venv/bin/python -m pyflakes` fails for the same reason
- System `pytest` is available, but it is not the same interpreter as the project venv
- `app/mobile_api/main.py` currently fails to start in the venv because `fastapi` imports `starlette` incorrectly in this environment
- `jose`, `pyperclip`, and `pyflakes` are not importable from the active system Python environment

## Audit Methodology
- Baseline repo and toolchain first
- Read documentation, scripts, backend routers, services, and frontend entry points
- Measure build/test behavior before any code change
- Use local data and existing test fixtures instead of fabricated examples
- Treat missing dependencies and startup failures as environment drift unless code evidence shows otherwise
- Avoid destructive testing or live paid-provider jobs

## Intentionally Excluded From Destructive Testing
- Live paid-provider translation jobs
- Live paid-provider TTS synthesis
- Production restore over active data
- Database deletion/reset
- Secrets or environment-variable disclosure
- Any multi-user or SaaS behavior

## Preliminary Architecture Notes
- The backend is already split by domain, but some modules are very large:
  - `app/database/db.py`
  - `app/mobile_api/services/pipeline_service.py`
  - `app/mobile_api/routers/import_routes.py`
  - `app/mobile_api/routers/books.py`
  - `app/mobile_api/services/job_service.py`
  - `web/src/components/ReaderView.tsx`
  - `web/src/components/ImportPanel.tsx`
  - `web/src/styles.css`
- The current codebase is maintainable for a single operator, but the reader/import surfaces are dense enough that future splits are justified.
