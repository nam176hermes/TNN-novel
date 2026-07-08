#!/usr/bin/env python3
"""
Auto-import watcher: scans NovelTNN downloads folder → pushes to pipeline API.

Scans recursively for *.txt files, posts each to /api/import/paste,
moves imported files to an "imported" subfolder to prevent re-processing.

Usage:
    python3 auto_import_watcher.py            # one-shot scan
    python3 auto_import_watcher.py --watch    # continuous (poll every 30s)
"""
from __future__ import annotations

import os
import re
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone

import requests

# ─── Config ────────────────────────────────────────────────────────
PIPELINE_BASE = os.getenv("NOVEL_PIPELINE_URL", "http://localhost:7860")
ADMIN_USERNAME = os.getenv("MOBILE_API_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("MOBILE_API_ADMIN_PASSWORD", "")
WIN_DOWNLOAD_DIR = Path("/mnt/c/Users/thenam/Downloads/NovelTNN")
IMPORTED_DIR_NAME = "_imported"
POLL_INTERVAL = 30  # seconds

# ─── Auth ──────────────────────────────────────────────────────────

_token_cache: dict = {"token": "", "expires": 0}


def get_token() -> str:
    """Login and cache token until expiry."""
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]

    resp = requests.post(
        f"{PIPELINE_BASE}/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    # Token expires in 60 min; cache for 55
    _token_cache["expires"] = time.time() + 55 * 60
    log(f"Logged in as {ADMIN_USERNAME}")
    return _token_cache["token"]


def import_chapter(book_title: str, chapter_num: int, chapter_title: str, text: str) -> dict:
    """POST a chapter to the paste import endpoint."""
    token = get_token()
    resp = requests.post(
        f"{PIPELINE_BASE}/api/import/paste",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "title": book_title,
            "chapter_number": chapter_num,
            "chapter_title": chapter_title,
            "text": text,
        },
        timeout=30,
    )
    if resp.status_code == 409:
        return {"skipped": True, "reason": "duplicate"}
    resp.raise_for_status()
    return resp.json()


# ─── File parsing ──────────────────────────────────────────────────

# Filename patterns from the extension:
#   #1_第1章 归零.txt
#   #10_第10章 晚星苑.txt
#   ERROR_#5_第5章 xxx.txt   (error files — skip)

CHAPTER_RE = re.compile(r"^#?(\d+)_(.+)$")


def parse_filename(filepath: Path, book_override: str = "") -> tuple[str, int, str] | None:
    """
    Extract (book_title, chapter_number, chapter_title) from a NovelTNN file.

    The folder name is the book title; the filename has chapter info.
    Returns None for files that should be skipped (ERROR_ prefix, etc).
    """
    stem = filepath.stem

    # Skip error files
    if stem.startswith("ERROR_"):
        return None

    # Book title from parent folder
    book_title = book_override or filepath.parent.name

    # Try matching #1_第1章 归零 pattern
    m = CHAPTER_RE.match(stem)
    if m:
        chapter_num = int(m.group(1))
        chapter_title_raw = m.group(2).strip()
        # Clean: remove leading 第N章 prefix if present
        chapter_title = re.sub(r"^第\d+章\s*", "", chapter_title_raw).strip()
        if not chapter_title:
            chapter_title = chapter_title_raw
        return book_title, chapter_num, chapter_title

    return None


# ─── Core logic ────────────────────────────────────────────────────

def scan_and_import() -> dict:
    """Scan download dir, import new files, move to _imported.
    
    Returns: {"imported": N, "skipped": N, "errors": N, "total": N}
    """
    stats = {"imported": 0, "skipped": 0, "errors": 0, "total": 0}

    if not WIN_DOWNLOAD_DIR.exists():
        log(f"Download dir not found: {WIN_DOWNLOAD_DIR}")
        return stats

    # Find all .txt files recursively, excluding _imported subdirs
    txt_files = []
    for f in WIN_DOWNLOAD_DIR.rglob("*.txt"):
        # Skip files already in _imported
        if IMPORTED_DIR_NAME in f.parts:
            continue
        txt_files.append(f)

    if not txt_files:
        return stats

    stats["total"] = len(txt_files)
    log(f"Found {len(txt_files)} file(s) to process")

    for filepath in sorted(txt_files):
        parsed = parse_filename(filepath)
        if parsed is None:
            log(f"  SKIP (unparseable): {filepath.name}")
            stats["skipped"] += 1
            move_to_imported(filepath)
            continue

        book_title, chapter_num, chapter_title = parsed

        try:
            text = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = filepath.read_text(encoding="gbk")
            except Exception:
                log(f"  ERROR (encoding): {filepath.name}")
                stats["errors"] += 1
                move_to_imported(filepath)
                continue

        # Strip any leading chapter title line the extension adds
        lines = text.strip().split("\n")
        if lines and lines[0].strip() in (chapter_title, f"第{chapter_num}章 {chapter_title}"):
            text = "\n".join(lines[1:]).strip()

        if len(text) < 50:
            log(f"  SKIP (too short): {filepath.name}")
            stats["skipped"] += 1
            move_to_imported(filepath)
            continue

        try:
            result = import_chapter(book_title, chapter_num, chapter_title, text)
            if result.get("skipped"):
                log(f"  SKIP (duplicate): {filepath.name}")
                stats["skipped"] += 1
            else:
                log(f"  OK: [{book_title}] ch{chapter_num} ← {filepath.name}")
                stats["imported"] += 1
        except Exception as e:
            log(f"  FAIL: {filepath.name} — {e}")
            stats["errors"] += 1

        move_to_imported(filepath)

    return stats


def move_to_imported(filepath: Path) -> None:
    """Move file to _imported subfolder (preserves book subfolder structure)."""
    # Relative path from WIN_DOWNLOAD_DIR
    rel = filepath.relative_to(WIN_DOWNLOAD_DIR)
    imported_path = WIN_DOWNLOAD_DIR / IMPORTED_DIR_NAME / rel
    imported_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(filepath), str(imported_path))
    except Exception as e:
        log(f"  WARN (move failed): {filepath.name} — {e}")


# ─── Utils ─────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not ADMIN_PASSWORD:
        print("ERROR: Set MOBILE_API_ADMIN_PASSWORD env var", file=sys.stderr)
        sys.exit(1)

    watch_mode = "--watch" in sys.argv

    if watch_mode:
        log(f"Starting watcher — polling every {POLL_INTERVAL}s")
        log(f"  Scan dir: {WIN_DOWNLOAD_DIR}")
        log(f"  Pipeline: {PIPELINE_BASE}")
        while True:
            try:
                stats = scan_and_import()
                if stats["total"] > 0:
                    log(f"Done: imported={stats['imported']} skipped={stats['skipped']} errors={stats['errors']}")
            except Exception as e:
                log(f"Scan error: {e}")
            time.sleep(POLL_INTERVAL)
    else:
        log(f"One-shot scan — {WIN_DOWNLOAD_DIR}")
        stats = scan_and_import()
        log(f"Done: total={stats['total']} imported={stats['imported']} skipped={stats['skipped']} errors={stats['errors']}")
        if stats["errors"] > 0:
            sys.exit(1)
