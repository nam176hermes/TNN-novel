from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke-browser-execution-isolation.sh"

FORBIDDEN_WORKER_KEYS = {
    "REMOTE_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "MOBILE_API_SECRET",
    "MOBILE_API_ADMIN_PASSWORD",
}


def _safe_compose_config() -> dict[str, object]:
    return {
        "services": {
            "api": {
                "image": "novel-pipeline-api:local",
                "environment": {
                    "MOBILE_API_SECRET": "safe-render-only",
                    "MOBILE_API_ADMIN_PASSWORD": "safe-render-only",
                },
                "networks": {"api-egress": None},
                "volumes": [
                    {"type": "bind", "source": "/tmp/data", "target": "/data"},
                    {
                        "type": "volume",
                        "source": "render_provider-secrets",
                        "target": "/data/secrets",
                    },
                ],
            },
            "import-worker": {
                "image": "novel-pipeline-import-worker:local",
                "environment": {
                    "DATA_DIR": "/data",
                    "NOVEL_COMPONENT": "import-worker",
                    "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
                },
                "networks": {"browser-egress": None},
                "volumes": [
                    {"type": "bind", "source": "/tmp/data", "target": "/data"}
                ],
            },
        },
        "networks": {"api-egress": {}, "browser-egress": {}},
        "volumes": {"provider-secrets": {}},
    }


