#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

export NOVEL_PIPELINE_IGNORE_DOTENV="${NOVEL_PIPELINE_IGNORE_DOTENV:-1}"

"$PYTHON_BIN" -m compileall -q app scripts tests
for script in scripts/*.sh; do
  bash -n "$script"
done
scripts/lint.sh
"$PYTHON_BIN" -m pytest -q -s

if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip check
fi

if command -v npm >/dev/null 2>&1; then
  npm --prefix web test
  npm --prefix web run build
else
  echo "npm not found; skipped frontend verification" >&2
fi
