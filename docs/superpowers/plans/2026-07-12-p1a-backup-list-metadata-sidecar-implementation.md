# P1A Backup List Metadata and Sidecar Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authenticated backup listing sidecar-only, bounded, and fast; add explicit dry-run sidecar repair; preserve archive bytes, restore compatibility, protected downloads, and operator database state.

**Architecture:** Split bounded external-sidecar parsing from explicit archive inspection in `scripts/ops.py`. Normal listing classifies every backup independently using safe filenames, stat metadata, and sidecars only. Creation and repair publish compact sidecars atomically while the full internal manifest and restore format remain unchanged; API and UI consume only the safe summary.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, `tarfile`, `argparse`, pytest/httpx, React, TypeScript, Vitest/Testing Library, Playwright, Bash.

## Global Constraints

- Mark applied changes `P1A_FIX_APPLIED`; mark later architecture work `RECOMMENDATION_ONLY`.
- Normal `GET /api/system/backups` must never open, decompress, decrypt, checksum, or walk archive members.
- Do not modify archive bytes, restore format, operator database, book export, job runner, authentication, protected downloads, or path protections.
- Do not delete archives, perform a live restore, add restore UI, redesign Status, or implement job-backed creation.
- Repair defaults to dry-run; writes require `--apply`; valid sidecar replacement requires `--overwrite`.
- Do not expose absolute paths, passphrases, provider keys, raw errors, private member paths, or full checksum inventories.
- Only `READY` entries receive `download_url` and browser download controls.
- Sidecar publication must be same-directory atomic and leave no partial file.
- Tests use isolated backup/data/database directories; no new production dependency is allowed.
- Acceptance: current warm list below 250 ms and normal-list archive-open count exactly `0`.

## File Map

- `scripts/ops.py`: metadata parser/list, atomic writer, explicit inspection, repair command.
- `tests/test_ops_scripts.py`: listing, creation, repair, immutability, restore compatibility.
- `app/mobile_api/schemas/__init__.py`, `services/backup_service.py`, `routers/backups.py`: safe API contract.
- `tests/test_mobile_api_backups.py`: authenticated isolated API coverage.
- `web/src/api/types.ts`, `web/src/App.tsx`, `web/src/components/StatusSettingsView.tsx`: independent backup UI state.
- `web/src/components/StatusSettingsView.test.tsx`, `web/src/api/client.test.ts`: frontend contract tests.
- `scripts/benchmark_backup_listing.py`, `tests/test_benchmark_backup_listing.py`: reproducible benchmark.
- `docs/backup-metadata-sidecars.md`, `docs/p1a-backup-list-implementation-note.md` and existing runbooks: operator evidence.

---

### Task 1: Implement bounded sidecar-only listing

**Files:**
- Modify: `scripts/ops.py:26-31,480-522`
- Test: `tests/test_ops_scripts.py`

**Interfaces:**
- Produces `backup_sidecar_path(archive_path: Path) -> Path`
- Produces `read_backup_sidecar(archive_path: Path) -> dict[str, Any]`
- Produces `list_backups(out_dir: Path | None = None) -> list[dict[str, Any]]`
- Item fields: existing summary fields plus `metadata_status`, `repair_needed`, `manifest_available`, `archive_available`, `warning`

- [ ] **Step 1: Write failing metadata-state and zero-archive-open tests**

Add imports `json` and fixtures covering valid, missing, malformed, orphan, zero-byte, unsupported, unrelated, oversized, unreadable, and symlink entries. The core regression test is:

