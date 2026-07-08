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

export MOBILE_API_HOST="${MOBILE_API_HOST:-127.0.0.1}"
export MOBILE_API_PORT="${MOBILE_API_PORT:-7860}"
export MOBILE_API_SERVE_WEB="${MOBILE_API_SERVE_WEB:-0}"
if [[ "${NOVEL_LOCAL_DISABLE_AUTH:-1}" == "1" ]]; then
  export PUBLIC_DEPLOY=0
  export MOBILE_API_DISABLE_AUTH=1
  export VITE_DISABLE_AUTH=1
fi
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-5174}"

DATA_DIR_VALUE="${DATA_DIR:-data}"
if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi
RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"
mkdir -p "$RUNTIME_DIR"
API_PID_FILE="$RUNTIME_DIR/mobile-api.pid"
WEB_PID_FILE="$RUNTIME_DIR/web-vite.pid"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

start_detached() {
  local log_file="$1"
  shift
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >>"$log_file" 2>&1 &
  else
    nohup "$@" >>"$log_file" 2>&1 &
  fi
  echo $!
}

if is_running "$API_PID_FILE"; then
  echo "API already running: pid $(cat "$API_PID_FILE")"
  "$PYTHON_BIN" scripts/ops.py wait-health \
    --base-url "http://127.0.0.1:${MOBILE_API_PORT}" \
    --timeout "${API_START_TIMEOUT:-45}"
elif "$PYTHON_BIN" scripts/ops.py wait-health --base-url "http://127.0.0.1:${MOBILE_API_PORT}" --timeout 2 >/dev/null 2>&1; then
  rm -f "$API_PID_FILE"
  echo "API already reachable: http://127.0.0.1:${MOBILE_API_PORT}"
else
  "$PYTHON_BIN" scripts/ops.py rotate-logs \
    --data-dir "$RESOLVED_DATA_DIR" \
    --max-bytes "${LOG_ROTATE_MAX_BYTES:-1000000}" \
    --keep "${LOG_ROTATE_KEEP:-5}" >/dev/null
  start_detached "$RUNTIME_DIR/mobile-api.log" "$PYTHON_BIN" -m app.mobile_api >"$API_PID_FILE"
  "$PYTHON_BIN" scripts/ops.py wait-health \
    --base-url "http://127.0.0.1:${MOBILE_API_PORT}" \
    --timeout "${API_START_TIMEOUT:-45}"
fi

if is_running "$WEB_PID_FILE"; then
  echo "Web already running: pid $(cat "$WEB_PID_FILE")"
elif command -v curl >/dev/null 2>&1 && curl -fsS "http://${WEB_HOST}:${WEB_PORT}/" >/dev/null; then
  rm -f "$WEB_PID_FILE"
  echo "Web already reachable: http://${WEB_HOST}:${WEB_PORT}"
else
  if [[ ! -d "$ROOT/web/node_modules" ]]; then
    npm --prefix "$ROOT/web" ci
  fi
  start_detached "$RUNTIME_DIR/web-vite.log" npm --prefix "$ROOT/web" run dev -- --host "$WEB_HOST" --port "$WEB_PORT" >"$WEB_PID_FILE"
fi

echo "API: http://127.0.0.1:${MOBILE_API_PORT}"
echo "Web: http://${WEB_HOST}:${WEB_PORT}"
