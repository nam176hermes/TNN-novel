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

DATA_DIR_VALUE="${DATA_DIR:-data}"
if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi
RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"
API_PID_FILE="$RUNTIME_DIR/mobile-api.pid"
WEB_PID_FILE="$RUNTIME_DIR/web-vite.pid"
API_PORT="${MOBILE_API_PORT:-7860}"
WEB_PORT="${WEB_PORT:-5174}"

show_pid() {
  local label="$1"
  local pid_file="$2"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$label running: pid $(cat "$pid_file")"
  else
    echo "$label not running"
  fi
}

show_pid "API" "$API_PID_FILE"
show_pid "Web" "$WEB_PID_FILE"

if "$PYTHON_BIN" scripts/ops.py wait-health --base-url "http://127.0.0.1:${API_PORT}" --timeout 3 >/dev/null; then
  echo "API readiness: ok"
else
  echo "API readiness: unavailable"
fi

if command -v curl >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:${WEB_PORT}/" >/dev/null; then
  echo "Web health: ok"
else
  echo "Web health: unavailable"
fi
