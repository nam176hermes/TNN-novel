from __future__ import annotations

import os
import shlex
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
    group_signalled = tmp_path / "group-signalled"
    group_probed = tmp_path / "group-probed"
    kill_log = tmp_path / "kill.log"
    process_map = tmp_path / "process-map.log"
    readiness_log = tmp_path / "readiness.log"
    api_became_ready = tmp_path / "api-became-ready"
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        "enable -n kill\n"
        'if [[ "${STUB_FAIL_FINAL_OUTPUT:-0}" == "1" ]]; then enable -n echo; fi\n',
        encoding="utf-8",
    )
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
          if [[ "${STUB_RECORD_DIRECT_LAUNCHES:-0}" == "1" ]]; then
            printf 'worker %s\\n' "$BASHPID" >>"$STUB_PROCESS_MAP"
          fi
          mkdir -p "$(dirname "$STUB_HEARTBEAT")"
          : >"$STUB_HEARTBEAT"
          : >"$STUB_WORKER_HEARTBEAT_FRESH"
          if [[ "${STUB_API_BECOMES_READY_WITH_WORKER:-0}" == "1" ]]; then
            : >"$STUB_API_BECAME_READY"
          fi
          exit 0
        fi
        if [[ "${1:-}" == "-m" && "${2:-}" == "app.mobile_api" ]]; then
          if [[ "${STUB_RECORD_DIRECT_LAUNCHES:-0}" == "1" ]]; then
            printf 'api %s\\n' "$BASHPID" >>"$STUB_PROCESS_MAP"
          fi
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
          if [[ "${STUB_FAIL:-}" == "api-readiness" ]]; then
            if [[ -n "${STUB_REPLACE_PID_FILE:-}" ]]; then printf '%s' "$STUB_REPLACEMENT_PID" >"$STUB_REPLACE_PID_FILE"; fi
            exit 42
          fi
          if [[ ! -f "$STUB_WORKER_HEALTHCHECK_SUCCESS" ]]; then
            printf 'api-ready blocked\n' >>"$STUB_READINESS_LOG"
            exit 42
          fi
          if [[ "${STUB_PREEXISTING_API:-0}" != "1" \
                && ! -f "$STUB_API_BECAME_READY" \
                && ! -f "$STUB_RUNTIME_DIR/mobile-api.pid" ]]; then
            printf 'api-ready unavailable\n' >>"$STUB_READINESS_LOG"
            exit 1
          fi
          printf 'api-ready ok\n' >>"$STUB_READINESS_LOG"
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
        label=unknown
        if [[ " $* " == *" app.import_worker "* ]]; then label=worker; fi
        if [[ " $* " == *" app.mobile_api "* ]]; then label=api; fi
        if [[ " $* " == *" npm "* || "${1:-}" == "npm" ]]; then label=web; fi
        printf '%s %s\\n' "$label" "$BASHPID" >>"$STUB_PROCESS_MAP"
        exec "$@"
        """,
    )
    _write_executable(
        bin_dir / "npm",
        """#!/usr/bin/env bash
        printf 'npm %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        if [[ "${STUB_RECORD_DIRECT_LAUNCHES:-0}" == "1" && " $* " == *" run dev "* ]]; then
          printf 'web %s\\n' "$BASHPID" >>"$STUB_PROCESS_MAP"
        fi
        """,
    )
    _write_executable(
        bin_dir / "echo",
        """#!/usr/bin/env bash
        set -euo pipefail
        if [[ "${STUB_FAIL_FINAL_OUTPUT:-0}" == "1" && "${1:-}" == API:* ]]; then
          for _ in {1..100}; do
            grep -q '^web ' "$STUB_PROCESS_MAP" 2>/dev/null && break
            sleep 0.01
          done
          if [[ -n "${STUB_REPLACE_PID_FILE:-}" ]]; then
            printf '%s' "$STUB_REPLACEMENT_PID" >"$STUB_REPLACE_PID_FILE"
          fi
          exit 70
        fi
        printf '%s\\n' "$*"
        """,
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
        printf 'curl %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        if [[ "$*" == *"/api/health"* ]]; then
          if [[ "${STUB_PREEXISTING_API:-0}" == "1" ]]; then
            printf 'api-health ok\\n' >>"$STUB_READINESS_LOG"
            if [[ ! -f "$STUB_WORKER_HEALTHCHECK_SUCCESS" ]]; then
              printf 'api-ready blocked\\n' >>"$STUB_READINESS_LOG"
            fi
            exit 0
          fi
          printf 'api-health unavailable\\n' >>"$STUB_READINESS_LOG"
          exit 1
        fi
        [[ "${STUB_PREEXISTING_WEB:-1}" == "1" ]] || exit 1
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
        normalized_target="${target#-}"
        if [[ "${1:-}" == "-0" ]]; then
          state=stopped
          if [[ "$target" == -* && "${STUB_NO_PROCESS_GROUPS:-0}" == "1" ]]; then
            state=stopped
          elif [[ "${STUB_ALLOW_DYNAMIC_PIDS:-0}" == "1" && ! -f "$STUB_PROCESS_STOPPED/$normalized_target" ]]; then
            state=alive
          elif [[ " $STUB_LIVE_PIDS " == *" $normalized_target "* && ! -f "$STUB_PROCESS_STOPPED/$normalized_target" ]]; then
            state=alive
          fi
          if [[ "$target" == -* \
                && "${STUB_DELAY_GROUP_FORMATION:-0}" == "1" \
                && ! -f "$STUB_GROUP_SIGNALLED/$normalized_target" ]]; then
            mkdir -p "$STUB_GROUP_PROBED" "$STUB_GROUP_SIGNALLED"
            if [[ ! -f "$STUB_GROUP_PROBED/$normalized_target" ]]; then
              : >"$STUB_GROUP_PROBED/$normalized_target"
              state=stopped
            else
              : >"$STUB_GROUP_SIGNALLED/$normalized_target"
            fi
          fi
          printf 'poll %s %s\\n' "$state" "$target" >>"$STUB_KILL_LOG"
          [[ "$state" == alive ]]
          exit
        fi
        printf 'kill %s\\n' "$*" >>"$STUB_INVOCATION_LOG"
        signal=TERM
        if [[ "${1:-}" == "-9" ]]; then signal=KILL; fi
        printf 'signal %s %s\\n' "$signal" "$target" >>"$STUB_KILL_LOG"
        if [[ "$target" == -* && "${STUB_NO_PROCESS_GROUPS:-0}" == "1" ]]; then
          exit 1
        fi
        mkdir -p "$STUB_PROCESS_STOPPED"
        if [[ "$target" == -* ]]; then
          mkdir -p "$STUB_GROUP_SIGNALLED"
          : >"$STUB_GROUP_SIGNALLED/$normalized_target"
        fi
        if [[ "${1:-}" != "-9" && "${STUB_RESIST_TERM:-0}" == "1" ]]; then exit 0; fi
        if [[ "${1:-}" == "-9" && "${STUB_UNKILLABLE:-0}" == "1" ]]; then exit 0; fi
        : >"$STUB_PROCESS_STOPPED/$normalized_target"
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
        "STUB_GROUP_SIGNALLED": str(group_signalled),
        "STUB_GROUP_PROBED": str(group_probed),
        "STUB_KILL_LOG": str(kill_log),
        "STUB_PROCESS_MAP": str(process_map),
        "STUB_READINESS_LOG": str(readiness_log),
        "STUB_API_BECAME_READY": str(api_became_ready),
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


def _use_controlled_path_without_setsid(env: dict[str, str]) -> None:
    """Keep required inert commands available while making setsid unresolvable."""

    bin_dir = Path(env["PYTHON_BIN"]).parent
    (bin_dir / "setsid").unlink()
    for name in ("bash", "cat", "dirname", "grep", "mkdir", "mv", "nohup", "sed", "sleep", "sort"):
        executable = shutil.which(name)
        assert executable is not None
        (bin_dir / name).symlink_to(executable)

    real_rm = shutil.which("rm")
    assert real_rm is not None
    _write_executable(
        bin_dir / "rm",
        """#!/usr/bin/env bash
        set -euo pipefail
        target="${!#}"
        if [[ "${STUB_REQUIRE_DEAD_BEFORE_PID_REMOVE:-0}" == "1" && "$target" == *.pid && -f "$target" ]]; then
          pid="$(cat "$target")"
          state=alive
          if [[ -f "$STUB_PROCESS_STOPPED/$pid" ]]; then state=dead; fi
          printf 'remove %s %s\\n' "$state" "$pid" >>"$STUB_PID_REMOVAL_LOG"
          [[ "$state" == dead ]] || exit 97
        fi
        exec "$STUB_REAL_RM" "$@"
        """,
    )
    env.update(
        {
            "PATH": str(bin_dir),
            "STUB_NO_PROCESS_GROUPS": "1",
            "STUB_PID_REMOVAL_LOG": str(bin_dir.parent / "pid-removal.log"),
            "STUB_REAL_RM": real_rm,
            "STUB_RECORD_DIRECT_LAUNCHES": "1",
            "STUB_REQUIRE_DEAD_BEFORE_PID_REMOVE": "1",
        }
    )
    probe = subprocess.run(
        ["bash", "-c", "command -v setsid"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert probe.returncode != 0
    assert probe.stdout == ""


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


def _seed_runtime(data_dir: Path, pids: tuple[str, str, str], canary: str) -> Path:
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    for name, pid in zip(("web-vite", "mobile-api", "import-worker"), pids, strict=True):
        (runtime_dir / f"{name}.pid").write_text(pid, encoding="utf-8")
        (runtime_dir / f"{name}.log").write_text(f"{canary}:{name}\n", encoding="utf-8")
    (runtime_dir / "import-worker.heartbeat").write_text(f"{canary}:heartbeat\n", encoding="utf-8")
    return runtime_dir


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _process_pids(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["STUB_PROCESS_MAP"]).read_text(encoding="utf-8").splitlines()
    return {label: pid for label, pid in (line.split() for line in lines)}


def _signal_targets(invocation_log: Path) -> list[str]:
    return [
        line.rsplit(" ", maxsplit=1)[-1]
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("kill ")
    ]


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
        if "scripts/ops.py wait-health" in line and "--timeout 2" not in line
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


def test_status_and_stop_ignore_poisoned_repo_dotenv_when_requested(tmp_path: Path) -> None:
    """Dotenv bypass selects only the isolated runtime and executables."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    copied_root = _copy_script_tree(tmp_path)
    safe_runtime = _seed_runtime(data_dir, ("4101", "4102", "4103"), "safe")
    Path(env["STUB_WORKER_HEARTBEAT_FRESH"]).touch()

    poison_data = tmp_path / "poison-data"
    _seed_runtime(poison_data, ("9101", "9102", "9103"), "poison")
    poison_bin = tmp_path / "poison-bin"
    poison_bin.mkdir()
    poison_invocations = tmp_path / "poison-invocations.log"
    poison_signals = tmp_path / "poison-signals.log"
    poison_stopped = tmp_path / "poison-stopped"
    _write_executable(
        poison_bin / "python",
        """#!/usr/bin/env bash
        printf 'poison-python %s\n' "$*" >>"$POISON_INVOCATION_LOG"
        """,
    )
    _write_executable(
        poison_bin / "curl",
        """#!/usr/bin/env bash
        printf 'poison-curl %s\n' "$*" >>"$POISON_INVOCATION_LOG"
        """,
    )
    _write_executable(
        poison_bin / "kill",
        """#!/usr/bin/env bash
        set -euo pipefail
        target="${!#}"
        normalized_target="${target#-}"
        if [[ "${1:-}" == "-0" ]]; then
          [[ ! -f "$POISON_STOPPED/$normalized_target" ]]
          exit
        fi
        printf 'poison-kill %s\n' "$*" >>"$POISON_SIGNAL_LOG"
        mkdir -p "$POISON_STOPPED"
        : >"$POISON_STOPPED/$normalized_target"
        """,
    )
    env.update(
        {
            "POISON_INVOCATION_LOG": str(poison_invocations),
            "POISON_SIGNAL_LOG": str(poison_signals),
            "POISON_STOPPED": str(poison_stopped),
        }
    )
    (copied_root / ".env").write_text(
        "\n".join(
            (
                f"DATA_DIR={shlex.quote(str(poison_data))}",
                f"PYTHON_BIN={shlex.quote(str(poison_bin / 'python'))}",
                f"PATH={shlex.quote(str(poison_bin))}:$PATH",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    poison_before = _snapshot_tree(poison_data)

    assert not (ROOT / ".env").exists()
    status = _run_script("status-local.sh", env, copied_root)

    assert status.returncode == 0, status.stderr
    assert status.stderr == ""
    assert status.stdout.splitlines() == [
        "API running: pid 4102",
        "Web running: pid 4101",
        "Import worker running: pid 4103",
        "Import worker health: ok",
        "API readiness: ok",
        "Web health: ok",
    ]
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        "python -c import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)",
        "python -m app.import_worker --healthcheck",
        "worker-healthcheck ok",
        "python scripts/ops.py wait-health --base-url http://127.0.0.1:7860 --timeout 3",
        "curl -fsS http://127.0.0.1:5174/",
    ]
    assert Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "poll alive 4102",
        "poll alive 4101",
        "poll alive 4103",
    ]
    assert _snapshot_tree(poison_data) == poison_before
    assert not poison_invocations.exists()
    assert not poison_signals.exists()
    assert not poison_stopped.exists()

    invocation_log.write_text("", encoding="utf-8")
    Path(env["STUB_KILL_LOG"]).write_text("", encoding="utf-8")
    stop = _run_script("stop-local.sh", env, copied_root)

    assert stop.returncode == 0, stop.stderr
    assert stop.stderr == ""
    assert stop.stdout.splitlines() == ["Web stopped", "API stopped", "Import worker stopped"]
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        "kill -- -4101",
        "kill -- -4102",
        "kill -- -4103",
    ]
    assert Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "poll alive 4101",
        "poll alive -4101",
        "signal TERM -4101",
        "poll stopped 4101",
        "poll alive 4102",
        "poll alive -4102",
        "signal TERM -4102",
        "poll stopped 4102",
        "poll alive 4103",
        "poll alive -4103",
        "signal TERM -4103",
        "poll stopped 4103",
    ]
    assert not any(path.exists() for path in safe_runtime.glob("*.pid"))
    assert _snapshot_tree(poison_data) == poison_before
    assert not poison_invocations.exists()
    assert not poison_signals.exists()
    assert not poison_stopped.exists()
    assert not (ROOT / ".env").exists()
    assert all(target not in {"9101", "-9101", "9102", "-9102", "9103", "-9103"} for target in _signal_targets(invocation_log))


