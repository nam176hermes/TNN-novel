"""Run isolated loopback delivery validation for operational alerts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Sequence

from app.config import PROJECT_ROOT, settings
from app.services.operational_alert_delivery import (
    AlertDeliveryConfig,
    DeliveryReceipt,
    OperationalAlertDispatcher,
    SUPPORTED_ALERT_CLASSES,
)


_PAYLOAD_KEYS = {
    "schema_version",
    "alert_class",
    "code",
    "severity",
    "release_id",
    "observed_at",
    "fingerprint",
}
_RECEIPT_FILENAMES = {
    "backup_failure": "alert-backup_failure.receipt.json",
    "wrong_release_receipt": "alert-wrong_release_receipt.receipt.json",
    "worker_stale": "alert-worker_stale.receipt.json",
    "stuck_jobs": "alert-stuck_jobs.receipt.json",
}
_SYNTHETIC_RESPONSE_BODY = b"synthetic-response-body"
_MAX_REQUEST_BYTES = 8 * 1024


def _validated_receipt_dir(raw_value: str) -> Path:
    path = Path(raw_value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise ValueError("Synthetic receipt directory is unsafe")
    try:
        metadata = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError:
        raise ValueError("Synthetic receipt directory is unsafe") from None
    lexical = Path(os.path.abspath(os.fspath(path)))
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or canonical != lexical
    ):
        raise ValueError("Synthetic receipt directory is unsafe")

    forbidden = (PROJECT_ROOT.resolve(), settings.resolved_data_dir.resolve())
    if canonical in forbidden:
        raise ValueError("Synthetic receipt directory is unsafe")
    return canonical


def _synthetic_snapshot() -> dict[str, object]:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "release": {"release_id": "synthetic-alert-smoke"},
        "alerts": [
            {"code": "backup_failed", "severity": "warning"},
            {"code": "external_backup_wrong_release", "severity": "warning"},
            {"code": "worker_stale", "severity": "critical"},
            {"code": "queue_stale", "severity": "warning"},
        ],
    }


def _handler_for(captured_requests: list[dict[str, object]]) -> type[BaseHTTPRequestHandler]:
    class SyntheticWebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                content_length = int(self.headers.get("Content-Length", ""))
                if not 1 <= content_length <= _MAX_REQUEST_BYTES:
                    raise ValueError
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
                    raise ValueError
            except (UnicodeError, ValueError, json.JSONDecodeError):
                self.send_error(400)
                return
            captured_requests.append(payload)
            self.send_response(202)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(_SYNTHETIC_RESPONSE_BODY)))
            self.end_headers()
            self.wfile.write(_SYNTHETIC_RESPONSE_BODY)

        def log_message(self, format: str, *args: object) -> None:
            return

    return SyntheticWebhookHandler


def _verify_smoke_artifacts(
    receipt_dir: Path,
    receipts: tuple[DeliveryReceipt, ...],
    captured_requests: list[dict[str, object]],
) -> None:
    if [(receipt.alert_class, receipt.status) for receipt in receipts] != [
        (alert_class, "delivered") for alert_class in SUPPORTED_ALERT_CLASSES
    ]:
        raise RuntimeError("Synthetic delivery did not deliver every alert class")
    if len(captured_requests) != len(SUPPORTED_ALERT_CLASSES) or any(
        set(payload) != _PAYLOAD_KEYS for payload in captured_requests
    ):
        raise RuntimeError("Synthetic delivery payload validation failed")
    expected_names = set(_RECEIPT_FILENAMES.values())
    files = tuple(receipt_dir.iterdir())
    if {path.name for path in files} != expected_names or any(
        not path.is_file() or path.is_symlink() for path in files
    ):
        raise RuntimeError("Synthetic delivery receipt validation failed")
    for alert_class, filename in _RECEIPT_FILENAMES.items():
        try:
            payload = json.loads((receipt_dir / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Synthetic delivery receipt validation failed") from None
        if payload.get("alert_class") != alert_class or payload.get("status") != "delivered":
            raise RuntimeError("Synthetic delivery receipt validation failed")


def run_smoke(
    receipt_dir: Path,
) -> tuple[tuple[DeliveryReceipt, ...], tuple[dict[str, object], ...]]:
    receipt_dir = _validated_receipt_dir(os.fspath(receipt_dir))
    captured_requests: list[dict[str, object]] = []
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler_for(captured_requests),
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        if host != "127.0.0.1":
            raise RuntimeError("Synthetic receiver did not bind literal loopback")
        dispatcher = OperationalAlertDispatcher(
            AlertDeliveryConfig(
                webhook_url=f"http://127.0.0.1:{port}/operational-alert",
                timeout_seconds=2.0,
                max_attempts=1,
                allow_loopback_http=True,
            ),
            receipt_dir=receipt_dir,
        )
        receipts = dispatcher.dispatch(_synthetic_snapshot())
        _verify_smoke_artifacts(receipt_dir, receipts, captured_requests)
        return receipts, tuple(captured_requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _receipt_dir_argument(argv: Sequence[str] | None) -> Path:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--receipt-dir")
    try:
        parsed, extras = parser.parse_known_args(argv)
    except argparse.ArgumentError:
        raise ValueError("Synthetic receipt directory is required") from None
    if extras or not parsed.receipt_dir:
        raise ValueError("Synthetic receipt directory is required")
    return _validated_receipt_dir(parsed.receipt_dir)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        receipt_dir = _receipt_dir_argument(argv)
    except (TypeError, ValueError):
        print("status=configuration_error", file=sys.stderr)
        return 2
    try:
        receipts, _captured_requests = run_smoke(receipt_dir)
    except Exception:
        print("status=error", file=sys.stderr)
        return 1
    for receipt in receipts:
        print(f"class={receipt.alert_class} status={receipt.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
