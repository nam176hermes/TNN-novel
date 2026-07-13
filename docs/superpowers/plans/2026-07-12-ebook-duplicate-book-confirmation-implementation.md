# Ebook Duplicate Book Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn when an ebook resolves to an existing Library story and require confirmation of that exact book before any import mutation or job creation.

**Architecture:** Centralize book-match metadata and confirmation validation in `EbookImportService`, using an exact existing book ID rather than a client boolean or title string. Preview returns safe match metadata; synchronous and job routes pass `confirmed_existing_book_id` and map a dedicated validation exception to HTTP 409. The Import panel binds its checkbox to the latest preview's existing book ID and resets it whenever source, target, split, strategy, or preview changes.

**Tech Stack:** Python 3.11, FastAPI multipart forms, SQLite helpers, pytest/httpx, React, TypeScript, Vitest/Testing Library.

## Global Constraints

- Preserve established title matching, book identity, chapter text, cover behavior, parsing, import history schema, and `skip|error|overwrite` semantics.
- Require confirmation for every resolved existing target, including zero duplicate chapter numbers and explicit target selection.
- Validate confirmation before cover publication, chapter file writes, database mutation, import-history recording, or job creation.
- Carry the confirmed ID into the background job and revalidate before background mutation to close the Preview-to-Import race.
- New-story imports remain backward compatible without a confirmation field.
- Missing or stale confirmation returns HTTP 409 with a safe message and no internal path, SQL detail, traceback, or chapter content.
- Do not add fuzzy identity matching, schema migrations, undo UI, global notifications, network-failure reconciliation, or unrelated refactoring.
- No new production dependencies.
- Tests use temporary databases and data directories; never use the operator database.
- P1A implementation remains paused until this feature is complete.

## File Map

- `app/mobile_api/services/ebook_import_service.py`: book-match descriptor, preview metadata, dedicated exception, preflight and mutation-time validation.
- `app/mobile_api/routers/import_routes.py`: multipart field, 409 mapping, pre-job validation, background propagation.
- `tests/test_ebook_import_service.py`: service-level match, confirmation, race, and mutation-safety tests.
- `tests/test_mobile_api_import_ebook.py`: route status, upload/staged/inbox/job behavior, and safe error tests.
- `web/src/api/types.ts`: preview and request contract.
- `web/src/api/client.ts`: append confirmed existing book ID to import forms.
- `web/src/api/client.test.ts`: multipart contract tests.
- `web/src/components/ImportPanel.tsx`: warning, bound confirmation state, reset rules, disabled action.
- `web/src/components/ImportPanel.test.tsx`: UI behavior and request payload tests.
- `web/src/App.integration.test.tsx`: end-to-end component flow for existing and new books.

---

### Task 1: Add service-level book-match metadata and confirmation validation

**Files:**
- Modify: `app/mobile_api/services/ebook_import_service.py:768-1020`
- Test: `tests/test_ebook_import_service.py`

**Interfaces:**
- Produces `ExistingBookConfirmationRequired(ValueError)`
- Produces `_book_match_for_parsed(parsed: ParsedEbook, target_book_id: int | None) -> dict[str, Any]`
- Produces `_assert_existing_book_confirmed(match: dict[str, Any], confirmed_existing_book_id: int | None) -> None`
- Produces `validate_existing_book_confirmation(file_path: Path, *, target_book_id: int | None, split_mode: str, original_filename: str, confirmed_existing_book_id: int | None) -> None`
- Extends `import_translated_ebook(..., confirmed_existing_book_id: int | None = None)`
- Extends preview `dry_run` with `existing_book_id`, `existing_book_title`, `existing_chapter_count`, `book_match_reason`, `requires_existing_book_confirmation`

- [ ] **Step 1: Write failing preview metadata tests**

Add service tests using `write_minimal_epub()` and `temp_db_path`:

```python
def test_preview_reports_automatic_existing_book_match(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")

    preview = service.preview(ebook)

    assert preview["dry_run"] | {
        "existing_book_id": first["book_id"],
        "existing_book_title": "Phàm Nhân Tu Tiên",
        "existing_chapter_count": 2,
        "book_match_reason": "title",
        "requires_existing_book_confirmation": True,
    } == preview["dry_run"]


def test_preview_reports_new_and_explicit_target_matches(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    fresh = service.preview(ebook)["dry_run"]
    assert fresh["book_match_reason"] == "new"
    assert fresh["requires_existing_book_confirmation"] is False
    existing_id = add_book(temp_db_path, "Truyện đích", "", "ebook", "")
    selected = service.preview(ebook, target_book_id=existing_id)["dry_run"]
    assert selected["existing_book_id"] == existing_id
    assert selected["book_match_reason"] == "selected"
    assert selected["requires_existing_book_confirmation"] is True
```

Use individual assertions if dictionary-union style obscures failures. Add a target with zero overlapping chapter numbers and assert confirmation remains required.

- [ ] **Step 2: Run tests and confirm missing fields**

Run: `.venv/bin/python -m pytest tests/test_ebook_import_service.py -k 'existing_book_match or explicit_target_matches' -q`

Expected: FAIL because match fields do not exist.

- [ ] **Step 3: Implement one book-match descriptor used by Preview and Import**

Import `list_chapters` from the database helper module and add:

```python
class ExistingBookConfirmationRequired(ValueError):
    pass


def _book_match_for_parsed(self, parsed: ParsedEbook, target_book_id: int | None) -> dict[str, Any]:
    if target_book_id is not None:
        book = get_book_by_id(self.db_path, target_book_id)
        if not book:
            raise ValueError(f"Book {target_book_id} not found")
        reason = "selected"
    else:
        book = get_book_by_title(self.db_path, parsed.title)
        reason = "title" if book else "new"
    existing_id = int(book["id"]) if book else None
    return {
        "existing_book_id": existing_id,
        "existing_book_title": str(book.get("title") or parsed.title) if book else "",
        "existing_chapter_count": len(list_chapters(self.db_path, existing_id)) if existing_id else 0,
        "book_match_reason": reason,
        "requires_existing_book_confirmation": existing_id is not None,
    }
```

Make `_dry_run_for_parsed()` call this helper once, use `existing_book_id` for duplicate counts, and merge the five fields into its return value. Keep existing dry-run fields unchanged.

- [ ] **Step 4: Write failing no-mutation confirmation tests**

```python
def test_existing_book_import_requires_exact_confirmation_before_mutation(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")
    before_raw = sorted((tmp_path / "data" / "raw").glob("*"))
    before_runs = list_ebook_import_runs(temp_db_path)

    with pytest.raises(ExistingBookConfirmationRequired):
        service.import_translated_ebook(ebook, duplicate_strategy="skip")
    with pytest.raises(ExistingBookConfirmationRequired):
        service.import_translated_ebook(ebook, duplicate_strategy="skip", confirmed_existing_book_id=first["book_id"] + 1)

    assert sorted((tmp_path / "data" / "raw").glob("*")) == before_raw
    assert list_ebook_import_runs(temp_db_path) == before_runs


def test_exact_existing_book_confirmation_preserves_duplicate_strategy(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")
    second = service.import_translated_ebook(ebook, duplicate_strategy="skip", confirmed_existing_book_id=first["book_id"])
    assert second["imported_chapters"] == 0
    assert second["skipped_chapters"] == 2
```

- [ ] **Step 5: Implement validation before all mutation**

```python
def _assert_existing_book_confirmed(self, match: dict[str, Any], confirmed_existing_book_id: int | None) -> None:
    existing_id = match["existing_book_id"]
    if existing_id is not None and confirmed_existing_book_id != existing_id:
        raise ExistingBookConfirmationRequired(
            "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
        )
```

In `import_translated_ebook()`, parse, build match, assert confirmation, and only then call `_raise_if_unreadable`, `_save_cover`, file writers, DB writers, or history recording. Resolve `book_id` from the confirmed match or create a new book. Add `validate_existing_book_confirmation()` that parses, builds the match, and asserts without mutation; job routes use it before creating a tracker job.