def test_start_scripts_ignore_poisoned_repo_dotenv_when_requested(tmp_path: Path) -> None:
    """Both start workflows keep their runtime artifacts out of poison data."""

    env, _, data_dir = _script_test_environment(tmp_path)
    copied_root = _copy_script_tree(tmp_path)
    poison_dir = tmp_path / "operator-runtime"
    (copied_root / ".env").write_text(
        f"DATA_DIR={poison_dir}\nPYTHON_BIN=/operator/python\nPATH=/operator/bin\n",
        encoding="utf-8",
    )

    local = _run_script("start-local.sh", env, copied_root)
    assert local.returncode == 0, local.stderr
    cloudflare = _run_script("start-cloudflare.sh", {**env, "CLOUDFLARE_HOSTNAME": "local.example.test"}, copied_root)
    assert cloudflare.returncode == 0, cloudflare.stderr
    assert (data_dir / "logs" / "runtime" / "import-worker.log").is_file()
    assert not poison_dir.exists()
    assert not (ROOT / ".env").exists()


def test_fresh_start_rotates_before_opening_import_worker_log(tmp_path: Path) -> None:
    """Rotation must complete before a new worker opens its append-only log."""

    env, invocation_log, _ = _script_test_environment(tmp_path)
    env["STUB_API_ALREADY_REACHABLE"] = "0"
    env["STUB_PREEXISTING_WEB"] = "0"

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    lines = invocation_log.read_text(encoding="utf-8").splitlines()
    assert lines.index("rotate-logs") < next(i for i, line in enumerate(lines) if line.startswith("setsid") and "app.import_worker" in line)