```python
def test_list_backups_never_opens_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    ready.write_bytes(b"artifact")
    ready.with_suffix(ready.suffix + ops.BACKUP_MANIFEST_SUFFIX).write_text(json.dumps({
        "backup_format_version": 2,
        "created_at": "2026-07-12T10:00:00",
        "encrypted": False,
        "secrets_included": False,
        "included_modules": ["database"],
        "excluded_modules": ["secrets"],
        "file_count": 1,
        "total_size_bytes": 8,
        "checksums": [{"path": "data/private.txt", "sha256": "a" * 64}],
    }), encoding="utf-8")
    missing = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz"
    missing.write_bytes(b"large-content-is-irrelevant")
    monkeypatch.setattr(ops.tarfile, "open", lambda *a, **k: pytest.fail("listing opened archive"))

    items = {item["filename"]: item for item in ops.list_backups(tmp_path)}

    assert items[ready.name]["metadata_status"] == "READY"
    assert items[missing.name]["metadata_status"] == "METADATA_MISSING"
    assert "checksums" not in items[ready.name]["manifest"]
    assert "private.txt" not in json.dumps(items)
```

Assert malformed sidecar is `METADATA_INVALID`, orphan sidecar is `ARTIFACT_MISSING`, zero-byte artifact is `ARTIFACT_INVALID`, backup-prefixed `.zip` is `UNSUPPORTED_FORMAT`, unrelated files are absent, and one failure does not hide other entries.

- [ ] **Step 2: Verify the old implementation fails**

Run: `.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'list_backups or backup_sidecar' -q`

Expected: FAIL because new statuses do not exist and missing sidecar invokes the monkeypatched archive open.

- [ ] **Step 3: Add strict bounded parsing helpers**

Implement:

```python
BACKUP_SIDECAR_SCHEMA_VERSION = 1
MAX_BACKUP_SIDECAR_BYTES = 8 * 1024 * 1024
SAFE_MANIFEST_FIELDS = {
    "app_name", "app_version", "artifact_state", "archive_checksum",
    "archive_size_bytes", "backup_filename", "backup_format_version",
    "created_at", "encrypted", "excluded_modules", "file_count",
    "included_modules", "manifest_version", "secrets_included",
    "sidecar_schema_version", "total_size_bytes",
}


def backup_sidecar_path(archive_path: Path) -> Path:
    return archive_path.with_suffix(archive_path.suffix + BACKUP_MANIFEST_SUFFIX)


def read_backup_sidecar(archive_path: Path) -> dict[str, Any]:
    sidecar = backup_sidecar_path(archive_path)
    stat = sidecar.lstat()
    if sidecar.is_symlink() or not sidecar.is_file() or stat.st_size > MAX_BACKUP_SIDECAR_BYTES:
        raise ValueError("invalid backup sidecar")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("backup sidecar must be an object")
    return _safe_manifest_summary(payload)
```

Add `_safe_manifest_summary()` with strict bool/int/string/list checks, length bounds, module identifiers without separators, and an allowlisted result. Do not return `checksums`, `database`, project names, or directory names.

- [ ] **Step 4: Replace `list_backups()` with independent stat/sidecar classification**

Enumerate supported archives, recognized orphan sidecars, and backup-prefixed unsupported artifacts. Use `lstat`, fixed safe warnings, deterministic newest-first sorting, and per-entry exception isolation. Never call `read_backup_manifest()` or any archive inspector.

- [ ] **Step 5: Run focused and full ops tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'list_backups or backup_sidecar' -q
.venv/bin/python -m pytest tests/test_ops_scripts.py -q
```

Expected: listing tests PASS with zero archive access; unrelated existing failures must be documented before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/ops.py tests/test_ops_scripts.py
git commit -m "fix: make backup listing metadata only"
```

---

### Task 2: Publish compact sidecars atomically

**Files:**
- Modify: `scripts/ops.py:236-459`
- Test: `tests/test_ops_scripts.py`

**Interfaces:**
- Consumes `backup_sidecar_path()` and safe summary contract from Task 1
- Produces `build_backup_sidecar(manifest: dict[str, Any], archive_path: Path) -> dict[str, Any]`
- Produces `write_backup_sidecar_atomic(archive_path: Path, metadata: dict[str, Any]) -> Path`
- Preserves full internal `manifest.json`

- [ ] **Step 1: Write failing compact and atomic-publication tests**

