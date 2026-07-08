#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:${MOBILE_API_PORT:-7860}}"
WEB_URL="${WEB_URL:-http://127.0.0.1:${WEB_PORT:-5174}}"

"$PYTHON_BIN" scripts/ops.py smoke \
  --base-url "$API_BASE_URL" \
  --username "${MOBILE_API_ADMIN_USERNAME:-admin}" \
  --password "${MOBILE_API_ADMIN_PASSWORD:-change_me}" \
  --web-url "$WEB_URL"
