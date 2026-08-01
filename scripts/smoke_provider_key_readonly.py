#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import requests


PROVIDER_ID = "gemini"
UNRELATED_PROVIDER_ID = "openrouter"
PROVIDER_ENV_NAME = "GEMINI_API_KEY"
UNRELATED_PROVIDER_ENV_NAME = "OPENROUTER_API_KEY"
STORE_PATH = "/data/secrets/provider-keys.json"
PROJECT_ENV_PATH = "/app/.env"
DISPOSABLE_LABEL = "com.novel-tnn.pr3-disposable"
EXPECTED_CONTAINER_USER = "10001:10001"


class SmokeFailure(RuntimeError):
    pass


@dataclass
class Evidence:
    response_surfaces: list[bytes] = field(default_factory=list)

    def record(self, response: requests.Response) -> None:
        self.response_surfaces.append(response.content)
        self.response_surfaces.append(
            json.dumps(dict(response.headers), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )


def _docker_capture(
    *arguments: str,
    stdin: bytes | None = None,
    timeout_seconds: int = 120,
) -> bytes:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure("Docker operation timed out") from exc
    if result.returncode != 0:
        raise SmokeFailure("Docker operation failed")
    return result.stdout


def _docker_capture_streams(*arguments: str) -> tuple[bytes, bytes]:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure("Docker operation timed out") from exc
    if result.returncode != 0:
        raise SmokeFailure("Docker operation failed")
    return result.stdout, result.stderr


def _docker_format(container: str, expression: str) -> bytes:
    return _docker_capture("inspect", "--format", expression, container).strip()


def _inspect_json(container: str, expression: str) -> Any:
    output = _docker_format(container, expression)
    try:
        return json.loads(output.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("Docker inspection returned malformed output") from exc


def _published_base_url(container: str) -> str:
    bindings = _inspect_json(container, '{{json (index .NetworkSettings.Ports "7860/tcp")}}')
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise SmokeFailure("Container must have one unambiguous API port binding")
    binding = bindings[0]
    if binding.get("HostIp") not in {"127.0.0.1", "::1"}:
        raise SmokeFailure("Container API port is not loopback-bound")
    host_port = str(binding.get("HostPort") or "")
    if not host_port.isdigit():
        raise SmokeFailure("Container API port binding is invalid")
    return f"http://127.0.0.1:{host_port}"


def _validate_disposable_container(container: str, expected_image: str) -> str:
    labels = _inspect_json(container, "{{json .Config.Labels}}")
    if not isinstance(labels, dict) or labels.get(DISPOSABLE_LABEL) != "true":
        raise SmokeFailure("Refusing container without disposable PR-3 label")
    if _docker_format(container, "{{json .HostConfig.ReadonlyRootfs}}") != b"true":
        raise SmokeFailure("Container root filesystem is not read-only")
    if _docker_format(container, "{{.Config.User}}").decode("utf-8") != EXPECTED_CONTAINER_USER:
        raise SmokeFailure("Container user does not match production contract")

    expected_image_id = _docker_capture("image", "inspect", "--format", "{{.Id}}", expected_image).strip()
    container_image_id = _docker_format(container, "{{.Image}}")
    if not expected_image_id or not secrets.compare_digest(expected_image_id, container_image_id):
        raise SmokeFailure("Container does not use the freshly selected image")

    mounts = _inspect_json(container, "{{json .Mounts}}")
    if not isinstance(mounts, list):
        raise SmokeFailure("Container mount inspection failed")
    data_mount = next((item for item in mounts if item.get("Destination") == "/data"), None)
    secret_mount = next((item for item in mounts if item.get("Destination") == "/data/secrets"), None)
    if not isinstance(data_mount, dict) or not data_mount.get("RW"):
        raise SmokeFailure("Writable data mount is missing")
    if not isinstance(secret_mount, dict) or not secret_mount.get("RW"):
        raise SmokeFailure("API-only credential mount is missing")
    if data_mount.get("Type") != "volume" or secret_mount.get("Type") != "volume":
        raise SmokeFailure("Disposable runtime storage must use Docker volumes")
    if data_mount.get("Source") == secret_mount.get("Source"):
        raise SmokeFailure("Credential and data mounts are not isolated")
    return _published_base_url(container)


def _request_json(
    method: str,
    url: str,
    *,
    evidence: Evidence,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    try:
        response = requests.request(method, url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        raise SmokeFailure("API request failed") from exc
    evidence.record(response)
    if response.status_code != expected_status:
        route = urlsplit(url).path
        raise SmokeFailure(f"API returned status {response.status_code} at {method} {route}")
    try:
        data = response.json()
    except ValueError as exc:
        raise SmokeFailure("API returned malformed JSON") from exc
    if not isinstance(data, dict):
        raise SmokeFailure("API returned unexpected payload shape")
    return data


def _wait_ready(base_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api/ready", timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise SmokeFailure("Container did not become ready after restart")


def _login(base_url: str, evidence: Evidence, username: str, password: str) -> dict[str, str]:
    payload = _request_json(
        "POST",
        f"{base_url}/api/auth/login",
        evidence=evidence,
        payload={"username": username, "password": password},
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SmokeFailure("Login response omitted access token")
    return {"Authorization": f"Bearer {token}"}


def _restart_and_login(
    container: str,
    base_url: str,
    evidence: Evidence,
    username: str,
    password: str,
) -> tuple[dict[str, str], str]:
    _docker_capture("restart", container)
    base_url = _published_base_url(container)
    _wait_ready(base_url)
    return _login(base_url, evidence, username, password), base_url


def _container_probe(container: str, payload: dict[str, Any]) -> dict[str, Any]:
    script = r'''
import json, os, stat, sys
request = json.load(sys.stdin)
path = request["path"]
result = {"exists": os.path.exists(path), "ok": True}
if result["exists"]:
    st = os.stat(path, follow_symlinks=False)
    result["regular"] = stat.S_ISREG(st.st_mode)
    result["mode"] = stat.S_IMODE(st.st_mode)
    try:
        doc = json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        result["ok"] = False
    else:
        result["version"] = doc.get("version") if isinstance(doc, dict) else None
        keys = doc.get("keys") if isinstance(doc, dict) else None
        deleted = doc.get("deleted") if isinstance(doc, dict) else None
        result["keys_shape"] = isinstance(keys, dict)
        result["deleted_shape"] = isinstance(deleted, list)
        result["expected_match"] = bool(
            isinstance(keys, dict)
            and all(keys.get(name) == value for name, value in request.get("expected", {}).items())
        )
        rendered = json.dumps(doc, sort_keys=True, separators=(",", ":"))
        result["forbidden_absent"] = all(value not in rendered for value in request.get("forbidden", []))
        result["tombstones_match"] = bool(
            isinstance(deleted, list)
            and all(name in deleted for name in request.get("tombstones", []))
        )
        result["absent_names"] = bool(
            isinstance(keys, dict)
            and all(name not in keys for name in request.get("absent_names", []))
        )
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''
    output = _docker_capture(
        "exec",
        "-i",
        container,
        "python",
        "-c",
        script,
        stdin=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("Container verifier returned malformed output") from exc
    if not isinstance(result, dict):
        raise SmokeFailure("Container verifier returned unexpected output")
    return result


def _assert_store(
    container: str,
    *,
    expected: dict[str, str],
    forbidden: list[str],
    tombstones: list[str] | None = None,
    absent_names: list[str] | None = None,
) -> None:
    result = _container_probe(
        container,
        {
            "path": STORE_PATH,
            "expected": expected,
            "forbidden": forbidden,
            "tombstones": tombstones or [],
            "absent_names": absent_names or [],
        },
    )
    required = {
        "exists": True,
        "regular": True,
        "mode": 0o600,
        "version": 2,
        "keys_shape": True,
        "deleted_shape": True,
        "expected_match": True,
        "forbidden_absent": True,
        "tombstones_match": True,
        "absent_names": True,
    }
    if any(result.get(name) != value for name, value in required.items()):
        raise SmokeFailure("Provider secret store lifecycle evidence was invalid")


def _project_env_fingerprint(container: str) -> dict[str, Any]:
    script = (
        "import hashlib,json,os;"
        f"p='{PROJECT_ENV_PATH}';"
        "print(json.dumps({'exists':os.path.exists(p),'digest':"
        "hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.exists(p) else ''},"
        "sort_keys=True,separators=(',',':')))"
    )
    output = _docker_capture("exec", container, "python", "-c", script)
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("Project environment fingerprint failed") from exc
    if not isinstance(result, dict):
        raise SmokeFailure("Project environment fingerprint was invalid")
    return result


def _provider(payload: dict[str, Any], provider_id: str) -> dict[str, Any]:
    provider = payload.get("provider")
    if not isinstance(provider, dict) or provider.get("id") != provider_id:
        raise SmokeFailure("Provider response shape was invalid")
    return provider


def _listed_provider(payload: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise SmokeFailure("Provider list response shape was invalid")
    for item in providers:
        if isinstance(item, dict) and item.get("id") == provider_id:
            return item
    raise SmokeFailure("Provider was absent from provider list")


def _assert_provider_state(
    base_url: str,
    headers: dict[str, str],
    evidence: Evidence,
    provider_id: str,
    configured: bool,
) -> None:
    listed = _request_json(
        "GET",
        f"{base_url}/api/providers",
        evidence=evidence,
        headers=headers,
    )
    if _listed_provider(listed, provider_id).get("api_key_set") is not configured:
        raise SmokeFailure("Provider configured status did not survive restart")


def _stop_disposable_container(container: str) -> None:
    _docker_capture("stop", "--time", "10", container)
    if _docker_format(container, "{{.State.Status}}") != b"exited":
        raise SmokeFailure("Disposable API did not stop before volume scan")


def _remove_scan_container(container: str) -> None:
    for _attempt in range(3):
        try:
            subprocess.run(
                ["docker", "rm", "--force", container],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        try:
            remaining = subprocess.run(
                [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    f"name=^/{container}$",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if remaining.returncode == 0 and not remaining.stdout.strip():
            return
    raise SmokeFailure("Scanner container cleanup could not be confirmed")


def _assert_exclusive_volume_user(container: str, volume: str) -> None:
    expected_id = _docker_format(container, "{{.Id}}")
    users = {
        item.strip()
        for item in _docker_capture(
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"volume={volume}",
        ).splitlines()
        if item.strip()
    }
    if users != {expected_id}:
        raise SmokeFailure("Disposable runtime volume has an unexpected user")


def _scan_stopped_container_files(container: str, expected_image: str, values: list[str]) -> None:
    mounts = _inspect_json(container, "{{json .Mounts}}")
    if not isinstance(mounts, list):
        raise SmokeFailure("Container mount inspection failed")
    data_mount = next((item for item in mounts if item.get("Destination") == "/data"), None)
    secret_mount = next((item for item in mounts if item.get("Destination") == "/data/secrets"), None)
    if not isinstance(data_mount, dict) or not isinstance(secret_mount, dict):
        raise SmokeFailure("Disposable runtime volumes are missing")
    data_source = str(data_mount.get("Name") or "")
    secret_source = str(secret_mount.get("Name") or "")
    if not data_source or not secret_source or data_source == secret_source:
        raise SmokeFailure("Disposable runtime volume identity is invalid")
    _assert_exclusive_volume_user(container, data_source)
    _assert_exclusive_volume_user(container, secret_source)

    script = r'''
import json, os, stat, sys
request = json.load(sys.stdin)
needles = [value.encode("utf-8") for value in request["values"]]
overlap = max((len(needle) for needle in needles), default=1) - 1
leaks = 0
files = 0
errors = 0
for root in ("/scan/data", "/scan/provider-secrets"):
    walk_errors = []
    for current, dirs, names in os.walk(root, followlinks=False, onerror=walk_errors.append):
        retained_dirs = []
        for name in dirs:
            path = os.path.join(current, name)
            try:
                if stat.S_ISLNK(os.lstat(path).st_mode):
                    errors += 1
                else:
                    retained_dirs.append(name)
            except OSError:
                errors += 1
        dirs[:] = retained_dirs
        for name in names:
            path = os.path.join(current, name)
            descriptor = -1
            try:
                descriptor = os.open(
                    path,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW,
                )
                source_stat = os.fstat(descriptor)
                if not stat.S_ISREG(source_stat.st_mode):
                    errors += 1
                    continue
                with os.fdopen(descriptor, "rb", closefd=True) as handle:
                    descriptor = -1
                    tail = b""
                    leaked = False
                    remaining = source_stat.st_size
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            errors += 1
                            break
                        remaining -= len(chunk)
                        content = tail + chunk
                        if any(needle in content for needle in needles):
                            leaked = True
                            break
                        tail = content[-overlap:] if overlap else b""
            except (OSError, ValueError):
                errors += 1
                continue
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            files += 1
            if leaked:
                leaks += 1
    errors += len(walk_errors)
print(json.dumps({"files_scanned":files,"leaks":leaks,"errors":errors},separators=(",", ":")))
'''
    scan_container = f"novel-pr3-scan-{secrets.token_hex(8)}"
    output = b""
    scan_failure: BaseException | None = None
    cleanup_failure: SmokeFailure | None = None
    try:
        output = _docker_capture(
        "run",
        "--name",
        scan_container,
        "--interactive",
        "--label",
        f"{DISPOSABLE_LABEL}=true",
        "--read-only",
        "--user",
        EXPECTED_CONTAINER_USER,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--mount",
        f"type=volume,source={data_source},target=/scan/data,readonly",
        "--mount",
        f"type=volume,source={secret_source},target=/scan/provider-secrets,readonly",
        "--entrypoint",
        "python",
        expected_image,
        "-c",
        script,
        stdin=json.dumps({"values": values}, separators=(",", ":")).encode("utf-8"),
        timeout_seconds=120,
        )
    except BaseException as exc:
        scan_failure = exc
    try:
        _remove_scan_container(scan_container)
    except SmokeFailure as exc:
        cleanup_failure = exc
    if scan_failure is not None:
        if cleanup_failure is not None:
            raise SmokeFailure("Scanner failed and cleanup could not be confirmed") from scan_failure
        raise scan_failure
    if cleanup_failure is not None:
        raise cleanup_failure
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("Container leak scan returned malformed output") from exc
    if not isinstance(result, dict):
        raise SmokeFailure("Synthetic provider key remained in runtime data")
    files_scanned = result.get("files_scanned")
    if (
        result.get("leaks") != 0
        or result.get("errors") != 0
        or not isinstance(files_scanned, int)
        or files_scanned < 1
    ):
        raise SmokeFailure("Synthetic provider key remained in runtime data")


def run(container: str, expected_image: str) -> None:
    username = os.environ.get("SMOKE_PROVIDER_ADMIN_USERNAME", "").strip()
    password = os.environ.get("SMOKE_PROVIDER_ADMIN_PASSWORD", "")
    baseline = os.environ.get("SMOKE_PROVIDER_BASELINE_KEY", "")
    if not username or not password or not baseline:
        raise SmokeFailure("Synthetic smoke authentication environment is missing")

    base_url = _validate_disposable_container(container, expected_image)
    preexisting = _container_probe(
        container,
        {"path": STORE_PATH, "expected": {}, "forbidden": [], "tombstones": [], "absent_names": []},
    )
    if preexisting.get("exists"):
        raise SmokeFailure("Refusing container with pre-existing managed secret-store state")

    evidence = Evidence()
    first = secrets.token_urlsafe(32)
    second = secrets.token_urlsafe(32)
    unrelated = secrets.token_urlsafe(32)
    values = [baseline, first, second, unrelated]
    if len(set(values)) != len(values):
        raise SmokeFailure("Synthetic lifecycle values were not unique")

    before_env = _project_env_fingerprint(container)
    _wait_ready(base_url)
    headers = _login(base_url, evidence, username, password)

    unrelated_saved = _request_json(
        "POST",
        f"{base_url}/api/providers/{UNRELATED_PROVIDER_ID}/key",
        evidence=evidence,
        headers=headers,
        payload={"api_key": unrelated},
    )
    if _provider(unrelated_saved, UNRELATED_PROVIDER_ID).get("api_key_set") is not True:
        raise SmokeFailure("Unrelated provider setup failed")

    saved = _request_json(
        "POST",
        f"{base_url}/api/providers/{PROVIDER_ID}/key",
        evidence=evidence,
        headers=headers,
        payload={"api_key": first},
    )
    if _provider(saved, PROVIDER_ID).get("api_key_set") is not True:
        raise SmokeFailure("Save did not mark provider key configured")
    headers, base_url = _restart_and_login(container, base_url, evidence, username, password)
    _assert_provider_state(base_url, headers, evidence, PROVIDER_ID, True)
    _assert_store(
        container,
        expected={PROVIDER_ENV_NAME: first, UNRELATED_PROVIDER_ENV_NAME: unrelated},
        forbidden=[baseline, second],
    )
    print("PROVIDER_KEY_SAVE_RESTART=PASS")

    replaced = _request_json(
        "POST",
        f"{base_url}/api/providers/{PROVIDER_ID}/key",
        evidence=evidence,
        headers=headers,
        payload={"api_key": second},
    )
    if _provider(replaced, PROVIDER_ID).get("api_key_set") is not True:
        raise SmokeFailure("Replace did not keep provider key configured")
    headers, base_url = _restart_and_login(container, base_url, evidence, username, password)
    _assert_provider_state(base_url, headers, evidence, PROVIDER_ID, True)
    _assert_store(
        container,
        expected={PROVIDER_ENV_NAME: second, UNRELATED_PROVIDER_ENV_NAME: unrelated},
        forbidden=[baseline, first],
    )
    print("PROVIDER_KEY_REPLACE_RESTART=PASS")

    deleted = _request_json(
        "DELETE",
        f"{base_url}/api/providers/{PROVIDER_ID}/key",
        evidence=evidence,
        headers=headers,
    )
    if _provider(deleted, PROVIDER_ID).get("api_key_set") is not False:
        raise SmokeFailure("Delete did not clear provider key state")
    headers, base_url = _restart_and_login(container, base_url, evidence, username, password)
    _assert_provider_state(base_url, headers, evidence, PROVIDER_ID, False)
    _assert_provider_state(base_url, headers, evidence, UNRELATED_PROVIDER_ID, True)
    _assert_store(
        container,
        expected={UNRELATED_PROVIDER_ENV_NAME: unrelated},
        forbidden=[baseline, first, second],
        tombstones=[PROVIDER_ENV_NAME],
        absent_names=[PROVIDER_ENV_NAME],
    )
    print("PROVIDER_KEY_DELETE_RESTART=PASS")

    unrelated_deleted = _request_json(
        "DELETE",
        f"{base_url}/api/providers/{UNRELATED_PROVIDER_ID}/key",
        evidence=evidence,
        headers=headers,
    )
    if _provider(unrelated_deleted, UNRELATED_PROVIDER_ID).get("api_key_set") is not False:
        raise SmokeFailure("Unrelated provider cleanup failed")
    _assert_store(
        container,
        expected={},
        forbidden=values,
        tombstones=[PROVIDER_ENV_NAME, UNRELATED_PROVIDER_ENV_NAME],
        absent_names=[PROVIDER_ENV_NAME, UNRELATED_PROVIDER_ENV_NAME],
    )

    after_env = _project_env_fingerprint(container)
    if before_env != after_env:
        raise SmokeFailure("Project environment file changed during lifecycle")

    _stop_disposable_container(container)
    docker_stdout, docker_stderr = _docker_capture_streams("logs", container)
    docker_logs = docker_stdout + b"\n" + docker_stderr
    _scan_stopped_container_files(container, expected_image, values)
    response_surfaces = b"\n".join(evidence.response_surfaces)
    for value in values:
        encoded = value.encode("utf-8")
        if encoded in docker_logs or encoded in response_surfaces:
            raise SmokeFailure("Synthetic provider key was exposed")

    print("PROVIDER_KEY_NO_LEAK=PASS")
    print("PROVIDER_KEY_READONLY_LIFECYCLE=PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify provider-key lifecycle on an exact disposable image")
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-image", required=True)
    arguments = parser.parse_args()
    try:
        run(arguments.container, arguments.expected_image)
    except SmokeFailure as exc:
        print(f"PROVIDER_KEY_READONLY_LIFECYCLE=FAIL reason={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
