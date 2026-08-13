from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "ci-docker-runtime-smoke.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _run_smoke(tmp_path: Path, *, fail_root_probe: bool = False) -> tuple[subprocess.CompletedProcess[str], list[list[str]], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    docker_log = tmp_path / "docker.jsonl"
    curl_log = tmp_path / "curl.log"
    _write_executable(
        bin_dir / "docker",
        r'''
        #!/usr/bin/env python3
        import json
        import os
        from pathlib import Path
        import sys

        args = sys.argv[1:]
        with Path(os.environ["FAKE_DOCKER_LOG"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")

        if args[:2] == ["volume", "create"]:
            print(args[-1])
            raise SystemExit(0)
        if args[:2] == ["volume", "rm"]:
            raise SystemExit(0)
        if args[:2] == ["rm", "-f"]:
            raise SystemExit(0)
        if args[:1] == ["logs"]:
            raise SystemExit(0)
        if args[:2] == ["run", "-d"]:
            print("fake-container-id")
            raise SystemExit(0)
        if args[:1] == ["exec"]:
            if args[-4:] != ["python", "-m", "app.import_worker", "--healthcheck"]:
                raise SystemExit(81)
            raise SystemExit(0)
        raise SystemExit(82)
        ''',
    )
    _write_executable(
        bin_dir / "curl",
        r'''
        #!/usr/bin/env python3
        import os
        from pathlib import Path
        import sys

        url = sys.argv[-1]
        with Path(os.environ["FAKE_CURL_LOG"]).open("a", encoding="utf-8") as handle:
            handle.write(url + "\n")
        if url.endswith("/") and os.environ.get("FAKE_ROOT_PROBE_FAIL") == "1":
            raise SystemExit(22)
        if url.endswith("/"):
            print('<div id="root"></div>')
        else:
            print('{"status":"ready"}')
        ''',
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_ROOT_PROBE_FAIL": "1" if fail_root_probe else "0",
        "CI_DOCKER_SMOKE_ID": "ws1-ci-contract",
        "CI_DOCKER_RELEASE_ID": "ci-release-123",
        "CI_DOCKER_GIT_SHA": "deadbeef",
        "CI_DOCKER_IMAGE_DIGEST": "sha256:ci-contract",
        "CI_API_IMAGE": "novel-pipeline-api:ci",
        "CI_WORKER_IMAGE": "novel-pipeline-import-worker:ci",
    }
    result = subprocess.run(
        ["bash", str(SMOKE)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    docker_calls = [
        json.loads(line)
        for line in docker_log.read_text(encoding="utf-8").splitlines()
    ] if docker_log.exists() else []
    curl_calls = curl_log.read_text(encoding="utf-8").splitlines() if curl_log.exists() else []
    return result, docker_calls, curl_calls


def _run_call(calls: list[list[str]], name: str) -> list[str]:
    return next(call for call in calls if call[:2] == ["run", "-d"] and name in call)


def _assert_exact_cleanup(calls: list[list[str]]) -> None:
    assert ["rm", "-f", "ws1-ci-contract-api"] in calls
    assert ["rm", "-f", "ws1-ci-contract-worker"] in calls
    assert ["volume", "rm", "ws1-ci-contract-data"] in calls
    destructive = [call for call in calls if call[:1] == ["rm"] or call[:2] == ["volume", "rm"]]
    assert destructive == [
        ["rm", "-f", "ws1-ci-contract-api"],
        ["rm", "-f", "ws1-ci-contract-worker"],
        ["volume", "rm", "ws1-ci-contract-data"],
    ]


def test_ci_runtime_smoke_starts_healthy_worker_before_ready_api_on_one_isolated_volume(tmp_path: Path) -> None:
    result, calls, curl_calls = _run_smoke(tmp_path)

    assert result.returncode == 0, result.stderr
    assert ["volume", "create", "ws1-ci-contract-data"] in calls
    worker_run = _run_call(calls, "ws1-ci-contract-worker")
    api_run = _run_call(calls, "ws1-ci-contract-api")
    shared_mount = "type=volume,src=ws1-ci-contract-data,dst=/data"
    for run_call in (worker_run, api_run):
        assert [shared_mount] == [run_call[run_call.index("--mount") + 1]]
        assert "NOVEL_RELEASE_ID=ci-release-123" in run_call
        assert "NOVEL_GIT_SHA=deadbeef" in run_call
        assert "NOVEL_IMAGE_DIGEST=sha256:ci-contract" in run_call
    assert "-p" not in worker_run
    assert api_run[api_run.index("-p") + 1] == "127.0.0.1:7860:7860"
    worker_health = [
        "exec",
        "ws1-ci-contract-worker",
        "python",
        "-m",
        "app.import_worker",
        "--healthcheck",
    ]
    assert calls.index(worker_run) < calls.index(worker_health) < calls.index(api_run)
    assert curl_calls[-2:] == ["http://127.0.0.1:7860/api/ready", "http://127.0.0.1:7860/"]
    _assert_exact_cleanup(calls)


def test_ci_runtime_smoke_cleans_both_containers_and_volume_after_probe_failure(tmp_path: Path) -> None:
    result, calls, _curl_calls = _run_smoke(tmp_path, fail_root_probe=True)

    assert result.returncode != 0
    _assert_exact_cleanup(calls)
