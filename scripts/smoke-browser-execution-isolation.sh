#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_HEX="$(printf '%04x%04x' "$RANDOM" "$RANDOM")"
SMOKE_PREFIX="novel-ws1-$$-${SMOKE_HEX}"
API_IMAGE="${SMOKE_PREFIX}-api:smoke"
WORKER_IMAGE="${SMOKE_PREFIX}-worker:smoke"
API_CONTAINER="${SMOKE_PREFIX}-api-check"
WORKER_CONTAINER="${SMOKE_PREFIX}-worker-check"
NETWORK_NAME="${SMOKE_PREFIX}-network"
VOLUME_NAME="${SMOKE_PREFIX}-volume"
TEMP_ROOT="${TMPDIR:-/tmp}"
TEMP_DIR="$(mktemp -d "${TEMP_ROOT%/}/${SMOKE_PREFIX}.XXXXXXXX")"

case "$TEMP_DIR" in
  "${TEMP_ROOT%/}/${SMOKE_PREFIX}."*) ;;
  *)
    echo "refusing unsafe smoke temp path" >&2
    exit 2
    ;;
esac

cleanup() {
  local exit_status=$?
  set +e
  if command -v docker >/dev/null 2>&1; then
    docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$WORKER_CONTAINER" >/dev/null 2>&1 || true
    docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
    docker image rm -f "$API_IMAGE" "$WORKER_IMAGE" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TEMP_DIR"
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null 2>&1 || {
  echo "docker is required" >&2
  exit 1
}
docker --version >/dev/null
docker compose version >/dev/null
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required" >&2
  exit 1
}

docker build --target api -t "$API_IMAGE" "$ROOT_DIR"
docker build --target import-worker -t "$WORKER_IMAGE" "$ROOT_DIR"

docker run --rm --name "$API_CONTAINER" "$API_IMAGE" sh -ec '
  for candidate in chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "API image contains an executable browser" >&2
      exit 20
    fi
  done
  playwright_root="${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}"
  for executable_path in \
    "$playwright_root"/chromium-*/chrome-linux*/chrome \
    "$playwright_root"/chromium_headless_shell-*/chrome-linux*/headless_shell \
    "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome \
    "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux*/headless_shell \
    /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome \
    /root/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux*/headless_shell; do
    if [ -x "$executable_path" ]; then
      echo "API image contains the Playwright Chromium executable" >&2
      exit 21
    fi
  done
'

docker run --rm --name "$WORKER_CONTAINER" --user novel "$WORKER_IMAGE" python -c '
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        page.set_content("<h1>worker-browser-ok</h1>")
        if page.locator("h1").inner_text() != "worker-browser-ok":
            raise SystemExit("synthetic worker page assertion failed")
    finally:
        browser.close()
'

COMPOSE_ENV="$TEMP_DIR/public.invalid.env"
COMPOSE_JSON="$TEMP_DIR/compose.json"
umask 077
printf '%s\n' \
  'MOBILE_API_SECRET=ws1-render-only-secret' \
  'MOBILE_API_ADMIN_PASSWORD=ws1-render-only-password' \
  'MOBILE_API_CORS_ORIGINS=https://ws1-browser-isolation.invalid' \
  'OLLAMA_HOST=https://ollama.ws1-browser-isolation.invalid/v1' \
  'PUBLIC_DEPLOY=0' \
  >"$COMPOSE_ENV"

docker compose \
  --env-file "$COMPOSE_ENV" \
  -f "$ROOT_DIR/compose.yaml" \
  -p "$SMOKE_PREFIX" \
  config --format json \
  >"$COMPOSE_JSON"

python3 - "$COMPOSE_JSON" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


FORBIDDEN_WORKER_KEYS = {
    "REMOTE_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "MOBILE_API_SECRET",
    "MOBILE_API_ADMIN_PASSWORD",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def network_names(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, dict):
        return set(networks)
    if isinstance(networks, list):
        return {str(name) for name in networks}
    fail("rendered service networks have an unsupported shape")


def environment_keys(service: dict[str, Any]) -> set[str]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return set(environment)
    if isinstance(environment, list):
        return {str(item).split("=", 1)[0] for item in environment}
    fail("rendered service environment has an unsupported shape")


document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
services = document.get("services", {})
if not isinstance(services, dict) or not {"api", "import-worker"}.issubset(services):
    fail("rendered Compose is missing the API or import-worker service")

api = services["api"]
worker = services["import-worker"]
if not isinstance(api, dict) or not isinstance(worker, dict):
    fail("rendered Compose service metadata is invalid")

api_image = api.get("image")
worker_image = worker.get("image")
if not isinstance(api_image, str) or not isinstance(worker_image, str):
    fail("rendered Compose is missing target image names")
if api_image == worker_image:
    fail("API and import-worker must use separate target images")

api_networks = network_names(api)
worker_networks = network_names(worker)
if "api-egress" not in api_networks or "browser-egress" not in worker_networks:
    fail("rendered Compose is missing isolated egress networks")
if api_networks & worker_networks:
    fail("import-worker shares the API DNS network")

worker_mounts = worker.get("volumes", [])
if not isinstance(worker_mounts, list):
    fail("rendered worker mounts have an unsupported shape")
for mount in worker_mounts:
    if isinstance(mount, dict):
        mount_type = str(mount.get("type", ""))
        source = str(mount.get("source", ""))
        if mount_type == "volume" and "provider-secrets" in source:
            fail("import-worker mounts the provider-secret volume")
    elif isinstance(mount, str) and "provider-secrets" in mount.split(":", 1)[0]:
        fail("import-worker mounts the provider-secret volume")
    else:
        fail("rendered worker mount metadata is invalid")

forbidden_keys = environment_keys(worker) & FORBIDDEN_WORKER_KEYS
if forbidden_keys:
    fail("import-worker contains a forbidden provider or API credential key")
PY

API_SIZE="$(docker image inspect --format '{{.Size}}' "$API_IMAGE")"
WORKER_SIZE="$(docker image inspect --format '{{.Size}}' "$WORKER_IMAGE")"
[[ "$API_SIZE" =~ ^[0-9]+$ ]] || {
  echo "API image size is unavailable" >&2
  exit 1
}
[[ "$WORKER_SIZE" =~ ^[0-9]+$ ]] || {
  echo "worker image size is unavailable" >&2
  exit 1
}
printf 'api image bytes: %s\n' "$API_SIZE"
printf 'worker image bytes: %s\n' "$WORKER_SIZE"
