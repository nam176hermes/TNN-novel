#!/usr/bin/env bash
# auto_import_cron.sh — Wrapper for auto_import_watcher.py
# Called by Hermes cron every 5 minutes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"

# Load env
set -a
source "$ROOT/.env" 2>/dev/null || true
set +a

export MOBILE_API_ADMIN_PASSWORD="${MOBILE_API_ADMIN_PASSWORD:-}"
export MOBILE_API_ADMIN_USERNAME="${MOBILE_API_ADMIN_USERNAME:-admin}"
export NOVEL_PIPELINE_URL="http://localhost:7860"

PYTHON_BIN="$(resolve_python_bin "$ROOT")"

"$PYTHON_BIN" scripts/auto_import_watcher.py 2>&1
