from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_CONSUMER_SCRIPTS = (
    "backup-local.sh",
    "batch-local.sh",
    "lint.sh",
    "smoke-local.sh",
    "start-cloudflare.sh",
    "start-local.sh",
    "status-local.sh",
    "verify.sh",
)

ACTIVE_OPERATIONAL_FILES = (
    "deploy/systemd/novel-pipeline.service.example",
    "docs/backup-restore.md",
    "docs/deployment-hardening.md",
    "docs/local-development.md",
    "docs/operations/P5_RUNBOOK.md",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


def _script_test_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    """Provide inert commands while preserving the scripts' real process flow."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    invocation_log = tmp_path / "invocations.log"
    data_dir = tmp_path / "runtime-data"
    heartbeat = data_dir / "logs" / "runtime" / "import-worker.heartbeat"
    fresh_heartbeat = tmp_path / "worker-heartbeat-fresh"
    healthcheck_success = tmp_path / "worker-healthcheck-success"
    process_stopped = tmp_path / "process-stopped"
    bash_env = tmp_path / "bash-env"
    bash_env.write_text("enable -n kill\n", encoding="utf-8")
    _write_executable(
        bin_dir / "python",
        """#!/usr/bin/env bash
        set -euo pipefail
        printf 'python %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        if [[ "${1:-}" == "-c" ]]; then
          exit 0
        fi
        if [[ "${1:-}" == "-m" && "${2:-}" == "app.import_worker" ]]; then
          if [[ "${3:-}" == "--healthcheck" ]]; then
            [[ "${STUB_FAIL:-}" != "worker-health" ]] || exit 1
            if [[ -f "$STUB_HEARTBEAT" && -f "$STUB_WORKER_HEARTBEAT_FRESH" ]]; then
              printf 'worker-healthcheck ok\\n' >>"$STUB_INVOCATION_LOG"
              : >"$STUB_WORKER_HEALTHCHECK_SUCCESS"
              exit 0
            fi
            exit 1
          fi
          mkdir -p "$(dirname "$STUB_HEARTBEAT")"
          : >"$STUB_HEARTBEAT"
          : >"$STUB_WORKER_HEARTBEAT_FRESH"
          exit 0
        fi
        if [[ "${1:-}" == "scripts/ops.py" && "${2:-}" == "rotate-logs" ]]; then
          printf 'rotate-logs\\n' >>"$STUB_INVOCATION_LOG"
          if [[ -f "$STUB_RUNTIME_DIR/import-worker.log" ]]; then
            mv "$STUB_RUNTIME_DIR/import-worker.log" "$STUB_RUNTIME_DIR/import-worker.log.1"
          fi
          exit 0
        fi
        if [[ "${1:-}" == "scripts/ops.py" && "${2:-}" == "wait-health" ]]; then
          [[ "${STUB_FAIL:-}" != "api-readiness" ]] || exit 42
          if [[ " $* " == *" --timeout 2 "* && "${STUB_API_ALREADY_REACHABLE:-1}" == "0" ]]; then
            exit 1
          fi
          [[ -f "$STUB_WORKER_HEALTHCHECK_SUCCESS" ]] || exit 42
          exit 0
        fi
        exit 0
        """,
    )
    _write_executable(
        bin_dir / "setsid",
        """#!/usr/bin/env bash
        set -euo pipefail
        printf 'setsid %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        exec "$@"
        """,
    )
    _write_executable(
        bin_dir / "npm",
        """#!/usr/bin/env bash
        printf 'npm %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        """,
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
        printf 'curl %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        [[ "${STUB_FAIL:-}" != "curl" ]] || exit 43
        printf '<div id="root"></div>\\n'
        """,
    )
    _write_executable(
        bin_dir / "ss",
        """#!/usr/bin/env bash
        printf 'ss %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        """,
    )
    _write_executable(
        bin_dir / "kill",
        """#!/usr/bin/env bash
        set -euo pipefail
        target="${!#}"
        if [[ "$target" == -* ]]; then
          exit 1
        fi
        if [[ "${1:-}" == "-0" ]]; then
          if [[ "${STUB_ALLOW_DYNAMIC_PIDS:-0}" == "1" && ! -f "$STUB_PROCESS_STOPPED/$target" ]]; then
            exit 0
          fi
          [[ " $STUB_LIVE_PIDS " == *" $target "* && ! -f "$STUB_PROCESS_STOPPED/$target" ]]
          exit
        fi
        printf 'kill %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        mkdir -p "$STUB_PROCESS_STOPPED"
        : >"$STUB_PROCESS_STOPPED/$target"
        """,
    )
    env = {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "PYTHON_BIN": str(bin_dir / "python"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_HEARTBEAT": str(heartbeat),
        "STUB_WORKER_HEARTBEAT_FRESH": str(fresh_heartbeat),
        "STUB_WORKER_HEALTHCHECK_SUCCESS": str(healthcheck_success),
        "STUB_INVOCATION_LOG": str(invocation_log),
        "STUB_PROCESS_PID": "4103",
        "STUB_LIVE_PIDS": "4101 4102 4103",
        "STUB_PROCESS_STOPPED": str(process_stopped),
        "STUB_RUNTIME_DIR": str(data_dir / "logs" / "runtime"),
        "BASH_ENV": str(bash_env),
        "NOVEL_PIPELINE_IGNORE_DOTENV": "1",
    }
    return env, invocation_log, data_dir


def _run_script(script_name: str, env: dict[str, str], root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / script_name)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _copy_script_tree(tmp_path: Path) -> Path:
    copied_root = tmp_path / "poisoned-repository"
    copied_scripts = copied_root / "scripts"
    copied_scripts.mkdir(parents=True)
    for name in ("start-local.sh", "start-cloudflare.sh", "stop-local.sh", "status-local.sh"):
        shutil.copy2(ROOT / "scripts" / name, copied_scripts / name)
    shutil.copy2(ROOT / "scripts" / "lib" / "python.sh", copied_scripts / "python.sh")
    (copied_scripts / "lib").mkdir()
    shutil.copy2(ROOT / "scripts" / "lib" / "python.sh", copied_scripts / "lib" / "python.sh")
    (copied_root / "web").mkdir()
    return copied_root


def _seed_stale_heartbeat(data_dir: Path) -> None:
    heartbeat = data_dir / "logs" / "runtime" / "import-worker.heartbeat"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.touch()
    os.utime(heartbeat, (1, 1))


def test_local_start_launches_worker_before_waiting_for_api_readiness(tmp_path: Path) -> None:
    """A missing worker release must prevent the API from becoming ready."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    _seed_stale_heartbeat(data_dir)

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    runtime_dir = data_dir / "logs" / "runtime"
    assert (runtime_dir / "import-worker.pid").is_file()
    assert (runtime_dir / "import-worker.log").is_file()
    invocations = invocation_log.read_text(encoding="utf-8").splitlines()
    worker_start = next(
        index
        for index, line in enumerate(invocations)
        if line.startswith("setsid") and "app.import_worker" in line
    )
    readiness_wait = next(
        index
        for index, line in enumerate(invocations)
        if "scripts/ops.py wait-health" in line
    )
    healthcheck = next(index for index, line in enumerate(invocations) if line == "worker-healthcheck ok")
    assert worker_start < healthcheck < readiness_wait


def test_cloudflare_start_launches_the_same_worker_process(tmp_path: Path) -> None:
    """The public-local workflow must release the same dedicated worker first."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env["CLOUDFLARE_HOSTNAME"] = "local.example.test"
    _seed_stale_heartbeat(data_dir)

    result = _run_script("start-cloudflare.sh", env)

    assert result.returncode == 0, result.stderr
    runtime_dir = data_dir / "logs" / "runtime"
    assert (runtime_dir / "import-worker.pid").is_file()
    assert (runtime_dir / "import-worker.log").is_file()
    invocations = invocation_log.read_text(encoding="utf-8").splitlines()
    worker_start = next(
        index
        for index, line in enumerate(invocations)
        if line.startswith("setsid") and "app.import_worker" in line
    )
    readiness_wait = next(
        index
        for index, line in enumerate(invocations)
        if "scripts/ops.py wait-health" in line
    )
    healthcheck = next(index for index, line in enumerate(invocations) if line == "worker-healthcheck ok")
    assert worker_start < healthcheck < readiness_wait


def test_cloudflare_start_reuses_a_live_worker(tmp_path: Path) -> None:
    """Restarting the public-local API leaves a healthy worker process in place."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env["CLOUDFLARE_HOSTNAME"] = "local.example.test"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "import-worker.heartbeat").touch()
    Path(env["STUB_WORKER_HEARTBEAT_FRESH"]).touch()
    worker_pid_file = runtime_dir / "import-worker.pid"
    worker_pid_file.write_text(env["STUB_PROCESS_PID"], encoding="utf-8")

    result = _run_script("start-cloudflare.sh", env)

    assert result.returncode == 0, result.stderr
    assert not Path(env["STUB_PROCESS_STOPPED"]).exists()
    assert worker_pid_file.read_text(encoding="utf-8") == env["STUB_PROCESS_PID"]
    assert not any(
        line.startswith("setsid") and "app.import_worker" in line
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    )


def test_scripts_ignore_poisoned_repo_dotenv_when_requested(tmp_path: Path) -> None:
    """The test-only dotenv bypass keeps all script runtime state isolated."""

    env, _, data_dir = _script_test_environment(tmp_path)
    copied_root = _copy_script_tree(tmp_path)
    poison_dir = tmp_path / "operator-runtime"
    (copied_root / ".env").write_text(
        f"DATA_DIR={poison_dir}\nPYTHON_BIN=/operator/python\nPATH=/operator/bin\n",
        encoding="utf-8",
    )
    env["STUB_API_ALREADY_REACHABLE"] = "0"

    for script_name in ("start-local.sh", "status-local.sh", "stop-local.sh", "start-cloudflare.sh"):
        result = _run_script(script_name, env, copied_root)
        assert result.returncode == 0, result.stderr

    assert (data_dir / "logs" / "runtime" / "import-worker.log").is_file()
    assert not poison_dir.exists()


def test_fresh_start_rotates_before_opening_import_worker_log(tmp_path: Path) -> None:
    """Rotation must complete before a new worker opens its append-only log."""

    env, invocation_log, _ = _script_test_environment(tmp_path)
    env["STUB_API_ALREADY_REACHABLE"] = "0"

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    lines = invocation_log.read_text(encoding="utf-8").splitlines()
    assert lines.index("rotate-logs") < next(i for i, line in enumerate(lines) if line.startswith("setsid") and "app.import_worker" in line)


def test_reused_worker_log_is_not_rotated(tmp_path: Path) -> None:
    """A live worker retains its open log instead of being rotated underneath it."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env["CLOUDFLARE_HOSTNAME"] = "local.example.test"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "import-worker.heartbeat").touch()
    Path(env["STUB_WORKER_HEARTBEAT_FRESH"]).touch()
    (runtime_dir / "import-worker.log").write_text("worker output\n", encoding="utf-8")
    (runtime_dir / "import-worker.pid").write_text(env["STUB_PROCESS_PID"], encoding="utf-8")

    result = _run_script("start-cloudflare.sh", env)

    assert result.returncode == 0, result.stderr
    assert (runtime_dir / "import-worker.log").read_text(encoding="utf-8") == "worker output\n"
    assert not (runtime_dir / "import-worker.log.1").exists()
    assert "rotate-logs" not in invocation_log.read_text(encoding="utf-8").splitlines()


def test_failed_worker_health_cleans_only_the_new_worker(tmp_path: Path) -> None:
    """A worker-health failure removes the worker process and its PID file."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env.update({"STUB_FAIL": "worker-health", "IMPORT_WORKER_START_TIMEOUT": "0", "STUB_ALLOW_DYNAMIC_PIDS": "1"})

    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    assert not (data_dir / "logs" / "runtime" / "import-worker.pid").exists()
    assert any(line.startswith("kill ") for line in invocation_log.read_text(encoding="utf-8").splitlines())


def test_failed_api_readiness_cleans_new_api_and_worker(tmp_path: Path) -> None:
    """An API readiness failure cleans both processes created by this invocation."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env.update({"STUB_FAIL": "api-readiness", "STUB_ALLOW_DYNAMIC_PIDS": "1"})

    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    runtime_dir = data_dir / "logs" / "runtime"
    assert not (runtime_dir / "import-worker.pid").exists()
    assert not (runtime_dir / "mobile-api.pid").exists()
    assert len([line for line in invocation_log.read_text(encoding="utf-8").splitlines() if line.startswith("kill ")]) == 2


def test_cloudflare_failure_cleans_new_api_but_preserves_existing_worker(tmp_path: Path) -> None:
    """A later public-readiness failure cannot tear down a worker it did not start."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env.update({"CLOUDFLARE_HOSTNAME": "local.example.test", "STUB_FAIL": "curl", "STUB_ALLOW_DYNAMIC_PIDS": "1"})
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "import-worker.heartbeat").touch()
    Path(env["STUB_WORKER_HEARTBEAT_FRESH"]).touch()
    worker_pid = runtime_dir / "import-worker.pid"
    worker_pid.write_text(env["STUB_PROCESS_PID"], encoding="utf-8")

    result = _run_script("start-cloudflare.sh", env)

    assert result.returncode != 0
    assert worker_pid.read_text(encoding="utf-8") == env["STUB_PROCESS_PID"]
    assert not (runtime_dir / "mobile-api.pid").exists()
    assert f"kill {env['STUB_PROCESS_PID']}" not in invocation_log.read_text(encoding="utf-8")


def test_local_stop_and_status_manage_import_worker_pid(tmp_path: Path) -> None:
    """A managed worker PID is visible, health-checked, and terminated on stop."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "import-worker.heartbeat").touch()
    Path(env["STUB_WORKER_HEARTBEAT_FRESH"]).touch()
    (runtime_dir / "web-vite.pid").write_text("4101", encoding="utf-8")
    (runtime_dir / "mobile-api.pid").write_text("4102", encoding="utf-8")
    worker_pid_file = runtime_dir / "import-worker.pid"
    worker_pid_file.write_text(env["STUB_PROCESS_PID"], encoding="utf-8")

    status = _run_script("status-local.sh", env)
    assert status.returncode == 0, status.stderr
    assert f"Import worker running: pid {env['STUB_PROCESS_PID']}" in status.stdout
    assert "Import worker health: ok" in status.stdout
    assert any("-m app.import_worker --healthcheck" in line for line in invocation_log.read_text(encoding="utf-8").splitlines())

    stop = _run_script("stop-local.sh", env)
    assert stop.returncode == 0, stop.stderr
    assert not worker_pid_file.exists()
    stopped = Path(env["STUB_PROCESS_STOPPED"])
    assert all((stopped / pid).is_file() for pid in ("4101", "4102", "4103"))
    assert "Import worker stopped" in stop.stdout
    signals = [line for line in invocation_log.read_text(encoding="utf-8").splitlines() if line.startswith("kill ")]
    assert signals == ["kill 4101", "kill 4102", "kill 4103"]


def test_python_resolver_rejects_missing_explicit_interpreter(tmp_path: Path) -> None:
    missing_python = tmp_path / "missing-python"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source scripts/lib/python.sh; resolve_python_bin "$PWD"',
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHON_BIN": str(missing_python)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert str(missing_python) in result.stderr
    assert result.stdout == ""


def test_python_scripts_share_the_strict_resolver() -> None:
    for script_name in PYTHON_CONSUMER_SCRIPTS:
        content = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert 'source "$ROOT/scripts/lib/python.sh"' in content or 'source "$ROOT_DIR/scripts/lib/python.sh"' in content
        assert "PYTHON_BIN_FALLBACK" not in content


def test_scripts_do_not_reference_the_old_repository_root() -> None:
    for script in (ROOT / "scripts").glob("*"):
        if not script.is_file():
            continue
        assert "/home/thenam176/novel_pipeline" not in script.read_text(encoding="utf-8")


def test_active_operational_files_do_not_reference_the_old_repository_root() -> None:
    for relative_path in ACTIVE_OPERATIONAL_FILES:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "/home/thenam176/novel_pipeline" not in content, relative_path


def test_systemd_example_uses_deploy_placeholders_not_personal_paths() -> None:
    content = (ROOT / "deploy/systemd/novel-pipeline.service.example").read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/novel-tnn" in content
    assert "Environment=DATA_DIR=/var/lib/novel-tnn" in content


def test_env_example_uses_only_safe_secret_placeholders() -> None:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

    for key in (
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_API_KEY",
        "CAPTCHA_API_KEY",
        "PROXY_LIST",
    ):
        assert values[key] == ""

    assert values["MOBILE_API_SECRET"].startswith("replace-with-")
    assert values["MOBILE_API_ADMIN_PASSWORD"].startswith("replace-with-")
    assert values["PUBLIC_DEPLOY"] == "0"


def test_dependency_manifests_keep_passlib_on_compatible_bcrypt() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert '"bcrypt>=4.0,<4.1"' in pyproject
    assert "bcrypt>=4.0,<4.1" in requirements.splitlines()


def test_pytest_session_uses_an_isolated_data_directory() -> None:
    configured_data_dir = Path(os.environ["DATA_DIR"]).resolve()

    assert configured_data_dir != (ROOT / "data").resolve()
    assert configured_data_dir.name.startswith("novel-tnn-pytest-")


def test_verify_script_propagates_an_injected_mandatory_gate_failure() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify.sh"), "--self-test-failure"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FAIL: injected mandatory gate" in result.stdout
    assert "compileall" not in result.stdout


def test_verify_script_fails_closed_when_chromium_binary_is_missing() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify.sh"), "--self-test-missing-browser"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FAIL: browser E2E browser availability" in result.stdout
    assert "Playwright Chromium binary is missing or not executable" in result.stderr
    assert "backend tests" not in result.stdout


def test_verify_script_keeps_browser_e2e_behind_explicit_opt_in() -> None:
    content = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")

    assert '"${1:-}" == "--with-e2e"' in content
    assert 'run_mandatory_gate "browser E2E browser availability"' in content
    assert 'run_mandatory_gate "browser E2E tests" npm --prefix web run test:e2e -- --project=chromium' in content
    assert content.index('run_mandatory_gate "frontend tests" npm --prefix web test') < content.index(
        'run_mandatory_gate "frontend build" npm --prefix web run build'
    )


def test_ci_python_job_provisions_project_runtime_dependencies() -> None:
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    python_job = content.split("  frontend:", maxsplit=1)[0]

    assert "sudo apt-get install -y ffmpeg" in python_job
    assert "python -m venv .venv" in python_job
    assert '.venv/bin/python -m pip install -r requirements.txt' in python_job
    assert '.venv/bin/python -m pip install -e ".[dev]"' in python_job
    assert "npm --prefix web ci" in python_job
    assert ".venv/bin/python -m pytest -q -s" in python_job


def test_ci_docker_smoke_uses_safe_public_runtime_configuration() -> None:
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    docker_job = content.split("  docker:", maxsplit=1)[1]

    assert "-e PUBLIC_DEPLOY=1" in docker_job
    assert "-e MOBILE_API_ADMIN_USERNAME=ci-operator" in docker_job
    assert "-e MOBILE_API_CORS_ORIGINS=https://ci.example.test" in docker_job
    assert "-e MOBILE_API_SECRET=ci-only-not-a-real-secret-000000000000" in docker_job
    assert "-e MOBILE_API_ADMIN_PASSWORD=ci-only-not-a-real-password" in docker_job
    assert "docker logs novel-pipeline-ci || true" in docker_job


def test_ci_installs_caches_and_runs_playwright_without_changing_existing_frontend_gates() -> None:
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uses: actions/cache@v4" in content
    assert "path: ~/.cache/ms-playwright" in content
    assert "runner.os }}-${{ runner.arch }}-playwright-${{ hashFiles('web/package-lock.json')" in content
    assert "restore-keys:" not in content
    assert "npm --prefix web exec -- playwright install --with-deps chromium" in content
    assert "npm --prefix web run test:e2e -- --project=chromium" in content
    assert content.index("run: npm --prefix web test") < content.index("run: npm --prefix web run build")