- [ ] **Step 6: Run service tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ebook_import_service.py -k 'preview or confirmation or duplicate' -q
.venv/bin/python -m pytest tests/test_ebook_import_service.py -q
```

Expected: PASS after updating existing repeat-import tests to pass the first result's `book_id`; new-story tests remain unchanged.

- [ ] **Step 7: Commit**

```bash
git add app/mobile_api/services/ebook_import_service.py tests/test_ebook_import_service.py
git commit -m "feat: require existing ebook target confirmation"
```

---

### Task 2: Enforce confirmation in synchronous and job API routes

**Files:**
- Modify: `app/mobile_api/routers/import_routes.py:365-450,557-691`
- Test: `tests/test_mobile_api_import_ebook.py`

**Interfaces:**
- Consumes `ExistingBookConfirmationRequired` and service methods from Task 1
- Multipart field `confirmed_existing_book_id: int | None`
- HTTP 409 detail: fixed safe confirmation message
- Background runner parameter `confirmed_existing_book_id: int | None`

- [ ] **Step 1: Write failing synchronous and staged-job API tests**

```python
@pytest.mark.asyncio
async def test_existing_ebook_requires_confirmation_before_sync_import(override_ebook_service: EbookImportService) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await auth_headers(client)
        first = await client.post("/api/import/ebook", data={"duplicate_strategy": "error"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")}, headers=headers)
        missing = await client.post("/api/import/ebook", data={"duplicate_strategy": "skip"},
            files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")}, headers=headers)
        confirmed = await client.post("/api/import/ebook", data={
            "duplicate_strategy": "skip", "confirmed_existing_book_id": str(first.json()["book_id"]),
        }, files={"file": ("translated.epub", minimal_epub_bytes(), "application/epub+zip")}, headers=headers)
    assert first.status_code == 200
    assert missing.status_code == 409
    assert confirmed.status_code == 200
```

Add a staged preview/job test asserting missing or mismatched confirmation returns 409 and no new job appears, while the correct ID returns 200. Add inbox coverage and assert response text contains no `/home/`, `/mnt/`, traceback, or chapter sample.

- [ ] **Step 2: Run route tests and verify old API accepts missing confirmation**

Run: `.venv/bin/python -m pytest tests/test_mobile_api_import_ebook.py -k 'requires_confirmation or confirmed_existing' -q`

Expected: FAIL because routes ignore the new field.

- [ ] **Step 3: Add typed form field and dedicated exception mapping**

Import `ExistingBookConfirmationRequired`. Add `confirmed_existing_book_id: int | None = Form(default=None)` to `/ebook` and `/ebook/job`. Pass it to service calls. Catch the dedicated exception before broad `ValueError` and return HTTP 409 with its safe detail; do not detect confirmation errors by string matching.

- [ ] **Step 4: Validate before job creation and revalidate in background**

Before `tracker.create_job()`, call:

```python
service.validate_existing_book_confirmation(
    ebook_path,
    target_book_id=target_book_id,
    split_mode=split_mode,
    original_filename=original_name,
    confirmed_existing_book_id=confirmed_existing_book_id,
)
```

On failure, return 409 without creating a job or deleting a reusable staged upload. If the request supplied a new direct upload, delete that request-scoped temporary file on preflight failure; inbox files and staged preview uploads remain untouched. Include the confirmed ID in safe in-memory job params, pass it into `_run_translated_ebook_import_job()`, and pass it again to `service.import_translated_ebook()` so a target change after job creation fails before background mutation.

- [ ] **Step 5: Run import API and job regressions**

Run:

```bash
.venv/bin/python -m pytest tests/test_mobile_api_import_ebook.py -q
.venv/bin/python -m pytest tests/test_job_service_logic.py -q
```

Expected: PASS; update existing duplicate-import fixtures with explicit confirmed IDs, while first/new imports remain unchanged.

- [ ] **Step 6: Commit**

```bash
git add app/mobile_api/routers/import_routes.py tests/test_mobile_api_import_ebook.py
git commit -m "fix: reject unconfirmed duplicate ebook jobs"
```

---

### Task 3: Add typed client contract and bound confirmation UI

**Files:**
- Modify: `web/src/api/types.ts:670-745`
- Modify: `web/src/api/client.ts:410-450`
- Modify: `web/src/components/ImportPanel.tsx:320-400,600-750,960-1210,1320-1460`
- Test: `web/src/api/client.test.ts:400-510`
- Test: `web/src/components/ImportPanel.test.tsx:400-570`

**Interfaces:**
- Adds `EbookBookMatchReason = 'title' | 'selected' | 'new'`
- Adds five dry-run match fields from Task 1
- Adds `confirmedExistingBookId?: number | null` to `EbookImportRequest`
- Produces UI state `confirmedExistingBookId: number | null`

- [ ] **Step 1: Write failing client multipart test**

Extend the existing job request test:

```typescript
await client.startTranslatedEbookImportJob({
  uploadId: 'upload-1',
  duplicateStrategy: 'skip',
  confirmedExistingBookId: 7,
});
const body = fetchMock.mock.calls[0][1]?.body as FormData;
expect(body.get('confirmed_existing_book_id')).toBe('7');
```

Also assert the field is absent for a new-story request.

- [ ] **Step 2: Write failing UI warning/disable/confirmation tests**

Use a preview fixture with `existing_book_id: 7`, title, existing count, `book_match_reason: 'title'`, and `requires_existing_book_confirmation: true`:

```tsx
expect(await screen.findByRole('alert')).toHaveTextContent('Truyện này đã có trong Library');
expect(screen.getByText(/43 chương mới/)).toBeVisible();
expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeDisabled();
await userEvent.click(screen.getByLabelText('Tôi xác nhận gộp ebook này vào truyện đã có.'));
expect(screen.getByRole('button', { name: 'Import vào Library' })).toBeEnabled();
await userEvent.click(screen.getByRole('button', { name: 'Import vào Library' }));
expect(onImportTranslatedEbook).toHaveBeenCalledWith(expect.objectContaining({ confirmedExistingBookId: 7 }));
```

Add tests for explicit-target wording, zero duplicates, new story without warning, and confirmation reset after file, inbox, split mode, target, duplicate strategy, or refreshed preview changes.

- [ ] **Step 3: Run client/component tests and verify failure**

Run: `npm --prefix web test -- client.test.ts ImportPanel.test.tsx`

Expected: FAIL for missing fields/state/UI.

- [ ] **Step 4: Extend TypeScript types and multipart body**

```typescript
export type EbookBookMatchReason = 'title' | 'selected' | 'new';

export type EbookImportDryRun = {
  // existing fields remain
  existing_book_id: number | null;
  existing_book_title: string;
  existing_chapter_count: number;
  book_match_reason: EbookBookMatchReason;
  requires_existing_book_confirmation: boolean;
};
```

Add `confirmedExistingBookId?: number | null` to `EbookImportRequest`. In `translatedEbookImportBody()`, append `confirmed_existing_book_id` only when non-null.

- [ ] **Step 5: Implement bound confirmation and reset rules**

Add:

```typescript
const [confirmedExistingBookId, setConfirmedExistingBookId] = useState<number | null>(null);
const existingBookId = ebookPreview?.dry_run?.existing_book_id ?? null;
const requiresExistingBookConfirmation = Boolean(ebookPreview?.dry_run?.requires_existing_book_confirmation);
const existingBookConfirmed = !requiresExistingBookConfirmation || confirmedExistingBookId === existingBookId;
```

Include `existingBookConfirmed` in `canSubmit` for ebook mode and set the action status to `Xác nhận gộp ebook vào truyện đã có trước khi import.` when blocked. Set confirmation to `null` at the start of both preview functions and in every file/source/inbox/split/target/duplicate handler. Send `confirmedExistingBookId` only when it equals the latest preview ID.

- [ ] **Step 6: Render the inline alert and checkbox**

Under the dry-run summary, render only when confirmation is required:

```tsx
<section className="ebook-preview-warnings" role="alert">
  <h5>{dryRun.book_match_reason === 'title' ? 'Truyện này đã có trong Library' : 'Sẽ gộp vào truyện đã chọn'}</h5>
  <p>{dryRun.existing_book_title} · {dryRun.existing_chapter_count.toLocaleString('vi-VN')} chương hiện có</p>
  <p>{dryRun.new_chapters.toLocaleString('vi-VN')} chương mới · {dryRun.duplicate_chapters.toLocaleString('vi-VN')} chương trùng</p>
  <label>
    <input checked={confirmedExistingBookId === dryRun.existing_book_id}
      onChange={(event) => setConfirmedExistingBookId(event.target.checked ? dryRun.existing_book_id : null)}
      type="checkbox" />
    <span>Tôi xác nhận gộp ebook này vào truyện đã có.</span>
  </label>
</section>
```

Use text rendering only; do not add modal, toast infrastructure, or raw HTML.

- [ ] **Step 7: Run frontend tests, typecheck, and build**

```bash
npm --prefix web test -- client.test.ts ImportPanel.test.tsx
npm --prefix web run typecheck
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/api/client.test.ts web/src/components/ImportPanel.tsx web/src/components/ImportPanel.test.tsx
git commit -m "feat: confirm ebook merge in import preview"
```

---

### Task 4: Cover App integration, stale conflicts, and full verification

**Files:**
- Modify: `web/src/App.integration.test.tsx:315-475`
- Modify: `web/src/App.tsx:1300-1350`
- Test: `tests/test_mobile_api_import_ebook.py`

**Interfaces:**
- Consumes all prior contracts
- Produces verified existing-story Preview → confirm → job flow without duplicate book creation

- [ ] **Step 1: Add failing App integration flow for an existing story**

Make `/api/books` return book ID 101. Make preview return the five match fields and dry-run counts. Assert the job FormData contains `confirmed_existing_book_id=101`; assert the import button is disabled before checking confirmation; then complete the existing job/event assertions.

Add a second integration test where the job endpoint returns HTTP 409. Assert the UI shows the safe message, remains on Import, clears the confirmation checkbox, and does not switch to Jobs.

- [ ] **Step 2: Run integration test and confirm failure**

Run: `npm --prefix web test -- App.integration.test.tsx`

Expected: FAIL until the existing fixture and 409 state behavior match the new contract.

- [ ] **Step 3: Implement minimal 409 reset hook if component state does not already reset**

In `App.handleImportTranslatedEbook()`, keep `handleJobError(error, 'Import ebook failed')` and then rethrow so the child can reconcile its confirmation state. In `ImportPanel.submitTranslatedEbook()`, catch the rejection, set `confirmedExistingBookId(null)`, set `ebookPreview(null)`, set `ebookPreviewState('error')`, and set `ebookPreviewError(errorMessage(error))`. Do not add global notification infrastructure; the existing global error and local Preview-required state may show the same safe cause in their established surfaces.

- [ ] **Step 4: Add race and no-duplicate-book backend assertions**

In route tests, Preview a new title, create the same title through the test database before import, then submit without confirmation and require HTTP 409 with zero new chapter/artifact/history mutations. In the confirmed integration path, compare `list_books()` before/after and require a single normalized book entry.

- [ ] **Step 5: Run all targeted checks**

```bash
.venv/bin/python -m pytest tests/test_ebook_import_service.py tests/test_mobile_api_import_ebook.py -q
npm --prefix web test -- client.test.ts ImportPanel.test.tsx App.integration.test.tsx
npm --prefix web run typecheck
npm --prefix web run build
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Run repository-wide verification**

Run: `scripts/verify.sh`

Expected: PASS. Confirm no paid provider call, live import, operator database access, generated ebook artifact, or secret occurred during tests.

- [ ] **Step 7: Commit final integration adjustments**

```bash
git add web/src/App.tsx web/src/App.integration.test.tsx tests/test_mobile_api_import_ebook.py
git commit -m "test: verify duplicate ebook confirmation flow"
```

Omit `web/src/App.tsx` when no production adjustment was required.

- [ ] **Step 8: Confirm clean handoff**

Run:

```bash
git status --short
git log --oneline --decorate -7
```

Expected: clean worktree and four focused feature commits after the design/plan commits.

## Final Acceptance Checklist

- [ ] Automatic same-title and explicit-target previews identify the existing story safely.
- [ ] Existing target with zero duplicate chapter numbers still requires confirmation.
- [ ] Import is disabled until the latest exact existing book ID is confirmed.
- [ ] File, source, inbox, split, target, strategy, and Preview changes reset confirmation.
- [ ] Missing/stale confirmation returns 409 before mutation or job creation.
- [ ] Background job revalidates confirmation before mutation.
- [ ] New-story import remains backward compatible.
- [ ] `skip`, `error`, and `overwrite` retain their chapter-level behavior after confirmation.
- [ ] No second book is created in the confirmed same-story integration flow.
- [ ] No internal paths, SQL detail, traceback, or private chapter content appears in errors.
- [ ] Targeted tests, typecheck, build, full verification, and `git diff --check` pass.
