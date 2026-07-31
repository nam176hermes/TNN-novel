#!/usr/bin/env python3
"""Verify the deployed API/worker container hardening contract.

The checker intentionally reads only non-secret ``docker inspect`` fields.  It
can also consume a saved inspect JSON document, which keeps the contract fully
testable without access to the Docker daemon.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONTAINERS = ("novel-tnn-wsl-api-1", "novel-tnn-wsl-import-worker-1")
MINIMUMS = {
    "api": {"memory": 768 * 1024 * 1024, "nano_cpus": 1_000_000_000, "pids": 256},
    "import-worker": {"memory": 1536 * 1024 * 1024, "nano_cpus": 2_000_000_000, "pids": 384},
}


def _component(container: dict[str, Any]) -> str:
    labels = (container.get("Config") or {}).get("Labels") or {}
    service = str(labels.get("com.docker.compose.service") or "").strip()
    if service in MINIMUMS:
        return service
    name = str(container.get("Name") or "").lstrip("/")
    return "import-worker" if "worker" in name else "api"


def validate_container(container: dict[str, Any]) -> list[str]:
    component = _component(container)
    limits = MINIMUMS[component]
    config = container.get("Config") or {}
    host = container.get("HostConfig") or {}
    errors: list[str] = []

    user = str(config.get("User") or "").strip().lower()
    if user in {"", "0", "root"}:
        errors.append("container must run as a non-root user")
    if host.get("ReadonlyRootfs") is not True:
        errors.append("root filesystem must be read-only")
    if "ALL" not in (host.get("CapDrop") or []):
        errors.append("all Linux capabilities must be dropped")
    security_options = {str(value).lower() for value in (host.get("SecurityOpt") or [])}
    if not any(value.startswith("no-new-privileges") for value in security_options):
        errors.append("no-new-privileges must be enabled")
    if int(host.get("PidsLimit") or 0) < limits["pids"]:
        errors.append(f"PID limit must be at least {limits['pids']}")
    if int(host.get("Memory") or 0) < limits["memory"]:
        errors.append(f"memory limit must be at least {limits['memory']} bytes")
    if int(host.get("NanoCpus") or 0) < limits["nano_cpus"]:
        errors.append(f"CPU limit must be at least {limits['nano_cpus']} nanocpus")
    if str((host.get("RestartPolicy") or {}).get("Name") or "") != "unless-stopped":
        errors.append("restart policy must be unless-stopped")
    if not (config.get("Healthcheck") or {}).get("Test"):
        errors.append("container healthcheck is required")
    return errors


def _load_inspect(path: Path | None, containers: list[str]) -> list[dict[str, Any]]:
    if path is not None:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        completed = subprocess.run(
            ["docker", "inspect", *containers],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("docker inspect failed; verify the requested containers are running")
        payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or not payload:
        raise ValueError("inspect input must contain at least one container")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-json", type=Path, help="validate a saved docker inspect JSON document")
    parser.add_argument("containers", nargs="*", default=list(DEFAULT_CONTAINERS))
    args = parser.parse_args(argv)
    try:
        inspected = _load_inspect(args.inspect_json, args.containers)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"runtime contract check failed: {exc}", file=sys.stderr)
        return 2

    failed = False
    for container in inspected:
        component = _component(container)
        errors = validate_container(container)
        if errors:
            failed = True
            print(f"FAIL {component}: {'; '.join(errors)}")
        else:
            print(f"PASS {component}: runtime hardening contract satisfied")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
