#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mode="development"
production_env_file=""

usage() {
  cat <<'EOF'
Usage: scripts/check-environment.sh [--production --env-file PATH]

Without options, validate the local-development checkout, including its ignored
.env file and host-writable runtime data directory. Production mode instead
validates the metadata and required values of an external production env file;
it never sources or prints that file and deliberately leaves container-owned
runtime volume checks to the running service.
EOF
}

while (($#)); do
  case "$1" in
    --production)
      mode="production"
      shift
      ;;
    --env-file)
      (($# >= 2)) || { usage >&2; exit 2; }
      production_env_file="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/python.sh"
PYTHON_BIN="$(resolve_python_bin "$ROOT")"

failures=0

ok() {
  echo "OK: $1"
}

fail() {
  echo "ERROR: $1" >&2
  failures=$((failures + 1))
}

require_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    ok "$command_name $("$command_name" --version 2>&1 | head -n 1)"
  else
    fail "$command_name is required but was not found"
  fi
}

production_env_value() {
  local key="$1"
  awk -v requested_key="$key" '
    $0 !~ /^[[:space:]]*#/ {
      separator = index($0, "=")
      if (separator > 0 && substr($0, 1, separator - 1) == requested_key) {
        value = substr($0, separator + 1)
        found = 1
      }
    }
    END {
      if (found) print value
    }
  ' "$production_env_file"
}

validate_production_env() {
  [[ -n "$production_env_file" ]] || { fail "--env-file is required with --production"; return; }
  [[ -f "$production_env_file" && ! -L "$production_env_file" ]] || {
    fail "production env file is missing or not a regular file"
    return
  }
  [[ "$(stat -c '%a' "$production_env_file")" == "600" ]] || fail "production env file must have mode 0600"

  local key value cors_origin
  local -a cors_origins=()
  for key in MOBILE_API_SECRET MOBILE_API_ADMIN_USERNAME MOBILE_API_ADMIN_PASSWORD MOBILE_API_CORS_ORIGINS PUBLIC_DEPLOY; do
    value="$(production_env_value "$key")"
    [[ -n "$value" ]] || fail "production env file is missing a non-empty ${key}"
  done

  [[ "$(production_env_value PUBLIC_DEPLOY)" == "1" ]] || fail "PUBLIC_DEPLOY must be 1 in production mode"
  IFS=',' read -r -a cors_origins <<<"$(production_env_value MOBILE_API_CORS_ORIGINS)"
  for cors_origin in "${cors_origins[@]}"; do
    [[ "$cors_origin" =~ ^https://[^[:space:]/]+(:[0-9]+)?$ ]] || {
      fail "MOBILE_API_CORS_ORIGINS must contain HTTPS origins only"
      break
    }
  done
}

echo "Repository: $ROOT"
echo "Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

if "$PYTHON_BIN" - <<'PY'
import importlib

required = (
    "fastapi",
    "starlette",
    "pydantic",
    "uvicorn",
    "jose",
    "pyperclip",
    "pytest",
    "pyflakes",
    "ebooklib",
    "mutagen",
    "jieba",
    "edge_tts",
)
for module_name in required:
    importlib.import_module(module_name)

import app.mobile_api
PY
then
  ok "required Python imports and app.mobile_api"
else
  fail "required Python imports failed; recreate .venv from declared dependencies"
fi

if "$PYTHON_BIN" -m pip check; then
  ok "Python package consistency"
else
  fail "pip check reported an inconsistent environment"
fi

require_command node
require_command npm
require_command ffmpeg
require_command ffprobe

if [[ "$mode" == "production" ]]; then
  validate_production_env
  if (( failures == 0 )); then
    ok "external production environment file validated without reading secret values"
  fi
else
  if [[ -f "$ROOT/data/pipeline.db" ]]; then
    ok "database file present"
  else
    fail "data/pipeline.db is missing"
  fi

  for runtime_dir in "$ROOT/data" "$ROOT/data/logs"; do
    if [[ -d "$runtime_dir" && -w "$runtime_dir" ]]; then
      ok "runtime directory writable: ${runtime_dir#$ROOT/}"
    else
      fail "runtime directory missing or not writable: $runtime_dir"
    fi
  done
fi

if [[ -f "$ROOT/.env.example" ]]; then
  ok ".env.example present"
else
  fail ".env.example is missing"
fi

if [[ "$mode" == "development" && -f "$ROOT/.env" ]]; then
  if git check-ignore -q "$ROOT/.env"; then
    ok ".env present and ignored by Git"
  else
    fail ".env exists but is not ignored by Git"
  fi
  if cmp -s "$ROOT/.env" "$ROOT/.env.example"; then
    fail ".env.example must not duplicate the operator .env"
  else
    ok ".env.example differs from operator .env"
  fi
elif [[ "$mode" == "development" ]]; then
  fail ".env is missing; copy .env.example and set local credentials"
fi

if awk -F= '
  /^(GEMINI_API_KEY|DEEPSEEK_API_KEY|OPENROUTER_API_KEY|OPENAI_API_KEY|OLLAMA_API_KEY|CAPTCHA_API_KEY|PROXY_LIST)=/ {
    if (length($2) != 0) exit 1
  }
  /^MOBILE_API_(SECRET|ADMIN_PASSWORD)=/ {
    if ($2 !~ /^replace-with-/) exit 1
  }
' "$ROOT/.env.example"; then
  ok ".env.example uses safe secret placeholders"
else
  fail ".env.example contains a non-placeholder secret value"
fi

if [[ -f "$ROOT/web/package-lock.json" && -d "$ROOT/web/node_modules" ]]; then
  ok "frontend lockfile and installed dependencies present"
else
  fail "frontend dependencies are missing; run npm --prefix web ci"
fi

if (( failures > 0 )); then
  echo "Environment check failed with $failures error(s)." >&2
  exit 1
fi

echo "Environment check passed."
