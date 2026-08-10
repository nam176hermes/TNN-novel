#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 007

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ "${NOVEL_PUBLIC_REVIEW_MODE:-0}" == "1" ]]; then
  export VITE_PUBLIC_REVIEW_MODE=1
  echo "Public review route enabled at /review with sanitized frontend-only demo data."
fi

PYTHON_BIN="$(resolve_python_bin "$ROOT")"

CLOUDFLARE_HOSTNAME="${CLOUDFLARE_HOSTNAME:-novel-tnn.tradingcompanydirect.com}"
PUBLIC_URL="https://${CLOUDFLARE_HOSTNAME}"
API_PORT="${MOBILE_API_PORT:-7860}"
DATA_DIR_VALUE="${DATA_DIR:-data}"

if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi

RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"
mkdir -p "$RUNTIME_DIR"
IMPORT_WORKER_PID_FILE="$RUNTIME_DIR/import-worker.pid"

VITE_API_BASE_URL="$PUBLIC_URL" npm --prefix "$ROOT/web" run build

KEEP_IMPORT_WORKER=1 scripts/stop-local.sh || true

listener_pids="$(
  ss -ltnp "sport = :${API_PORT}" 2>/dev/null \
    | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
    | sort -u
)"
if [[ -n "$listener_pids" ]]; then
  echo "Stopping existing API listener(s) on port ${API_PORT}: $listener_pids"
  for pid in $listener_pids; do
    if kill -0 -- "-$pid" 2>/dev/null; then
      kill -- "-$pid" 2>/dev/null || true
    else
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
fi

export MOBILE_API_HOST="${MOBILE_API_HOST:-127.0.0.1}"
export MOBILE_API_PORT="$API_PORT"
export PUBLIC_DEPLOY="${PUBLIC_DEPLOY:-1}"
export MOBILE_API_SERVE_WEB=1
export WEB_DIST_DIR="${WEB_DIST_DIR:-web/dist}"
export MOBILE_API_CORS_ORIGINS="${MOBILE_API_CORS_ORIGINS:-$PUBLIC_URL}"

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

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

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

"$PYTHON_BIN" scripts/ops.py rotate-logs \
  --data-dir "$RESOLVED_DATA_DIR" \
  --max-bytes "${LOG_ROTATE_MAX_BYTES:-1000000}" \
  --keep "${LOG_ROTATE_KEEP:-5}" \
  --force >/dev/null

if is_running "$IMPORT_WORKER_PID_FILE"; then
  echo "Import worker already running: pid $(cat "$IMPORT_WORKER_PID_FILE")"
else
  start_detached "$RUNTIME_DIR/import-worker.log" "$PYTHON_BIN" -m app.import_worker >"$IMPORT_WORKER_PID_FILE"
fi
wait_for_import_worker

start_detached "$RUNTIME_DIR/mobile-api.log" "$PYTHON_BIN" -m app.mobile_api >"$RUNTIME_DIR/mobile-api.pid"

"$PYTHON_BIN" scripts/ops.py wait-health --base-url "http://127.0.0.1:${API_PORT}" --timeout "${API_START_TIMEOUT:-45}"
curl -fsS --max-time 20 "$PUBLIC_URL/api/ready" >/dev/null
curl -fsS --max-time 20 "$PUBLIC_URL/" | grep -q '<div id="root"></div>'

echo "Cloudflare app: $PUBLIC_URL"