def _write_fake_docker(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            r'''
            #!/usr/bin/env python3
            import json
            import os
            import pathlib
            import sys

            args = sys.argv[1:]
            with pathlib.Path(os.environ["FAKE_DOCKER_LOG"]).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(args) + "\n")

            if args == ["--version"] or args == ["compose", "version"]:
                raise SystemExit(0)

            if args and args[0] == "build":
                if "--target" not in args or "-t" not in args:
                    raise SystemExit(90)
                raise SystemExit(0)

            if args and args[0] == "run":
                command = " ".join(args)
                if "-api-check" in command:
                    required = (
                        "command -v",
                        "chromium-browser",
                        "PLAYWRIGHT_BROWSERS_PATH",
                        "/ms-playwright",
                    )
                    if any(token not in command for token in required):
                        raise SystemExit(91)
                    if os.environ.get("FAKE_API_BROWSER_PRESENT") == "1":
                        print("browser executable unexpectedly present", file=sys.stderr)
                        raise SystemExit(20)
                    raise SystemExit(0)
                if "-worker-check" in command:
                    required = ("--user", "novel", "page.set_content", "worker-browser-ok")
                    if any(token not in command for token in required):
                        raise SystemExit(92)
                    if os.environ.get("FAKE_WORKER_BROWSER_FAIL") == "1":
                        print("worker browser launch failed", file=sys.stderr)
                        raise SystemExit(31)
                    raise SystemExit(0)
                raise SystemExit(93)

            if args and args[0] == "compose" and "config" in args:
                config = pathlib.Path(os.environ["FAKE_COMPOSE_CONFIG"])
                sys.stdout.write(config.read_text(encoding="utf-8"))
                raise SystemExit(0)

            if len(args) >= 3 and args[:2] == ["image", "inspect"]:
                if args[-1].endswith("-api:smoke"):
                    print("12345678")
                else:
                    print("34567890")
                raise SystemExit(0)

            if args and args[0] in {"rm", "network", "volume", "image"}:
                raise SystemExit(0)

            raise SystemExit(94)
            '''
        ).lstrip(),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_smoke(
    tmp_path: Path,
    *,
    compose_config: dict[str, object] | None = None,
    api_browser_present: bool = False,
    worker_browser_fail: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    _write_fake_docker(fake_bin / "docker")
    log_path = tmp_path / "docker.jsonl"
    config_path = tmp_path / "compose.json"
    config_path.write_text(
        json.dumps(compose_config or _safe_compose_config()), encoding="utf-8"
    )
    smoke_tmp = tmp_path / "smoke-tmp"
    smoke_tmp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TMPDIR": str(smoke_tmp),
        "FAKE_DOCKER_LOG": str(log_path),
        "FAKE_COMPOSE_CONFIG": str(config_path),
        "FAKE_API_BROWSER_PRESENT": "1" if api_browser_present else "0",
        "FAKE_WORKER_BROWSER_FAIL": "1" if worker_browser_fail else "0",
        "NOVEL_PIPELINE_IGNORE_DOTENV": "1",
    }
    result = subprocess.run(
        ["bash", str(SMOKE)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = (
        [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        if log_path.exists()
        else []
    )
    return result, calls, smoke_tmp


def _prefix_from_calls(calls: list[list[str]]) -> str:
    api_build = next(
        call
        for call in calls
        if call[:1] == ["build"] and call[call.index("--target") + 1] == "api"
    )
    api_tag = api_build[api_build.index("-t") + 1]
    assert api_tag.endswith("-api:smoke")
    return api_tag.removesuffix("-api:smoke")


def _assert_exact_cleanup(calls: list[list[str]], smoke_tmp: Path) -> None:
    prefix = _prefix_from_calls(calls)
    assert ["rm", "-f", f"{prefix}-api-check"] in calls
    assert ["rm", "-f", f"{prefix}-worker-check"] in calls
    assert ["network", "rm", f"{prefix}-network"] in calls
    assert ["volume", "rm", f"{prefix}-volume"] in calls
    assert ["image", "rm", "-f", f"{prefix}-api:smoke", f"{prefix}-worker:smoke"] in calls

    cleanup_calls = [
        call
        for call in calls
        if call[:1] == ["rm"]
        or call[:2] in (["network", "rm"], ["volume", "rm"], ["image", "rm"])
    ]
    for call in cleanup_calls:
        args_after_verb = call[1:] if call[0] == "rm" else call[2:]
        resource_args = [arg for arg in args_after_verb if not arg.startswith("-")]
        assert resource_args
        assert all(prefix in arg for arg in resource_args)
    assert not list(smoke_tmp.glob(f"{prefix}*"))


def test_api_image_has_no_executable_browser(tmp_path: Path) -> None:
    passed, calls, smoke_tmp = _run_smoke(tmp_path / "passing")
    assert passed.returncode == 0, passed.stderr
    api_run = next(call for call in calls if " ".join(call).find("-api-check") >= 0)
    assert "command -v" in " ".join(api_run)
    assert "chromium-browser" in " ".join(api_run)
    assert "PLAYWRIGHT_BROWSERS_PATH" in " ".join(api_run)
    assert "/ms-playwright" in " ".join(api_run)
    _assert_exact_cleanup(calls, smoke_tmp)

    failed, failed_calls, failed_tmp = _run_smoke(
        tmp_path / "browser-present", api_browser_present=True
    )
    assert failed.returncode != 0
    _assert_exact_cleanup(failed_calls, failed_tmp)


def test_worker_image_launches_chromium_on_synthetic_page(tmp_path: Path) -> None:
    passed, calls, smoke_tmp = _run_smoke(tmp_path / "passing")
    assert passed.returncode == 0, passed.stderr
    worker_run = next(call for call in calls if " ".join(call).find("-worker-check") >= 0)
    worker_command = " ".join(worker_run)
    assert "--user novel" in worker_command
    assert "page.set_content" in worker_command
    assert "worker-browser-ok" in worker_command
    _assert_exact_cleanup(calls, smoke_tmp)

    failed, failed_calls, failed_tmp = _run_smoke(
        tmp_path / "worker-failed", worker_browser_fail=True
    )
    assert failed.returncode != 0
    _assert_exact_cleanup(failed_calls, failed_tmp)


def test_rendered_compose_keeps_worker_off_provider_secrets_and_api_dns(
    tmp_path: Path,
) -> None:
    passed, calls, smoke_tmp = _run_smoke(tmp_path / "passing")
    assert passed.returncode == 0, passed.stderr
    compose_call = next(call for call in calls if call[:1] == ["compose"] and "config" in call)
    assert "--env-file" in compose_call
    assert "api image bytes: 12345678" in passed.stdout
    assert "worker image bytes: 34567890" in passed.stdout
    assert "safe-render-only" not in passed.stdout + passed.stderr
    _assert_exact_cleanup(calls, smoke_tmp)

    for forbidden_key in FORBIDDEN_WORKER_KEYS:
        secret_config = _safe_compose_config()
        worker = secret_config["services"]["import-worker"]  # type: ignore[index]
        worker["environment"][forbidden_key] = "never-print-this-secret"  # type: ignore[index]
        worker["volumes"].append(  # type: ignore[index]
            {
                "type": "volume",
                "source": "render_provider-secrets",
                "target": "/data/secrets",
            }
        )
        secret_failure, secret_calls, secret_tmp = _run_smoke(
            tmp_path / f"secret-leak-{forbidden_key.lower()}",
            compose_config=secret_config,
        )
        assert secret_failure.returncode != 0
        assert "never-print-this-secret" not in secret_failure.stdout + secret_failure.stderr
        _assert_exact_cleanup(secret_calls, secret_tmp)

    dns_config = _safe_compose_config()
    dns_worker = dns_config["services"]["import-worker"]  # type: ignore[index]
    dns_worker["networks"] = {"api-egress": None}  # type: ignore[index]
    dns_failure, dns_calls, dns_tmp = _run_smoke(
        tmp_path / "shared-api-dns", compose_config=dns_config
    )
    assert dns_failure.returncode != 0
    _assert_exact_cleanup(dns_calls, dns_tmp)
