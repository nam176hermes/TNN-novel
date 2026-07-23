from __future__ import annotations

import os
import subprocess
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
