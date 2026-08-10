#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON_BIN="$(resolve_python_bin "$ROOT")"

DATA_DIR_VALUE="${DATA_DIR:-data}"
if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi
RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"
API_PID_FILE="$RUNTIME_DIR/mobile-api.pid"
WEB_PID_FILE="$RUNTIME_DIR/web-vite.pid"
IMPORT_WORKER_PID_FILE="$RUNTIME_DIR/import-worker.pid"
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
show_pid "Import worker" "$IMPORT_WORKER_PID_FILE"

if "$PYTHON_BIN" -m app.import_worker --healthcheck >/dev/null 2>&1; then
  echo "Import worker health: ok"
else
  echo "Import worker health: unavailable"
fi

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
