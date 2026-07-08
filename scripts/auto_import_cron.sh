#!/bin/bash
# auto_import_cron.sh — Wrapper for auto_import_watcher.py
# Called by Hermes cron every 5 minutes
set -euo pipefail

cd /home/thenam176/novel_pipeline

# Load env
set -a
source /home/thenam176/novel_pipeline/.env 2>/dev/null || true
set +a

export MOBILE_API_ADMIN_PASSWORD="${MOBILE_API_ADMIN_PASSWORD:-}"
export MOBILE_API_ADMIN_USERNAME="${MOBILE_API_ADMIN_USERNAME:-admin}"
export NOVEL_PIPELINE_URL="http://localhost:7860"

# Use venv python
PYTHON=/home/thenam176/novel_pipeline/.venv/bin/python

$PYTHON scripts/auto_import_watcher.py 2>&1
