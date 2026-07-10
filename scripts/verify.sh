#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"
PYTHON_BIN="$(resolve_python_bin "$ROOT")"
export PYTHON_BIN

export NOVEL_PIPELINE_IGNORE_DOTENV="${NOVEL_PIPELINE_IGNORE_DOTENV:-1}"

"$PYTHON_BIN" -m compileall -q app scripts tests
for script in scripts/*.sh; do
  bash -n "$script"
done
scripts/check-environment.sh
scripts/lint.sh
"$PYTHON_BIN" -m pytest -q -s

"$PYTHON_BIN" -m pip check

npm --prefix web test
npm --prefix web run build