def test_missing_worker_does_not_rotate_live_api_or_web_logs(tmp_path: Path) -> None:
    """Recovering only the worker leaves active API and Vite logs untouched."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "mobile-api.pid").write_text("4102", encoding="utf-8")
    (runtime_dir / "web-vite.pid").write_text("4101", encoding="utf-8")
    (runtime_dir / "mobile-api.log").write_text("api writer\n", encoding="utf-8")
    (runtime_dir / "web-vite.log").write_text("web writer\n", encoding="utf-8")

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    assert (runtime_dir / "mobile-api.log").read_text(encoding="utf-8") == "api writer\n"
    assert (runtime_dir / "web-vite.log").read_text(encoding="utf-8") == "web writer\n"
    assert not (runtime_dir / "mobile-api.log.1").exists()
    assert not (runtime_dir / "web-vite.log.1").exists()
    assert "rotate-logs" not in invocation_log.read_text(encoding="utf-8").splitlines()


def test_missing_worker_does_not_rotate_reachable_api_or_web_logs(tmp_path: Path) -> None:
    """Reachable writers without PID files still protect their open logs."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env["STUB_PREEXISTING_API"] = "1"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "mobile-api.log").write_text("api writer\n", encoding="utf-8")
    (runtime_dir / "web-vite.log").write_text("web writer\n", encoding="utf-8")

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    assert (runtime_dir / "mobile-api.log").read_text(encoding="utf-8") == "api writer\n"
    assert (runtime_dir / "web-vite.log").read_text(encoding="utf-8") == "web writer\n"
    assert "rotate-logs" not in invocation_log.read_text(encoding="utf-8").splitlines()