```python
def test_create_backup_writes_compact_sidecar(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "chapter.txt").write_text("private", encoding="utf-8")
    archive = ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups", record_event=False)
    sidecar = ops.backup_sidecar_path(archive)
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["sidecar_schema_version"] == 1
    assert metadata["backup_filename"] == archive.name
    assert metadata["archive_size_bytes"] == archive.stat().st_size
    assert metadata["artifact_state"] == "READY"
    assert "checksums" not in metadata
    assert "chapter.txt" not in sidecar.read_text(encoding="utf-8")


def test_atomic_sidecar_failure_cleans_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    archive.write_bytes(b"artifact")
    monkeypatch.setattr(ops.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        ops.write_backup_sidecar_atomic(archive, {"sidecar_schema_version": 1})
    assert not ops.backup_sidecar_path(archive).exists()
    assert list(tmp_path.glob("*.tmp")) == []
```

Add an encrypted-backup test proving the encrypted sidecar is compact, contains no passphrase, and is published before plain files are removed.

- [ ] **Step 2: Verify direct `write_text` fails the new tests**

Run: `.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'compact_sidecar or atomic_sidecar or encrypted' -q`

Expected: FAIL because current sidecars duplicate `checksums` and publish non-atomically.

- [ ] **Step 3: Implement compact metadata and atomic write**

```python
def build_backup_sidecar(manifest: dict[str, Any], archive_path: Path) -> dict[str, Any]:
    return {
        "sidecar_schema_version": BACKUP_SIDECAR_SCHEMA_VERSION,
        "manifest_version": str(manifest.get("backup_format_version", "")),
        "backup_filename": archive_path.name,
        "backup_format_version": int(manifest.get("backup_format_version", 0)),
        "created_at": str(manifest.get("created_at", "")),
        "archive_size_bytes": archive_path.stat().st_size,
        "encrypted": bool(manifest.get("encrypted")),
        "secrets_included": bool(manifest.get("secrets_included")),
        "included_modules": list(manifest.get("included_modules", [])),
        "excluded_modules": list(manifest.get("excluded_modules", [])),
        "file_count": int(manifest.get("file_count", 0)),
        "total_size_bytes": int(manifest.get("total_size_bytes", 0)),
        "app_version": str(manifest.get("app_version", "")),
        "artifact_state": "READY",
    }


def write_backup_sidecar_atomic(archive_path: Path, metadata: dict[str, Any]) -> Path:
    sidecar = backup_sidecar_path(archive_path)
    fd, name = tempfile.mkstemp(prefix=f".{sidecar.name}.", suffix=".tmp", dir=sidecar.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, sidecar)
        return sidecar
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
```

Use it after plain archive completion and after encrypted artifact completion. Keep the full manifest inside the archive. Remove plain encrypted-source files only after encrypted sidecar publication succeeds.

- [ ] **Step 4: Run creation/encryption/restore tests**

Run: `.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'backup or restore' -q`

Expected: PASS; external sidecar is compact while internal `manifest.json` remains complete.

- [ ] **Step 5: Commit**

```bash
git add scripts/ops.py tests/test_ops_scripts.py
git commit -m "fix: publish compact backup sidecars atomically"
```

---

### Task 3: Add explicit archive inspection and repair CLI

**Files:**
- Modify: `scripts/ops.py:480-497,1029-1190`
- Test: `tests/test_ops_scripts.py`

**Interfaces:**
- Produces `inspect_backup_archive_explicitly(archive_path: Path, *, passphrase_env: str = "BACKUP_PASSPHRASE") -> dict[str, Any]`
- Produces `repair_backup_metadata(backup_dir: Path, *, filename: str | None, all_missing: bool, apply: bool, overwrite: bool, passphrase_env: str, report_dir: Path | None) -> dict[str, Any]`
- Produces CLI `backup-metadata-repair`

- [ ] **Step 1: Write failing repair/idempotency/immutability tests**

