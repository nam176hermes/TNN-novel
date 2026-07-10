from __future__ import annotations

from collections.abc import MutableMapping

PRIVATE_NO_STORE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def apply_private_no_store_headers(headers: MutableMapping[str, str]) -> None:
    for key, value in PRIVATE_NO_STORE_HEADERS.items():
        headers[key] = value