def test_missing_worker_preserves_health_reachable_api_log_without_pid(tmp_path: Path) -> None:
    """Health protects the active log while readiness waits for worker freshness."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env["STUB_PREEXISTING_WEB"] = "0"
    env["STUB_PREEXISTING_API"] = "1"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "mobile-api.log").write_text("api writer\n", encoding="utf-8")

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    assert (runtime_dir / "mobile-api.log").read_text(encoding="utf-8") == "api writer\n"
    assert not (runtime_dir / "mobile-api.log.1").exists()
    lines = invocation_log.read_text(encoding="utf-8").splitlines()
    assert "rotate-logs" not in lines
    assert not any(line.startswith("setsid") and "app.mobile_api" in line for line in lines)
    curl_lines = [line for line in lines if line.startswith("curl ")]
    assert curl_lines == [
        "curl -fsS --max-time 2 http://127.0.0.1:7860/api/health",
        "curl -fsS --max-time 2 http://127.0.0.1:5174/",
    ]
    worker_start = next(i for i, line in enumerate(lines) if line.startswith("setsid") and "app.import_worker" in line)
    worker_health = next(i for i, line in enumerate(lines) if line == "worker-healthcheck ok")
    readiness_lines = [line for line in lines if "scripts/ops.py wait-health" in line]
    assert readiness_lines == [
        "python scripts/ops.py wait-health --base-url http://127.0.0.1:7860 --timeout 2",
    ]
    readiness_index = lines.index(readiness_lines[0])
    assert worker_start < worker_health < readiness_index
    assert Path(env["STUB_READINESS_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "api-health ok",
        "api-ready blocked",
        "api-ready ok",
    ]


def test_api_recovery_during_worker_start_prevents_duplicate_launch(tmp_path: Path) -> None:
    """A post-worker ready probe reuses an API that recovered after preflight."""

    env, invocation_log, _ = _script_test_environment(tmp_path)
    env.update(
        {
            "STUB_API_BECOMES_READY_WITH_WORKER": "1",
            "STUB_PREEXISTING_API": "0",
        }
    )

    result = _run_script("start-local.sh", env)

    assert result.returncode == 0, result.stderr
    lines = invocation_log.read_text(encoding="utf-8").splitlines()
    assert lines.count("curl -fsS --max-time 2 http://127.0.0.1:7860/api/health") == 1
    assert not any(line.startswith("setsid") and "app.mobile_api" in line for line in lines)
    readiness = [line for line in lines if "scripts/ops.py wait-health" in line]
    assert readiness == [
        "python scripts/ops.py wait-health --base-url http://127.0.0.1:7860 --timeout 2"
    ]
    assert Path(env["STUB_API_BECAME_READY"]).is_file()
    assert Path(env["STUB_READINESS_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "api-health unavailable",
        "api-ready ok",
    ]


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


def test_failure_cleanup_preserves_replaced_pid_file(tmp_path: Path) -> None:
    """Cleanup uses the captured launched PID and leaves a replacement PID intact."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    replacement = runtime_dir / "mobile-api.pid"
    env.update({
        "STUB_FAIL": "api-readiness",
        "STUB_ALLOW_DYNAMIC_PIDS": "1",
        "STUB_REPLACE_PID_FILE": str(replacement),
        "STUB_REPLACEMENT_PID": "4999",
    })

    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    assert replacement.read_text(encoding="utf-8") == "4999"
    assert all(target not in {"4999", "-4999"} for target in _signal_targets(invocation_log))