```python
def test_metadata_repair_dry_run_apply_and_idempotency(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "chapter.txt").write_text("source", encoding="utf-8")
    source = ops.create_backup(data_dir=data, out_dir=tmp_path / "source", record_event=False)
    rehearsal = tmp_path / "rehearsal"
    rehearsal.mkdir()
    archive = rehearsal / source.name
    shutil.copy2(source, archive)
    ops.backup_sidecar_path(archive).unlink(missing_ok=True)
    before = ops.sha256_file(archive)

    dry = ops.repair_backup_metadata(rehearsal, filename=archive.name, all_missing=False, apply=False, overwrite=False, passphrase_env="BACKUP_PASSPHRASE", report_dir=None)
    assert dry["would_write"] == 1
    assert not ops.backup_sidecar_path(archive).exists()
    first = ops.repair_backup_metadata(rehearsal, filename=archive.name, all_missing=False, apply=True, overwrite=False, passphrase_env="BACKUP_PASSPHRASE", report_dir=None)
    second = ops.repair_backup_metadata(rehearsal, filename=archive.name, all_missing=False, apply=True, overwrite=False, passphrase_env="BACKUP_PASSPHRASE", report_dir=None)
    assert first["written"] == 1
    assert second["written"] == 0
    assert second["skipped_valid"] == 1
    assert ops.sha256_file(archive) == before
```

Also test corrupt plain archive, encrypted archive without passphrase environment, no overwrite of valid sidecar, explicit overwrite, unsafe filename, atomic cleanup, report redaction, and CLI dry-run defaults.

- [ ] **Step 2: Verify functions and command are absent**

Run: `.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'metadata_repair or inspect_backup_archive' -q`

Expected: FAIL for missing repair interfaces.

- [ ] **Step 3: Isolate explicit archive inspection**

For plain archives, open with `tarfile.open(..., "r:gz")`, require a bounded regular `manifest.json`, validate member safety, parse a JSON object, and return the full internal manifest only to explicit callers. For `.enc`, obtain the passphrase only through `os.getenv(passphrase_env)`, decrypt with `openssl -pass env:<name>` into `TemporaryDirectory`, inspect recursively, capture subprocess output, and emit fixed safe errors. Add a test monkeypatching `inspect_backup_archive_explicitly` to fail and prove `list_backups()` never calls it.

- [ ] **Step 4: Implement safe repair selection and atomic reports**

Resolve/contain `backup_dir`; require a safe basename for `filename`; select exactly the named artifact or missing/invalid supported artifacts; inspect each independently; write only with `apply=True`; skip valid sidecars unless `overwrite=True`. Return and optionally publish JSON/Markdown containing safe filenames, states, and counts only.

- [ ] **Step 5: Wire argparse and main**

```python
repair = subparsers.add_parser("backup-metadata-repair", help="Repair compact backup metadata sidecars")
repair.add_argument("--backup-dir", type=Path, required=True)
selection = repair.add_mutually_exclusive_group(required=True)
selection.add_argument("--filename")
selection.add_argument("--all-missing", action="store_true")
mode = repair.add_mutually_exclusive_group()
mode.add_argument("--dry-run", action="store_true", default=True)
mode.add_argument("--apply", action="store_true")
repair.add_argument("--overwrite", action="store_true")
repair.add_argument("--passphrase-env", default="BACKUP_PASSPHRASE")
repair.add_argument("--report-dir", type=Path, default=None)
```

Call `repair_backup_metadata(..., apply=args.apply, ...)`; print safe JSON and return non-zero when selected entries fail. Never print or persist the environment value.

