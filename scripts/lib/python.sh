#!/usr/bin/env bash

resolve_python_bin() {
  local root="$1"
  local candidate="${PYTHON_BIN:-$root/.venv/bin/python}"

  if [[ ! -x "$candidate" ]]; then
    echo "Project Python is missing or not executable: $candidate" >&2
    echo "Create it with: python3.11 -m venv $root/.venv" >&2
    return 2
  fi

  if ! "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' >/dev/null 2>&1; then
    echo "Project Python must be Python 3.11: $candidate" >&2
    return 2
  fi

  printf '%s\n' "$candidate"
}
