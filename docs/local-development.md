# Local Development

## Prerequisites

- Python 3.11 with the project `.venv`
- Node.js 22 and npm
- ffmpeg and ffprobe
- `web/node_modules` installed from `web/package-lock.json`
- a local `.env` created from `.env.example`

Run the safety check first:

```bash
scripts/check-environment.sh
```

It prints executable paths and versions, never secret values.

## Install dependencies

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade "pip<26" "setuptools<81" wheel
.venv/bin/python -m pip install -e ".[dev]" -r requirements.txt
npm --prefix web ci
```

## Start and stop

```bash
scripts/start-local.sh
scripts/status-local.sh
scripts/stop-local.sh
```

Default local URLs:

- Web: `http://127.0.0.1:5174`
- API: `http://127.0.0.1:7860`
- Health: `http://127.0.0.1:7860/api/health`
- Readiness: `http://127.0.0.1:7860/api/ready`

`start-local.sh` sources `.env` and defaults to local auth bypass through
`NOVEL_LOCAL_DISABLE_AUTH=1`. This mode is only for loopback development. It
must not be used for a public deployment.

For an authenticated local flow, set `NOVEL_LOCAL_DISABLE_AUTH=0` and use the
operator credentials from `.env`. Do not print those values in terminal logs or
documentation.

## CORS

For the default Vite origin, use exact local origins such as:

```dotenv
MOBILE_API_CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174
```

Public deployments must use exact HTTPS origins and the hardened public start
workflow. Never use `*` with credentialed requests.

## Status and smoke checks

```bash
.venv/bin/python scripts/ops.py wait-health \
  --base-url http://127.0.0.1:7860 \
  --timeout 10
scripts/smoke-local.sh
```

The verified P0 browser smoke covered the workbench, translated library,
reader, import wizard, jobs, sources, glossary/style, provider, status/backup,
and export views. It used a copied database and did not invoke translation or
TTS providers.

## Test data isolation

`tests/conftest.py` assigns every pytest session a temporary `DATA_DIR` before
application settings are imported. This prevents API tests from writing auth
sessions or audit events into `data/pipeline.db`. Keep this isolation in place
for all future tests that import `app.mobile_api.main`.

## WSL filesystem recommendation

The canonical project currently lives under `/mnt/c`. This is functional but
slow for dependency installation, Vitest workers, Python cache writes, and
SQLite process-heavy access.

Measured on the same machine:

| Check | `/mnt/c` | Linux filesystem | Difference |
| --- | ---: | ---: | ---: |
| Frontend production build | 26.87 s | 10.79 s | Linux 2.5x faster |
| Forced Python compileall | 5.50 s | 0.39 s | Linux 14.1x faster |
| 100 read-only SQLite queries | 10.08 s | 0.53 s | Linux 19.0x faster |
| 11-test backend subset | 9.37 s | 8.46 s | Linux 1.1x faster |
| Reader integration test | 59.71 s | 4.14 s | Linux 14.4x faster |

For regular development, keep the working checkout, `.venv`, `node_modules`,
and development database on the WSL Linux filesystem, for example under
`/home/thenam176/Novel-TNN`. Keep Windows access or backups under `/mnt/c` if
needed. Do not move the canonical root or live data automatically; schedule a
separate, verified migration if this recommendation is adopted.