- [ ] **Step 6: Run repair and restore compatibility tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ops_scripts.py -k 'metadata_repair or inspect_backup_archive or backup_and_restore or restore_drill or parser' -q
```

Expected: PASS; dry-run writes zero, second apply writes zero, corrupt/encrypted failures are safe, archive hashes stay unchanged.

- [ ] **Step 7: Commit**

```bash
git add scripts/ops.py tests/test_ops_scripts.py
git commit -m "feat: add explicit backup sidecar repair"
```

---

### Task 4: Expose safe metadata through the authenticated API

**Files:**
- Modify: `app/mobile_api/schemas/__init__.py:616-633`
- Modify: `app/mobile_api/services/backup_service.py`
- Modify: `app/mobile_api/routers/backups.py`
- Test: `tests/test_mobile_api_backups.py`

**Interfaces:**
- Consumes Task 1 item fields and `metadata_status == "READY"`
- Preserves authenticated list/create/download and direct-download containment

- [ ] **Step 1: Write failing API contract and security tests**

Create isolated `READY` and `METADATA_MISSING` artifacts in `backup_service_fixture`, monkeypatch `ops.tarfile.open` to fail, authenticate, and assert:

```python
payload = list_response.json()["items"]
by_name = {item["filename"]: item for item in payload}
assert by_name[ready.name]["metadata_status"] == "READY"
assert by_name[ready.name]["download_url"].endswith("/download")
assert by_name[missing.name]["metadata_status"] == "METADATA_MISSING"
assert by_name[missing.name]["download_url"] == ""
assert "checksums" not in list_response.text
assert not re.search(r"/home/|/mnt/|[A-Za-z]:\\\\", list_response.text)
```

Also prove one malformed entry does not fail the response, unauthenticated list/download are denied, safe direct download still works for an existing legacy archive, traversal remains rejected, symlink escape is rejected, and backup list/download responses retain private non-cache headers. Search the PWA/service-worker configuration and add an assertion that `/api/system/backups*` is not included in a runtime cache rule; if no service worker route cache exists, record that verified absence in the implementation note.

- [ ] **Step 2: Run API tests and verify failures**

Run: `.venv/bin/python -m pytest tests/test_mobile_api_backups.py -q`

Expected: FAIL for missing schema fields and unconditional list download URL.

- [ ] **Step 3: Extend the Pydantic model and gate list URLs**

```python
class SystemBackupItem(BaseModel):
    filename: str
    size_bytes: int = 0
    created_at: str = ""
    encrypted: bool = False
    secrets_included: bool = False
    included_modules: list[str] = Field(default_factory=list)
    excluded_modules: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    metadata_status: str = "METADATA_MISSING"
    repair_needed: bool = False
    manifest_available: bool = False
    archive_available: bool = False
    warning: str = ""
    download_url: str = ""
```

In `BackupService.list_backups()`, attach `download_url` only to `READY`; force `""` otherwise. In `create_backup()`, require the newly published list item to be `READY` without inspecting the archive. Keep `resolve_download_path()` independent and preserve its existing authenticated direct-download behavior while testing regular-file and resolved-parent containment.

- [ ] **Step 4: Run API/security/ops regressions**

Run:

```bash
.venv/bin/python -m pytest tests/test_mobile_api_backups.py tests/test_mobile_api_security.py tests/test_ops_scripts.py -q
```

Expected: PASS; normal API list opens zero archives and returns no host paths/private manifests.

- [ ] **Step 5: Commit**

```bash
git add app/mobile_api/schemas/__init__.py app/mobile_api/services/backup_service.py app/mobile_api/routers/backups.py tests/test_mobile_api_backups.py
git commit -m "fix: expose safe backup metadata states"
```

---

### Task 5: Decouple backup list states in the existing Status UI

**Files:**
- Modify: `web/src/api/types.ts:263-280`
- Modify: `web/src/App.tsx:176-178,378-394,575-576,1920-1940`
- Modify: `web/src/components/StatusSettingsView.tsx`
- Test: `web/src/components/StatusSettingsView.test.tsx`
- Test: `web/src/api/client.test.ts:1213-1277`
- Test when isolated fixtures permit: `web/e2e/novel-tnn.spec.ts`

**Interfaces:**
- Produces props `backups`, `backupLoading`, `backupError`, `onReloadBackups`
- Preserves existing create/encrypted-create/download callbacks and core status state

- [ ] **Step 1: Write failing component tests for independent loading/error and READY-only download**

Extend fixtures with the five new fields and add:

```tsx
it('keeps core status visible while backup metadata fails', () => {
  render(<StatusSettingsView backupError="Không tải được metadata backup."
    backupLoading backups={[]} error="" loading={false}
    onRefresh={() => undefined} onReloadBackups={() => undefined} status={status} />);
  expect(screen.getByText('API Readiness')).toBeVisible();
  expect(screen.getByText('Đang tải danh sách backup')).toBeVisible();
  expect(screen.getByText('Không tải được metadata backup.')).toBeVisible();
});

