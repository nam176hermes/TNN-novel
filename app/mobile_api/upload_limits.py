from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.mobile_api.config import mobile_settings

UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


def _format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} bytes"


def upload_too_large_exception(label: str, max_bytes: int | None = None) -> HTTPException:
    limit = max(1, int(max_bytes if max_bytes is not None else mobile_settings.upload_max_bytes))
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"{label} is too large. Maximum allowed size is {_format_bytes(limit)}.",
    )


async def read_upload_bytes_limited(
    file: UploadFile,
    *,
    label: str,
    max_bytes: int | None = None,
) -> bytes:
    limit = max(1, int(max_bytes if max_bytes is not None else mobile_settings.upload_max_bytes))
    chunks: list[bytes] = []
    total = 0
    while True:
        read_size = min(UPLOAD_READ_CHUNK_BYTES, limit - total + 1)
        chunk = await file.read(read_size)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise upload_too_large_exception(label, limit)
        chunks.append(chunk)
    return b"".join(chunks)


async def write_upload_to_temp_limited(
    file: UploadFile,
    *,
    suffix: str,
    prefix: str,
    label: str,
    max_bytes: int | None = None,
) -> Path:
    limit = max(1, int(max_bytes if max_bytes is not None else mobile_settings.upload_max_bytes))
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=prefix)
    temp_path = Path(handle.name)
    total = 0
    try:
        while True:
            read_size = min(UPLOAD_READ_CHUNK_BYTES, limit - total + 1)
            chunk = await file.read(read_size)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise upload_too_large_exception(label, limit)
            handle.write(chunk)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        handle.close()
