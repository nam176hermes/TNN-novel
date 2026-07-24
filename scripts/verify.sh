#!/usr/bin/env bash
set -euo pipefail

run_mandatory_gate() {
  local gate_name="$1"
  shift

  printf '==> %s\n' "$gate_name"
  if "$@"; then
    printf 'PASS: %s\n' "$gate_name"
    return 0
  else
    local status=$?
    printf 'FAIL: %s (exit %d)\n' "$gate_name" "$status"
    return "$status"
  fi
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_E2E=0

check_playwright_chromium() {
  (
    cd "$ROOT/web"
    node --input-type=module <<'NODE'
import { accessSync, constants } from 'node:fs';
import { chromium } from '@playwright/test';

const executable = chromium.executablePath();
try {
  accessSync(executable, constants.X_OK);
} catch {
  console.error(`Playwright Chromium binary is missing or not executable: ${executable}`);
  process.exit(1);
}
NODE
  )
}

if [[ "${1:-}" == "--self-test-failure" ]]; then
  run_mandatory_gate "injected mandatory gate" bash -c 'exit 97'
  exit 0
fi
if [[ "${1:-}" == "--self-test-missing-browser" ]]; then
  export PLAYWRIGHT_BROWSERS_PATH="/nonexistent/novel-tnn-playwright-browsers"
  run_mandatory_gate "browser E2E browser availability" check_playwright_chromium
  exit 0
fi
if [[ "${1:-}" == "--with-e2e" ]]; then
  WITH_E2E=1
  shift
fi
if [[ $# -gt 0 ]]; then
  printf 'Usage: %s [--with-e2e|--self-test-failure|--self-test-missing-browser]\n' "$0" >&2
  exit 2
fi

cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"
PYTHON_BIN="$(resolve_python_bin "$ROOT")"
export PYTHON_BIN

export NOVEL_PIPELINE_IGNORE_DOTENV="${NOVEL_PIPELINE_IGNORE_DOTENV:-1}"

check_shell_syntax() {
  local script
  for script in scripts/*.sh; do
    bash -n "$script"
  done
}

check_environment() {
  if [[ -n "${NOVEL_PIPELINE_PRODUCTION_ENV_FILE:-}" ]]; then
    scripts/check-environment.sh --production --env-file "$NOVEL_PIPELINE_PRODUCTION_ENV_FILE"
  else
    scripts/check-environment.sh
  fi
}

run_mandatory_gate "python compile" "$PYTHON_BIN" -m compileall -q app scripts tests
run_mandatory_gate "shell syntax" check_shell_syntax
run_mandatory_gate "environment" check_environment
run_mandatory_gate "lint and typecheck" scripts/lint.sh
run_mandatory_gate "backend tests" "$PYTHON_BIN" -m pytest -q -s
run_mandatory_gate "python dependency consistency" "$PYTHON_BIN" -m pip check
run_mandatory_gate "frontend tests" npm --prefix web test
run_mandatory_gate "frontend build" npm --prefix web run build
if [[ "$WITH_E2E" -eq 1 ]]; then
  run_mandatory_gate "browser E2E browser availability" check_playwright_chromium
  run_mandatory_gate "browser E2E tests" npm --prefix web run test:e2e -- --project=chromium
fi
