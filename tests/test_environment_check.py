from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-environment.sh"


def _production_env(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "MOBILE_API_SECRET": "test-secret",
        "MOBILE_API_ADMIN_USERNAME": "operator",
        "MOBILE_API_ADMIN_PASSWORD": "test-password",
        "MOBILE_API_CORS_ORIGINS": "https://novel.example.test",
        "PUBLIC_DEPLOY": "1",
        **overrides,
    }
    path = tmp_path / "production.env"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _run_production_check(env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK), "--production", "--env-file", str(env_file)],
        cwd=ROOT,
        env={**os.environ, "NOVEL_PIPELINE_IGNORE_DOTENV": "1"},
        text=True,
        capture_output=True,
        check=False,
    )


def test_production_environment_check_uses_external_env_without_repo_dotenv(tmp_path: Path) -> None:
    result = _run_production_check(_production_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "external production environment file validated" in result.stdout
    assert "test-secret" not in result.stdout


def test_production_environment_check_rejects_non_https_cors(tmp_path: Path) -> None:
    result = _run_production_check(_production_env(tmp_path, MOBILE_API_CORS_ORIGINS="http://localhost:5173"))

    assert result.returncode == 1
    assert "HTTPS origins only" in result.stderr


def test_production_environment_check_uses_the_last_duplicate_assignment(tmp_path: Path) -> None:
    env_file = _production_env(tmp_path)
    env_file.write_text("PUBLIC_DEPLOY=0\n" + env_file.read_text(encoding="utf-8"), encoding="utf-8")

    result = _run_production_check(env_file)

    assert result.returncode == 0, result.stderr


def test_production_environment_check_requires_private_file_permissions(tmp_path: Path) -> None:
    env_file = _production_env(tmp_path)
    env_file.chmod(0o644)

    result = _run_production_check(env_file)

    assert result.returncode == 1
    assert "mode 0600" in result.stderr
