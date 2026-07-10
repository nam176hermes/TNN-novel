#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/batch-local.sh translate --book-id ID [--limit N] [--preset-id PRESET] [...]
  scripts/batch-local.sh tts --book-id ID [--limit N] [--voice VOICE] [...]
  scripts/batch-local.sh status
  scripts/batch-local.sh logs

Starts local batch jobs in the background, without a web login session and
without requiring the web/API app to keep running.

Examples:
  scripts/batch-local.sh translate --book-id 1 --limit 500 --preset-id balanced
  scripts/batch-local.sh tts --book-id 1 --limit 200

Logs and pid files are written under data/logs/runtime/ by default.
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

EXPLICIT_DATA_DIR_SET=0
EXPLICIT_DATA_DIR=""
if [[ -v DATA_DIR ]]; then
  EXPLICIT_DATA_DIR_SET=1
  EXPLICIT_DATA_DIR="$DATA_DIR"
fi

EXPLICIT_PYTHON_BIN_SET=0
EXPLICIT_PYTHON_BIN=""
if [[ -v PYTHON_BIN ]]; then
  EXPLICIT_PYTHON_BIN_SET=1
  EXPLICIT_PYTHON_BIN="$PYTHON_BIN"
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ "$EXPLICIT_DATA_DIR_SET" -eq 1 ]]; then
  export DATA_DIR="$EXPLICIT_DATA_DIR"
fi
if [[ "$EXPLICIT_PYTHON_BIN_SET" -eq 1 ]]; then
  export PYTHON_BIN="$EXPLICIT_PYTHON_BIN"
fi

PYTHON_BIN="$(resolve_python_bin "$ROOT")"

DATA_DIR_VALUE="${DATA_DIR:-data}"
if [[ "$DATA_DIR_VALUE" = /* ]]; then
  RESOLVED_DATA_DIR="$DATA_DIR_VALUE"
else
  RESOLVED_DATA_DIR="$ROOT/$DATA_DIR_VALUE"
fi
RUNTIME_DIR="$RESOLVED_DATA_DIR/logs/runtime"
mkdir -p "$RUNTIME_DIR"

is_running_pid() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

show_status() {
  shopt -s nullglob
  local files=("$RUNTIME_DIR"/batch-*.pid)
  if [[ "${#files[@]}" -eq 0 ]]; then
    echo "No local batch pid files in $RUNTIME_DIR"
    return
  fi
  local pid_file pid label
  for pid_file in "${files[@]}"; do
    label="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if is_running_pid "$pid"; then
      echo "$label running: pid $pid"
    else
      echo "$label stopped: stale pid ${pid:-unknown}"
    fi
  done
}

show_logs() {
  shopt -s nullglob
  local logs=("$RUNTIME_DIR"/batch-*.log)
  if [[ "${#logs[@]}" -eq 0 ]]; then
    echo "No local batch logs in $RUNTIME_DIR"
    return
  fi
  printf '%s\n' "${logs[@]}" | sort -r
}

start_detached_batch() {
  local kind="$1"
  shift
  local timestamp
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local label="batch-${kind}-${timestamp}"
  local log_file="$RUNTIME_DIR/${label}.log"
  local pid_file="$RUNTIME_DIR/${label}.pid"

  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$PYTHON_BIN" -m app.jobs.batch "$kind" "$@" >>"$log_file" 2>&1 &
  else
    nohup "$PYTHON_BIN" -m app.jobs.batch "$kind" "$@" >>"$log_file" 2>&1 &
  fi
  local pid="$!"
  echo "$pid" >"$pid_file"
  echo "Started $kind batch: pid $pid"
  echo "Log: $log_file"
  echo "Status: scripts/batch-local.sh status"
}

command="$1"
shift

case "$command" in
  translate|tts)
    start_detached_batch "$command" "$@"
    ;;
  status)
    show_status
    ;;
  logs)
    show_logs
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
