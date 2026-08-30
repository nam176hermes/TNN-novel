#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--describe" ]]; then
  printf '%s\n' '{"cleanup":"automatic","fixture_rows":10000,"journey":"full_each_viewport","viewports":[{"height":900,"name":"desktop","width":1440},{"height":844,"name":"mobile","width":390}]}'
  exit 0
fi
if [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--describe]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"
PYTHON_BIN="$(resolve_python_bin "$ROOT")"
RUN_ROOT="$(mktemp -d /tmp/novel-tnn-phase6-browser-cert-XXXXXX)"
ARTIFACT_ROOT="${PHASE6_BROWSER_ARTIFACT_DIR:-$ROOT/output/playwright/phase6-certification-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
DRIVER="$ROOT/scripts/glossary_phase6_browser_journey.js"
SERVER_PID=""
CURRENT_SESSION=""
CURRENT_ARTIFACT_DIR=""

mkdir -p "$ARTIFACT_ROOT"

playwright_cli() {
  (
    cd "$CURRENT_ARTIFACT_DIR"
    TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
      npx --yes --package @playwright/cli playwright-cli \
      --session "$CURRENT_SESSION" "$@"
  )
}

cleanup_browser() {
  if [[ -n "$CURRENT_SESSION" && -n "$CURRENT_ARTIFACT_DIR" ]]; then
    playwright_cli close >/dev/null 2>&1 || true
    CURRENT_SESSION=""
  fi
}

cleanup_server() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  SERVER_PID=""
}

cleanup() {
  cleanup_browser
  cleanup_server
  if [[ "$RUN_ROOT" == /tmp/novel-tnn-phase6-browser-cert-* \
      && "$RUN_ROOT" != /tmp/novel-tnn-phase6-browser-cert- \
      && -d "$RUN_ROOT" ]]; then
    rm -rf -- "$RUN_ROOT"
  fi
}
trap cleanup EXIT INT TERM

PORT="$("$PYTHON_BIN" - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
BASE_URL="http://127.0.0.1:$PORT"

echo "Building the final static application for $BASE_URL"
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
VITE_API_BASE_URL="$BASE_URL" \
VITE_DISABLE_AUTH=0 \
  npm --prefix "$ROOT/web" run build

for specification in desktop:1440:900 mobile:390:844; do
  IFS=: read -r viewport_name viewport_width viewport_height <<<"$specification"
  data_dir="$RUN_ROOT/$viewport_name/data"
  CURRENT_ARTIFACT_DIR="$ARTIFACT_ROOT/$viewport_name"
  CURRENT_SESSION="phase6-${viewport_name}-$$"
  mkdir -p "$CURRENT_ARTIFACT_DIR"

  echo "Preparing fresh $viewport_name fixture"
  NOVEL_PIPELINE_IGNORE_DOTENV=1 \
    "$PYTHON_BIN" "$ROOT/scripts/prepare_glossary_phase6_fixture.py" \
      --data-dir "$data_dir" --rows 10000 \
      | tee "$CURRENT_ARTIFACT_DIR/fixture.json"

  echo "Starting loopback backend/static app for $viewport_name"
  NOVEL_PIPELINE_IGNORE_DOTENV=1 \
  DATA_DIR="$data_dir" \
  MOBILE_API_HOST=127.0.0.1 \
  MOBILE_API_PORT="$PORT" \
  MOBILE_API_SERVE_WEB=1 \
  WEB_DIST_DIR="$ROOT/web/dist" \
  PUBLIC_DEPLOY=0 \
  MOBILE_API_DISABLE_AUTH=0 \
  MOBILE_API_ADMIN_USERNAME=phase6_operator \
  MOBILE_API_ADMIN_PASSWORD='Phase6-Disposable-Only!2026' \
  MOBILE_API_SECRET='phase6-disposable-certification-secret-2026-000000000000000000000000' \
  MOBILE_API_CORS_ORIGINS="$BASE_URL" \
  CAPTCHA_API_KEY= \
  GEMINI_API_KEY= \
  DEEPSEEK_API_KEY= \
  OPENROUTER_API_KEY= \
  OPENAI_API_KEY= \
    "$PYTHON_BIN" -m app.mobile_api \
      >"$CURRENT_ARTIFACT_DIR/server.log" 2>&1 &
  SERVER_PID=$!

  if ! "$PYTHON_BIN" - "$BASE_URL" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

ready_url = f"{sys.argv[1].rstrip('/')}/api/ready"
deadline = time.monotonic() + 45
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(ready_url, timeout=3) as response:
            payload = json.load(response)
        if payload.get("status") in {"ready", "ready_with_degraded_capabilities"}:
            print(f"OK ready: {ready_url} ({payload['status']})")
            raise SystemExit(0)
    except (OSError, ValueError, urllib.error.URLError):
        pass
    time.sleep(0.5)
print(f"FAIL readiness timeout: {ready_url}", file=sys.stderr)
raise SystemExit(1)
PY
  then
    tail -100 "$CURRENT_ARTIFACT_DIR/server.log" >&2
    exit 1
  fi

  echo "Opening fresh Chromium session for $viewport_name ${viewport_width}x${viewport_height}"
  playwright_cli open "$BASE_URL"
  playwright_cli resize "$viewport_width" "$viewport_height"
  playwright_cli run-code --filename "$DRIVER" \
    | tee "$CURRENT_ARTIFACT_DIR/journey.log"
  playwright_cli close
  CURRENT_SESSION=""
  cleanup_server
done

echo "PHASE6_BROWSER_CERTIFICATION_OK fixtures=2 rows_each=10000 viewports=desktop:1440x900,mobile:390x844 artifacts=$ARTIFACT_ROOT"
