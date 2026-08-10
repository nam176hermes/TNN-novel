#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 007

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"

if [[ "${NOVEL_PIPELINE_IGNORE_DOTENV:-0}" != "1" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON_BIN="$(resolve_python_bin "$ROOT")"

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
IMPORT_WORKER_PID_FILE="$RUNTIME_DIR/import-worker.pid"
OWNED_WORKER_PID=""
OWNED_API_PID=""
OWNED_WEB_PID=""
OWNED_WORKER_TARGET=""
OWNED_API_TARGET=""
OWNED_WEB_TARGET=""
DETACHED_PID=""
DETACHED_TARGET=""

API_HEALTH_REACHABLE=0
WEB_ALREADY_REACHABLE=0
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:${MOBILE_API_PORT}/api/health" >/dev/null; then
  API_HEALTH_REACHABLE=1
fi
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://${WEB_HOST}:${WEB_PORT}/" >/dev/null; then
  WEB_ALREADY_REACHABLE=1
fi

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

start_detached() {
  local log_file="$1"
  shift
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >>"$log_file" 2>&1 &
    DETACHED_PID=$!
    DETACHED_TARGET="-$DETACHED_PID"
    for _ in {1..20}; do
      kill -0 -- "$DETACHED_TARGET" 2>/dev/null && break
      sleep 0.01
    done
  else
    nohup "$@" >>"$log_file" 2>&1 &
    DETACHED_PID=$!
    DETACHED_TARGET="$DETACHED_PID"
  fi
}

stop_owned_pid_file() {
  local pid_file="$1"
  local pid="$2"
  local target="$3"
  [[ -n "$pid" ]] || return 0
  kill -- "$target" 2>/dev/null || true
  for _ in {1..20}; do
    kill -0 -- "$target" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 -- "$target" 2>/dev/null; then
    kill -9 -- "$target" 2>/dev/null || true
    for _ in {1..20}; do kill -0 -- "$target" 2>/dev/null || break; sleep 0.1; done
  fi
  if kill -0 -- "$target" 2>/dev/null; then
    echo "Cleanup could not stop owned process" >&2
    return 1
  fi
  if [[ -f "$pid_file" && "$(cat "$pid_file")" == "$pid" ]]; then rm -f "$pid_file"; fi
}

cleanup_started() {
  local status="$1"
  trap - EXIT
  if (( status != 0 )); then
    stop_owned_pid_file "$WEB_PID_FILE" "$OWNED_WEB_PID" "$OWNED_WEB_TARGET" || true
    stop_owned_pid_file "$API_PID_FILE" "$OWNED_API_PID" "$OWNED_API_TARGET" || true
    stop_owned_pid_file "$IMPORT_WORKER_PID_FILE" "$OWNED_WORKER_PID" "$OWNED_WORKER_TARGET" || true
  fi
  exit "$status"
}
trap 'cleanup_started $?' EXIT

wait_for_import_worker() {
  local timeout="${IMPORT_WORKER_START_TIMEOUT:-45}"
  local deadline=$((SECONDS + timeout))
  while ! "$PYTHON_BIN" -m app.import_worker --healthcheck >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Import worker did not become healthy within ${timeout} seconds" >&2
      return 1
    fi
    sleep 1
  done
}

if is_running "$IMPORT_WORKER_PID_FILE"; then
  echo "Import worker already running: pid $(cat "$IMPORT_WORKER_PID_FILE")"
else
  if ! is_running "$API_PID_FILE" && ! is_running "$WEB_PID_FILE" && (( ! API_HEALTH_REACHABLE && ! WEB_ALREADY_REACHABLE )); then
    "$PYTHON_BIN" scripts/ops.py rotate-logs \
      --data-dir "$RESOLVED_DATA_DIR" \
      --max-bytes "${LOG_ROTATE_MAX_BYTES:-1000000}" \
      --keep "${LOG_ROTATE_KEEP:-5}" >/dev/null
  fi
  start_detached "$RUNTIME_DIR/import-worker.log" "$PYTHON_BIN" -m app.import_worker
  OWNED_WORKER_PID="$DETACHED_PID"
  OWNED_WORKER_TARGET="$DETACHED_TARGET"
  printf '%s\n' "$OWNED_WORKER_PID" >"$IMPORT_WORKER_PID_FILE"
fi
wait_for_import_worker

API_ALREADY_READY=0
if "$PYTHON_BIN" scripts/ops.py wait-health \
  --base-url "http://127.0.0.1:${MOBILE_API_PORT}" \
  --timeout 2 >/dev/null 2>&1; then
  API_ALREADY_READY=1
fi

if is_running "$API_PID_FILE"; then
  echo "API already running: pid $(cat "$API_PID_FILE")"
  if (( ! API_ALREADY_READY )); then
    "$PYTHON_BIN" scripts/ops.py wait-health \
      --base-url "http://127.0.0.1:${MOBILE_API_PORT}" \
      --timeout "${API_START_TIMEOUT:-45}"
  fi
elif (( API_ALREADY_READY )); then
  rm -f "$API_PID_FILE"
  echo "API already reachable: http://127.0.0.1:${MOBILE_API_PORT}"
else
  start_detached "$RUNTIME_DIR/mobile-api.log" "$PYTHON_BIN" -m app.mobile_api
  OWNED_API_PID="$DETACHED_PID"
  OWNED_API_TARGET="$DETACHED_TARGET"
  printf '%s\n' "$OWNED_API_PID" >"$API_PID_FILE"
  "$PYTHON_BIN" scripts/ops.py wait-health \
    --base-url "http://127.0.0.1:${MOBILE_API_PORT}" \
    --timeout "${API_START_TIMEOUT:-45}"
fi

if is_running "$WEB_PID_FILE"; then
  echo "Web already running: pid $(cat "$WEB_PID_FILE")"
elif (( WEB_ALREADY_REACHABLE )); then
  rm -f "$WEB_PID_FILE"
  echo "Web already reachable: http://${WEB_HOST}:${WEB_PORT}"
else
  if [[ ! -d "$ROOT/web/node_modules" ]]; then
    npm --prefix "$ROOT/web" ci
  fi
  start_detached "$RUNTIME_DIR/web-vite.log" npm --prefix "$ROOT/web" run dev -- --host "$WEB_HOST" --port "$WEB_PORT"
  OWNED_WEB_PID="$DETACHED_PID"
  OWNED_WEB_TARGET="$DETACHED_TARGET"
  printf '%s\n' "$OWNED_WEB_PID" >"$WEB_PID_FILE"
fi

echo "API: http://127.0.0.1:${MOBILE_API_PORT}"
echo "Web: http://${WEB_HOST}:${WEB_PORT}"
