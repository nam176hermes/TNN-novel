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

VITE_API_BASE_URL="$PUBLIC_URL" npm --prefix "$ROOT/web" run build

scripts/stop-local.sh || true

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

"$PYTHON_BIN" scripts/ops.py rotate-logs \
  --data-dir "$RESOLVED_DATA_DIR" \
  --max-bytes "${LOG_ROTATE_MAX_BYTES:-1000000}" \
  --keep "${LOG_ROTATE_KEEP:-5}" \
  --force >/dev/null

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$PYTHON_BIN" -m app.mobile_api >>"$RUNTIME_DIR/mobile-api.log" 2>&1 &
else
  nohup "$PYTHON_BIN" -m app.mobile_api >>"$RUNTIME_DIR/mobile-api.log" 2>&1 &
fi
echo $! >"$RUNTIME_DIR/mobile-api.pid"

"$PYTHON_BIN" scripts/ops.py wait-health --base-url "http://127.0.0.1:${API_PORT}" --timeout "${API_START_TIMEOUT:-45}"
curl -fsS --max-time 20 "$PUBLIC_URL/api/ready" >/dev/null
curl -fsS --max-time 20 "$PUBLIC_URL/" | grep -q '<div id="root"></div>'

echo "Cloudflare app: $PUBLIC_URL"
