# Environment Recovery

Validated on 2026-07-10 for the repository at
`/mnt/c/Users/thenam/Documents/Novel-TNN`.

## Why the old environment failed

The project was moved from `/home/thenam176/novel_pipeline`. Python virtual
environments are not relocatable in a reliable way: the old `pyvenv.cfg` and
console-script shebangs still referenced the previous root. Its package tree
was also incomplete: several importable package directories had no valid
distribution metadata, `pip` and test modules could not run with `python -m`,
FastAPI could not import `starlette.status`, and Edge TTS could not import its
`yarl` dependency correctly.

The failure was environmental, not a FastAPI product-code regression.

## Canonical runtime

- Python: 3.11
- Evidence: `Dockerfile`, GitHub Actions, README, and the operations runbook all
  select Python 3.11.
- `pyproject.toml` currently declares `>=3.11`; this is broader than the
  operational baseline. Local scripts intentionally require Python 3.11.
- Node.js: 22
- Package manager: npm with `web/package-lock.json`

The validated local interpreter is Python 3.11.15. Do not silently substitute
the host Python 3.12 interpreter.

## Protected backup

Before rebuilding the environment, the operator data was copied outside the
repository to:

`/home/thenam176/novel-tnn-p0-backup-20260710`

The backup contains `data/`, `backups/`, `inbox/`, and a private `.env` copy.
The directory mode is `700`, the copied `.env` mode is `600`, and the copied
database SHA-256 matched the source database at backup time. This location must
not be added to Git.

## Recreate the environment

From the repository root:

```bash
mv .venv .venv.audit-broken-backup
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade "pip<26" "setuptools<81" wheel
.venv/bin/python -m pip install -e ".[dev]" -r requirements.txt
scripts/check-environment.sh
```

The old environment is retained as `.venv.audit-broken-backup/` and ignored by
Git. Remove it only after the operator has accepted the recovered baseline.

## Dependency compatibility

The fresh install resolved to FastAPI 0.139.0, Starlette 1.3.1, Pydantic
2.13.4, and Uvicorn 0.51.0. These versions import and start together.

`passlib 1.7.4` is incompatible with modern bcrypt releases that removed the
legacy `bcrypt.__about__` metadata and changed long-password probe behavior.
Both dependency manifests therefore constrain bcrypt to `>=4.0,<4.1`; the
validated version is 4.0.1.

## Diagnose a broken environment

Use module execution through the project interpreter:

```bash
.venv/bin/python -V
.venv/bin/python -m pip check
.venv/bin/python -c "import fastapi, starlette, pydantic, uvicorn"
.venv/bin/python -c "import jose, pyperclip, pytest, pyflakes, edge_tts"
.venv/bin/python -c "import app.mobile_api"
scripts/check-environment.sh
```

Do not repair a moved venv by editing shebangs or installing missing packages
one at a time. Recreate it from the manifests. The shell scripts use
`PYTHON_BIN` when explicitly supplied; otherwise they require
`<repo>/.venv/bin/python` and fail instead of falling back to system Python.

## Secret handling

`.env` is ignored and must remain local. `.env.example` is a safe template and
must never be copied from the operator `.env`. The environment self-check
verifies that the two files differ and that secret fields in the template use
empty values or explicit replacement placeholders.