def test_resistant_owned_groups_escalate_in_reverse_order_without_following_replacement(tmp_path: Path) -> None:
    """Late failure cleans exact stable groups and preserves a replacement PID."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    runtime_dir = data_dir / "logs" / "runtime"
    replacement = runtime_dir / "mobile-api.pid"
    env.update(
        {
            "STUB_ALLOW_DYNAMIC_PIDS": "1",
            "STUB_DELAY_GROUP_FORMATION": "1",
            "STUB_FAIL_FINAL_OUTPUT": "1",
            "STUB_PREEXISTING_WEB": "0",
            "STUB_REPLACE_PID_FILE": str(replacement),
            "STUB_REPLACEMENT_PID": "4999",
            "STUB_RESIST_TERM": "1",
        }
    )

    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    pids = _process_pids(env)
    assert pids.keys() == {"worker", "api", "web"}
    assert replacement.read_text(encoding="utf-8") == "4999"
    assert not (runtime_dir / "web-vite.pid").exists()
    assert not (runtime_dir / "import-worker.pid").exists()
    expected_signals: list[str] = []
    expected_kill_flow = [
        event
        for label in ("worker", "api", "web")
        for event in (f"poll stopped -{pids[label]}", f"poll alive -{pids[label]}")
    ]
    for label in ("web", "api", "worker"):
        target = f"-{pids[label]}"
        expected_signals.extend((f"kill -- {target}", f"kill -9 -- {target}"))
        expected_kill_flow.extend(
            [f"signal TERM {target}"]
            + [f"poll alive {target}"] * 21
            + [f"signal KILL {target}", f"poll stopped {target}", f"poll stopped {target}"]
        )
    signals = [
        line
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("kill ")
    ]
    assert signals == expected_signals
    actual_kill_flow = Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert actual_kill_flow == expected_kill_flow
    assert all(target not in {"4999", "-4999"} for target in _signal_targets(invocation_log))
    assert not any(line.endswith((" 4999", " -4999")) for line in actual_kill_flow)


def test_local_no_setsid_failure_cleans_exact_positive_owned_targets(tmp_path: Path) -> None:
    """Fallback cleanup must escalate against each launched leader, never a group."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    _use_controlled_path_without_setsid(env)
    env.update(
        {
            "STUB_ALLOW_DYNAMIC_PIDS": "1",
            "STUB_FAIL_FINAL_OUTPUT": "1",
            "STUB_PREEXISTING_WEB": "0",
            "STUB_RESIST_TERM": "1",
        }
    )

    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    pids = _process_pids(env)
    assert pids.keys() == {"worker", "api", "web"}
    expected_signals: list[str] = []
    expected_kill_flow: list[str] = []
    expected_removals: list[str] = []
    for label in ("web", "api", "worker"):
        target = pids[label]
        expected_signals.extend((f"kill -- {target}", f"kill -9 -- {target}"))
        expected_kill_flow.extend(
            [f"signal TERM {target}"]
            + [f"poll alive {target}"] * 21
            + [f"signal KILL {target}", f"poll stopped {target}", f"poll stopped {target}"]
        )
        expected_removals.append(f"remove dead {target}")
    runtime_dir = data_dir / "logs" / "runtime"
    actual = {
        "signals": [
            line
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
            if line.startswith("kill ")
        ],
        "kill_flow": Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines(),
        "removals": Path(env["STUB_PID_REMOVAL_LOG"]).read_text(encoding="utf-8").splitlines(),
        "pid_files": sorted(path.name for path in runtime_dir.glob("*.pid")),
        "group_form_signal": Path(env["STUB_GROUP_SIGNALLED"]).exists(),
    }
    assert actual == {
        "signals": expected_signals,
        "kill_flow": expected_kill_flow,
        "removals": expected_removals,
        "pid_files": [],
        "group_form_signal": False,
    }


