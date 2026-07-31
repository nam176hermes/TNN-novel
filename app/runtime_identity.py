"""Safe, immutable release metadata shared by the API and worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re

from app.database.db import CURRENT_SCHEMA_VERSION


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,191}$")


def _value(name: str, default: str) -> str:
    value = str(os.getenv(name, default) or default).strip()
    return value if _SAFE_VALUE.fullmatch(value) else default


@dataclass(frozen=True)
class RuntimeIdentity:
    version: str
    frontend_version: str
    git_sha: str
    build_timestamp: str
    release_id: str
    image_tag: str
    image_digest: str
    schema_revision: str
    component: str

    def safe_dict(self) -> dict[str, str]:
        return asdict(self)


def get_runtime_identity(*, component: str | None = None) -> RuntimeIdentity:
    """Read build metadata without exposing arbitrary environment values."""

    version = _value("NOVEL_APP_VERSION", "0.1.0")
    return RuntimeIdentity(
        version=version,
        frontend_version=_value("NOVEL_FRONTEND_VERSION", version),
        git_sha=_value("NOVEL_GIT_SHA", "unknown"),
        build_timestamp=_value("NOVEL_BUILD_TIMESTAMP", "unknown"),
        release_id=_value("NOVEL_RELEASE_ID", "development"),
        image_tag=_value("NOVEL_IMAGE_TAG", "unknown"),
        image_digest=_value("NOVEL_IMAGE_DIGEST", "unknown"),
        schema_revision=CURRENT_SCHEMA_VERSION,
        component=_value("NOVEL_COMPONENT", component or "unknown"),
    )
