from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Generator

import pytest

os.environ.setdefault("NOVEL_PIPELINE_IGNORE_DOTENV", "1")


def _configure_test_tempdir() -> Path:
    """Keep WSL test SQLite files off an inherited Windows-mounted temp path."""
    override = os.environ.get("NOVEL_PIPELINE_TEST_TMPDIR")
    if override:
        candidate = Path(override).expanduser()
    else:
        inherited = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP") or ""
        candidate = Path("/tmp") if os.name != "nt" and inherited.startswith("/mnt/") else Path(tempfile.gettempdir())
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


_TEST_TMPDIR = _configure_test_tempdir()
os.environ["TMPDIR"] = str(_TEST_TMPDIR)
os.environ["TMP"] = str(_TEST_TMPDIR)
os.environ["TEMP"] = str(_TEST_TMPDIR)

# App-level API tests import singleton settings, so isolate DATA_DIR before any
# application module can resolve the repository's operator database.
_PYTEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="novel-tnn-pytest-", dir=_TEST_TMPDIR))
os.environ["DATA_DIR"] = str(_PYTEST_DATA_DIR)
_PYTEST_PROVIDER_SECRET_DIR = Path(
    tempfile.mkdtemp(prefix="novel-tnn-provider-secrets-pytest-", dir=_TEST_TMPDIR)
)
os.environ["PROVIDER_SECRET_STORE_PATH"] = str(
    _PYTEST_PROVIDER_SECRET_DIR / "provider-keys.json"
)

from app.database.schema import SCHEMA


def pytest_sessionfinish() -> None:
    shutil.rmtree(_PYTEST_DATA_DIR, ignore_errors=True)
    shutil.rmtree(_PYTEST_PROVIDER_SECRET_DIR, ignore_errors=True)


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary SQLite database with schema, yield path, then clean up."""
    fd, path = tempfile.mkstemp(suffix=".db", dir=_TEST_TMPDIR)
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def sample_glossary() -> dict[str, str]:
    return {"灵石": "linh thạch", "修真": "tu chân", "丹药": "đan dược"}


@pytest.fixture
def sample_chinese_text() -> str:
    return "\n".join(
        [
            "第一章",
            "张铁睁开双眼，发现自己躺在一间破旧的茅草屋里。",
            "他揉了揉眼睛，确信自己不是在梦中。",
            "",
            "丹田之内一阵刺痛传来，他不由得闷哼一声。",
        ]
    )