def test_cloudflare_no_setsid_failure_cleans_exact_positive_owned_targets(tmp_path: Path) -> None:
    """Public-local fallback cleanup must retain its own positive launch targets."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    _use_controlled_path_without_setsid(env)
    env.update(
        {
            "CLOUDFLARE_HOSTNAME": "local.example.test",
            "STUB_ALLOW_DYNAMIC_PIDS": "1",
            "STUB_FAIL": "curl",
            "STUB_RESIST_TERM": "1",
        }
    )

    result = _run_script("start-cloudflare.sh", env)

    assert result.returncode != 0
    pids = _process_pids(env)
    assert pids.keys() == {"worker", "api"}
    expected_signals: list[str] = []
    expected_kill_flow: list[str] = []
    expected_removals: list[str] = []
    for label in ("api", "worker"):
        target = pids[label]
        expected_signals.extend((f"kill -- {target}", f"kill -9 -- {target}"))
        expected_kill_flow.extend(
            [f"signal TERM {target}"]
            + [f"poll alive {target}"] * 21
            + [f"signal KILL {target}", f"poll stopped {target}", f"poll stopped {target}"]
        )
        expected_removals.append(f"remove dead {target}")
    runtime_dir = data_dir / "logs" / "runtime"
    actual = {
        "signals": [
            line
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
            if line.startswith("kill ")
        ],
        "kill_flow": Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines(),
        "removals": Path(env["STUB_PID_REMOVAL_LOG"]).read_text(encoding="utf-8").splitlines(),
        "pid_files": sorted(path.name for path in runtime_dir.glob("*.pid")),
        "group_form_signal": Path(env["STUB_GROUP_SIGNALLED"]).exists(),
    }
    assert actual == {
        "signals": expected_signals,
        "kill_flow": expected_kill_flow,
        "removals": expected_removals,
        "pid_files": [],
        "group_form_signal": False,
    }


def test_unkillable_owned_target_preserves_its_pid_file(tmp_path: Path) -> None:
    """Persistent group liveness keeps the PID file and emits a safe error."""

    env, invocation_log, data_dir = _script_test_environment(tmp_path)
    env.update(
        {
            "STUB_FAIL": "worker-health",
            "IMPORT_WORKER_START_TIMEOUT": "0",
            "STUB_ALLOW_DYNAMIC_PIDS": "1",
            "STUB_DELAY_GROUP_FORMATION": "1",
            "STUB_RESIST_TERM": "1",
            "STUB_UNKILLABLE": "1",
        }
    )
    result = _run_script("start-local.sh", env)

    assert result.returncode != 0
    worker_pid = _process_pids(env)["worker"]
    worker_pid_file = data_dir / "logs" / "runtime" / "import-worker.pid"
    assert worker_pid_file.read_text(encoding="utf-8").strip() == worker_pid
    target = f"-{worker_pid}"
    assert [
        line
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("kill ")
    ] == [f"kill -- {target}", f"kill -9 -- {target}"]
    assert Path(env["STUB_KILL_LOG"]).read_text(encoding="utf-8").splitlines() == (
        [f"poll stopped {target}", f"poll alive {target}", f"signal TERM {target}"]
        + [f"poll alive {target}"] * 21
        + [f"signal KILL {target}"]
        + [f"poll alive {target}"] * 21
    )
    assert result.stderr.splitlines().count("Cleanup could not stop owned process") == 1


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
    worker_targets = {env["STUB_PROCESS_PID"], f"-{env['STUB_PROCESS_PID']}"}
    assert all(target not in worker_targets for target in _signal_targets(invocation_log))


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
    assert signals == ["kill -- -4101", "kill -- -4102", "kill -- -4103"]


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
