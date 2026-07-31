# Verification Baseline

Validated on 2026-07-10 at
`/mnt/c/Users/thenam/Documents/Novel-TNN`.

## Repository baseline

- Branch: `master`
- Commit: none; the repository has no initial commit
- Worktree: project files are untracked after the root move
- No files were staged or committed during P0
- Safe external backup: `/home/thenam176/novel-tnn-p0-backup-20260710`

## Runtime versions

- Python: 3.11.15 from `.venv/bin/python`
- pip: 25.3
- Node.js: 22.23.0
- npm: 10.9.8
- ffmpeg/ffprobe: 6.1.1
- FastAPI: 0.139.0
- Starlette: 1.3.1
- Pydantic: 2.13.4
- Uvicorn: 0.51.0
- pytest: 8.3.3
- pyflakes: 3.4.0
- bcrypt: 4.0.1

## Validated commands and results

| Command | Result |
| --- | --- |
| `scripts/check-environment.sh` | PASS |
| `.venv/bin/python -m pip check` | PASS, no broken requirements |
| `scripts/lint.sh` | PASS: pyflakes and TypeScript typecheck |
| targeted backend config/database/security smoke | PASS: 80 tests, 2 warnings, 152.28 s |
| `.venv/bin/python -m pytest -q -s` through `scripts/verify.sh` | PASS: 641 tests, 2 warnings, 1518.70 s |
| `npm --prefix web test` | PASS: 69 files, 603 tests, 492.01 s |
| `npm --prefix web run test:e2e` | PASS: 5 Playwright tests, 9.6 s |
| `npm --prefix web run build` | PASS: 1841 modules, measured wall time 26.87 s |
| `scripts/smoke-local.sh` with isolated DB URLs | PASS: health, readiness, login, providers, status, and web shell |
| local readiness, health, CORS, API/web smoke | PASS on isolated DB, API port 7861, web port 5175 |
| browser smoke | PASS across major workflow pages; no console errors observed |
| `git diff --check` | PASS |
| `scripts/verify.sh` | PASS, exit 0, 2064.85 s |

The final `scripts/verify.sh` run included environment checks, compileall, shell
syntax, pyflakes, typecheck, full backend pytest, `pip check`, full frontend
tests, and production build. A SHA-256 guard confirmed that `data/pipeline.db`
did not change during the final gate.

## Frontend integration regression

The translated-library-to-reader test was not a product navigation failure.
On `/mnt/c`, the shell had already switched to `data-active-view="reader"`, but
the lazy ReaderView chunk did not load within Testing Library's default one
second timeout. The same test passed in 1.742 seconds on the Linux filesystem.

The test now waits up to ten seconds for the existing semantic `Đọc truyện`
heading. No product copy, duplicate heading, hidden compatibility element, or
navigation behavior was added. The fixed test passed on `/mnt/c` in 2.545
seconds of test execution.

## Data integrity note

During the first backend smoke before pytest isolation was added, two legacy
security tests used the default repository `DATA_DIR`. They inserted exactly:

- one test auth session;
- two auth operational events (`session_create` and `auth_login_success`).

Read-only table comparisons found no differences in book, chapter, glossary,
audio, export, or other content tables. The three audit/session rows were not
deleted because P0 forbids destructive database cleanup. After
`tests/conftest.py` was corrected, an auth regression test and the final full
verify both confirmed the live database hash remained unchanged.

## Remaining warnings

- `jieba 0.42.1` imports deprecated `pkg_resources`. Current impact is a
  warning during dictionary initialization. Replacement or upstream upgrade is
  recommended before moving to a setuptools release that removes the API.
- `passlib 1.7.4` imports Python's deprecated `crypt` module. It still works on
  Python 3.11; plan an auth hashing library migration before Python 3.13.
- The optional F5/Vietnamese TTS stack, including vinorm, is not part of the
  declared base environment and was not live-provider tested in P0. Existing
  vinorm deprecation risk remains an optional-provider concern.
- Vite reports plugin timing concentration in asset resolution and CSS
  post-processing. This is informational; the production build passes.
- Playwright E2E prints a Node warning about `NO_COLOR` being overridden by
  `FORCE_COLOR`. Tests pass and behavior is unaffected.

## Git baseline plan

Safe initial tracking candidates:

- `.dockerignore`, `.env.example`, `.github/`, `.gitignore`;
- application source under `app/`;
- frontend source, PWA assets, tests, `web/package.json`, and
  `web/package-lock.json`;
- tests under `tests/` and intended root test scripts;
- scripts under `scripts/`;
- documentation under `docs/` and intended top-level Markdown files;
- `pyproject.toml`, `requirements.txt`, `Dockerfile`, `compose.yaml`, and deploy
  configuration.

Never stage:

- `.env`, provider credentials, private keys, or credential JSON;
- `.venv*`, `node_modules`, caches, coverage, or build output;
- SQLite files or sidecars;
- `data/`, novels, translated content, covers, audio, exports, backups, logs,
  inbox files, output screenshots, or private artifacts.

Before the initial commit, review the intended root-level utility and manual
test scripts individually. Do not use `git add .`. Stage explicit paths or a
reviewed path list, inspect `git diff --cached --stat` and
`git diff --cached --name-only`, then commit only after operator approval.
The P0 dry-run found 431 track candidates and no runtime database, dependency
directory, venv, backup, output artifact, or non-ignored file larger than 5 MB.

Suggested initial commit message:

`Establish verified Novel-TNN project baseline`

## Readiness

The repository/environment baseline is ready for a live performance audit.
Modularization should wait until the operator creates and verifies the initial
baseline commit. Recommended sequence after that commit:

1. live performance audit;
2. reader modularization;
3. import modularization;
4. backend repository/service split;
5. CSS feature split.
