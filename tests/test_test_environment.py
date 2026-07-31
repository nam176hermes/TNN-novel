from __future__ import annotations

import os
from pathlib import Path


def test_sqlite_fixture_uses_native_wsl_temp_when_windows_temp_is_inherited(temp_db_path: Path) -> None:
    if os.name == "nt":
        return

    assert not str(temp_db_path).startswith("/mnt/")
    assert Path(os.environ["DATA_DIR"]).parent == Path(os.environ["TMPDIR"])