it('warns for missing metadata and downloads only READY entries', () => {
  const missing = { ...latestBackup, filename: 'legacy.tar.gz', metadata_status: 'METADATA_MISSING',
    repair_needed: true, manifest_available: false, warning: 'Backup metadata is missing.', download_url: '' } satisfies SystemBackupItem;
  render(<StatusSettingsView backups={[latestBackup, missing]} error="" loading={false}
    onRefresh={() => undefined} onDownloadBackup={() => undefined} status={status} />);
  expect(screen.getByText('Backup metadata is missing.')).toBeVisible();
  expect(screen.getAllByRole('button', { name: 'Tải backup' })).toHaveLength(1);
  expect(screen.queryByRole('button', { name: /restore/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Verify tests fail**

Run: `npm --prefix web test -- StatusSettingsView.test.tsx client.test.ts`

Expected: FAIL for new types/props/states.

- [ ] **Step 3: Add the typed metadata status and list state**

```typescript
export type BackupMetadataStatus =
  | 'READY' | 'METADATA_MISSING' | 'METADATA_INVALID'
  | 'ARTIFACT_MISSING' | 'ARTIFACT_INVALID' | 'UNSUPPORTED_FORMAT';
```

Add `metadata_status`, `repair_needed`, `manifest_available`, `archive_available`, and `warning` to `SystemBackupItem`. Replace `latestBackup` state in `App.tsx` with `systemBackups: SystemBackupItem[]` and `backupLoading`. Rename `loadLatestBackup()` to `loadSystemBackups()`, clear stale errors before each request, preserve auth expiry, and set loading in `finally` independently of `systemStatus`.

- [ ] **Step 4: Render a narrow bounded backup list**

Update `StatusSettingsView` props. Keep the current panel layout and create controls; add loading, empty, error/reload, and compact entry states. Render `warning` as React text. Show repair guidance when `repair_needed`. Render download only for `metadata_status === 'READY' && download_url`. Do not add restore controls or `dangerouslySetInnerHTML`.

- [ ] **Step 5: Run frontend tests, typecheck, and build**

```bash
npm --prefix web test -- StatusSettingsView.test.tsx client.test.ts
npm --prefix web run typecheck
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 6: Add Playwright only if the existing suite can isolate API state**

If `web/e2e/novel-tnn.spec.ts` already intercepts authenticated APIs, delay/fail `/api/system/backups` and assert core status appears before the backup warning. Otherwise record E2E as not practical and do not launch it against operator data.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/types.ts web/src/App.tsx web/src/components/StatusSettingsView.tsx web/src/components/StatusSettingsView.test.tsx web/src/api/client.test.ts
git commit -m "fix: decouple backup metadata from system status"
```

Add `web/e2e/novel-tnn.spec.ts` only if changed.

---

### Task 6: Add a reproducible metadata-only benchmark

**Files:**
- Create: `scripts/benchmark_backup_listing.py`
- Create: `tests/test_benchmark_backup_listing.py`

**Interfaces:**
- Produces `run_benchmark(work_dir: Path, iterations: int = 5) -> dict[str, Any]`
- Scenario fields: `scenario`, `entry_count`, `directory_scan_ms`, `sidecar_read_ms`, `service_total_ms`, `archive_open_count`, `bytes_read`, `response_bytes`

- [ ] **Step 1: Write a failing benchmark smoke test**

```python
def test_benchmark_opens_zero_archives(tmp_path: Path) -> None:
    result = benchmark_backup_listing.run_benchmark(tmp_path, iterations=2)
    names = {row["scenario"] for row in result["scenarios"]}
    assert {"zero", "two_ready", "ten_ready", "missing", "malformed", "large_missing"} <= names
    assert all(row["archive_open_count"] == 0 for row in result["scenarios"])
```

- [ ] **Step 2: Verify module absence**

Run: `.venv/bin/python -m pytest tests/test_benchmark_backup_listing.py -q`

Expected: FAIL import/module not found.

- [ ] **Step 3: Implement isolated fixtures and metrics**

Create one temporary directory per scenario. Create the large fixture as a 512 MiB sparse file using `seek(size - 1); write(b"\0")`, never a real compressed archive. Instrument directory enumeration and sidecar byte reads separately, wrap `ops.tarfile.open` to count and raise, warm once, measure medians, and serialize response bytes. Provide CLI options `--work-dir`, `--iterations`, `--json-output`. Never inspect operator backups.

- [ ] **Step 4: Run test and benchmark, then clean staging**

```bash
.venv/bin/python -m pytest tests/test_benchmark_backup_listing.py -q
.venv/bin/python scripts/benchmark_backup_listing.py --work-dir .tmp/p1a-benchmark --iterations 5 --json-output .tmp/p1a-benchmark/results.json
rm -rf .tmp/p1a-benchmark
```

Expected: every scenario reports zero archive opens; no timing threshold is asserted in pytest.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_backup_listing.py tests/test_benchmark_backup_listing.py
git commit -m "test: benchmark metadata-only backup listing"
```

---

### Task 7: Rehearse repair, apply operator sidecars, and document evidence

**Files:**
- Create: `docs/backup-metadata-sidecars.md`
- Create: `docs/p1a-backup-list-implementation-note.md`
- Modify: `docs/backup-restore.md`
- Modify: `docs/deployment-hardening.md`
- Modify: `docs/backend-performance-measurements.md`
- Runtime only: `.tmp/p1a-backup-rehearsal/`, `.tmp/p1a-reports/`, operator sidecars

**Interfaces:**
- Consumes Tasks 1-6
- Produces non-secret rehearsal, idempotency, hash, restore-drill, and latency evidence

- [ ] **Step 1: Capture fresh no-auth preflight evidence**

Set `REPO_ROOT`, configured `DATA_DIR`, `BACKUP_DIR`, `REHEARSAL_DIR`, and `REPORT_DIR`. Record operator DB SHA-256/size/mtime and archive filename/size/SHA-256 into ignored JSON reports without printing absolute paths or report contents.

- [ ] **Step 2: Copy only missing-sidecar archives to rehearsal**

Select `METADATA_MISSING` entries through `ops.list_backups()`, copy them with `shutil.copy2`, and hash the copies. Do not copy the already-`READY` multi-gigabyte archive.

- [ ] **Step 3: Run dry-run, apply, second apply**

```bash
.venv/bin/python scripts/ops.py backup-metadata-repair --backup-dir "$REHEARSAL_DIR" --all-missing --dry-run --report-dir "$REPORT_DIR/dry-run"
.venv/bin/python scripts/ops.py backup-metadata-repair --backup-dir "$REHEARSAL_DIR" --all-missing --apply --report-dir "$REPORT_DIR/apply"
.venv/bin/python scripts/ops.py backup-metadata-repair --backup-dir "$REHEARSAL_DIR" --all-missing --apply --report-dir "$REPORT_DIR/idempotency"
```

Require dry-run writes zero, first apply repairs all valid selected archives, second apply writes zero, listing opens zero archives, hashes match, and no partial files remain. Stop on failure.

- [ ] **Step 4: Run isolated restore drill on the smallest repaired copy**

Run `.venv/bin/python scripts/ops.py restore-drill "$SMALLEST_REHEARSAL_ARCHIVE" --work-dir "$REHEARSAL_DIR/restore-drill"` and require `ok: true` plus SQLite integrity `ok`. This is not a live restore. Remove restored staging after recording safe results.

- [ ] **Step 5: Repair operator missing sidecars only after gates pass**

Run operator dry-run, apply, and second apply with the same command pattern against `$BACKUP_DIR`. Require every valid current archive `READY`, second apply zero writes, and all archive hashes unchanged. Do not use `--overwrite` unless separately reviewed and necessary for the latency target.

- [ ] **Step 6: Benchmark current inventory without live authentication**

Instantiate `BackupService` directly with configured directories, monkeypatch `ops.tarfile.open` to fail/count, warm once, and measure at least five calls. Record median/min/max, payload bytes, item count, bytes read, and archive opens. Require median below 250 ms and opens `0`.

- [ ] **Step 7: Verify DB and archive immutability**

Recompute operator DB SHA-256/size/mtime and every archive SHA-256; compare exactly with Step 1. Sidecar additions are allowed. Abort completion claims for unexplained mismatch.

- [ ] **Step 8: Write active documentation**

Document old/new flow, compact schema, six states, repair/encryption rules, repository-relative commands, rehearsal/idempotency counts, restore compatibility, performance, archive-open count, hash evidence, and synchronous creation as `RECOMMENDATION_ONLY` for P2C. Never include passphrases, host paths, or private manifest rows.

- [ ] **Step 9: Clean staging and commit docs**

```bash
rm -rf "$REHEARSAL_DIR" "$REPORT_DIR"
git add docs/backup-metadata-sidecars.md docs/p1a-backup-list-implementation-note.md docs/backup-restore.md docs/deployment-hardening.md docs/backend-performance-measurements.md
git commit -m "docs: record P1A backup metadata repair"
```

---

### Task 8: Run complete verification and finalize

**Files:**
- Modify only when final evidence changes: `docs/p1a-backup-list-implementation-note.md`, `docs/backend-performance-measurements.md`

**Interfaces:**
- Consumes all prior tasks
- Produces final evidence and clean worktree

- [ ] **Step 1: Run focused backend suites**

```bash
.venv/bin/python -m pytest tests/test_ops_scripts.py tests/test_benchmark_backup_listing.py tests/test_mobile_api_backups.py tests/test_mobile_api_security.py -q
```

Expected: PASS using isolated directories only.

- [ ] **Step 2: Run focused frontend suites and build**

```bash
npm --prefix web test -- StatusSettingsView.test.tsx client.test.ts
npm --prefix web run typecheck
npm --prefix web run build
```

Expected: PASS and no restore button.

- [ ] **Step 3: Run safe focused Playwright when implemented**

Run `npm --prefix web run test:e2e -- --grep "status.*backup"` only with isolated API fixtures. Otherwise record the exact limitation and do not use operator data.

- [ ] **Step 4: Run repository verification**

```bash
scripts/verify.sh
git diff --check
git status --short
```

Expected: full verification PASS; only intentional evidence edits remain.

- [ ] **Step 5: Re-run final immutability and redaction checks**

Recompute DB/archive evidence and compare with baseline. Search changed API/UI/docs for `/home/`, `/mnt/`, Windows absolute paths, passphrase values, provider keys, `checksums`, and raw manifest member names. Variable names without values are allowed in operator docs.

- [ ] **Step 6: Commit final evidence only if it changed**

```bash
git add docs/p1a-backup-list-implementation-note.md docs/backend-performance-measurements.md
git commit -m "docs: finalize P1A verification evidence"
```

- [ ] **Step 7: Confirm clean completion**

Run `git status --short` and `git log --oneline --decorate -8`. Require no staged/generated archive, sidecar, operator DB, secret, report, or build artifact.

## Final Acceptance Checklist

- [ ] Normal listing opens zero archives and is below 250 ms warm on current inventory.
- [ ] Missing/corrupt metadata remains visible and does not block other entries.
- [ ] Only `READY` entries expose browser download controls.
- [ ] Repair defaults to dry-run, is atomic and idempotent, and follows rehearsal gates.
- [ ] Operator database metadata and all archive hashes remain unchanged.
- [ ] Isolated restore drill remains compatible.
- [ ] Core Status remains usable while backup metadata loads or fails.
- [ ] Authentication, traversal, symlink, encryption, non-cache, and protected-download controls remain intact.
- [ ] No absolute path, secret, raw manifest, or private checksum inventory appears in API/UI/reports.
- [ ] Full verification/build passes or pre-existing failures are recorded exactly.
- [ ] P2C creation jobs, restore UI, format/retention redesign, and unrelated refactors are absent.
