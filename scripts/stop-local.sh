#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

DATA_DIR_VALUE="${DATA_DIR:-data}"
if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi
RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"

stop_pid_file() {
  local label="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "$label not running: missing $pid_file"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$label not running: stale pid $pid"
    rm -f "$pid_file"
    return
  fi

  if kill -0 -- "-$pid" 2>/dev/null; then
    kill -- "-$pid"
  else
    kill "$pid"
  fi
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "$label stopped"
      return
    fi
    sleep 0.2
  done

  if kill -0 -- "-$pid" 2>/dev/null; then
    kill -9 -- "-$pid" 2>/dev/null || true
  else
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  echo "$label killed"
}

stop_pid_file "Web" "$RUNTIME_DIR/web-vite.pid"
stop_pid_file "API" "$RUNTIME_DIR/mobile-api.pid"
