# Ebook Duplicate Book Confirmation Design

**Status:** Approved for implementation planning

**Date:** 2026-07-12

## Purpose

Warn operators clearly when an ebook preview resolves to a story that already exists in the Library, and require explicit confirmation before importing chapters into that existing book.

The feature prevents an operator from unintentionally merging a second ebook into an existing story merely because the titles match. It preserves the current chapter-level `skip`, `error`, and `overwrite` strategies after the book-level merge has been confirmed.

## Current Behavior

The ebook import service already resolves an existing book when:

- the operator explicitly chooses a target book; or
- no target is selected and an existing Library title matches the parsed ebook title.

Preview dry-run metadata currently includes a nullable `target_book_id` and chapter counts. The UI shows new and duplicate chapter counts, but it does not clearly state that the target story already exists or require book-level merge confirmation.

As a result, the default `skip` strategy can silently merge new chapters into an existing story while skipping matching chapter numbers. The operator may interpret this as importing a new book.

## Scope

This change covers translated ebook preview and import through upload, staged preview upload, and server inbox paths. Both synchronous and job-backed ebook import endpoints enforce the same confirmation contract.

This change does not alter book identity, title normalization, chapter duplicate strategies, chapter text, cover behavior, ebook parsing, import history schema, Library merging outside ebook import, or job architecture.

## Selected Interaction

After Preview resolves an existing target, the Import panel displays an inline warning with `role="alert"`:

> Truyện này đã có trong Library. Ebook sẽ được gộp vào truyện hiện có.

The warning shows:

- existing story title;
- number of chapters currently in the target story;
- number of new chapters in the ebook;
- number of duplicate chapter numbers;
- the selected chapter strategy and its expected result.

The panel includes a required checkbox:

> Tôi xác nhận gộp ebook này vào truyện đã có.

The Import button remains disabled until the checkbox is selected. No modal, toast framework, or global notification system is introduced.

For automatic title matching, the copy says that the same story already exists. For an explicitly selected target, the copy says that the ebook will be merged into the selected existing story. This avoids describing two differently titled books as the same story.

## Preview Contract

The preview dry-run response gains:

- `existing_book_id: number | null`;
- `existing_book_title: string`;
- `existing_chapter_count: number`;
- `book_match_reason: "title" | "selected" | "new"`;
- `requires_existing_book_confirmation: boolean`.

Rules:

- automatic existing-title match uses `book_match_reason = "title"`;
- explicit target selection uses `book_match_reason = "selected"`;
- no existing target uses `book_match_reason = "new"`;
- confirmation is required whenever an existing book will receive imported chapters, even when `duplicate_chapters` is zero;
- no internal path or private chapter content enters this metadata.

The existing `target_book_id`, `target_title`, new/duplicate counts, and `would_*` fields remain for compatibility.

## Import Confirmation Contract

Ebook import requests gain optional `confirmed_existing_book_id`.

Before mutating files or database rows, the import service resolves the current target book using the established target/title matching behavior.

- If no existing book is resolved, confirmation is not required and a new book may be created normally.
- If an existing book is resolved, `confirmed_existing_book_id` must equal that resolved book ID.
- A missing or mismatched confirmation raises a dedicated duplicate-book confirmation error.
- If a book appears after Preview but before Import, the import is rejected and the operator must Preview and confirm again.
- If the explicit target changes after confirmation, the old confirmation cannot authorize the new target.

The API maps this validation failure to HTTP `409 Conflict` with a safe message instructing the operator to Preview and confirm again. Validation happens before cover publication, chapter file writes, database mutation, job creation, or import-history recording.

The same confirmed ID is carried into the background job parameters and passed to the import service. It is not treated as authorization outside the authenticated import request; existing authentication and ownership rules remain unchanged.

## Frontend State Rules

The Import panel stores the confirmed existing book ID, not a free boolean. The checkbox is considered valid only when its stored ID equals the latest preview's `existing_book_id`.

Confirmation resets when any input that can change the parsed book or target changes:

- selected upload file;
- selected server inbox file;
- staged upload/preview identity;
- split mode;
- explicit target book;
- chapter duplicate strategy;
- a new Preview response;
- leaving/resetting the ebook import flow.

Changing the chapter duplicate strategy triggers a refreshed Preview/dry run, updates the `would_skip`, `would_error`, or `would_overwrite` summary, and requires the operator to confirm the resulting action again.

If the API returns the confirmation conflict, the UI clears confirmation, retains the selected source where safe, shows the server message, and requires a fresh Preview.

## Data Flow

1. Operator selects or uploads an ebook and requests Preview.
2. Backend parses metadata and resolves the existing or new target without mutation.
3. Preview returns book-match metadata and chapter dry-run counts.
4. UI renders the existing-book warning and disables Import.
5. Operator reviews counts/strategy and checks the confirmation box.
6. UI sends `confirmed_existing_book_id` with the staged upload, inbox file, or upload request.
7. Backend resolves the target again and compares the confirmed ID before mutation.
8. Import proceeds using the existing `skip`, `error`, or `overwrite` chapter strategy.
9. Existing import result/history behavior remains unchanged.

## Error Handling

The feature distinguishes:

- existing book requires confirmation: HTTP 409 and fresh Preview required;
- confirmed ID no longer matches target: HTTP 409 and fresh Preview required;
- duplicate chapter strategy `error`: existing chapter-level conflict behavior;
- missing/expired staged upload: existing validation behavior;
- network uncertainty after job submission: existing job/history reconciliation remains separate from this feature.

Messages reveal only safe story-level metadata. They do not include filesystem paths, SQL details, tracebacks, or chapter text.

## Tests

Backend service and API tests cover:

- new story preview does not require confirmation;
- automatic same-title match returns existing-book metadata;
- explicitly selected target returns `selected` match reason;
- existing story with zero duplicate chapters still requires confirmation;
- import into an existing story without confirmation returns 409 before mutation;
- correct confirmed ID permits `skip`, `error`, and `overwrite` to behave as before;
- stale or mismatched confirmed ID returns 409 before mutation;
- staged upload and inbox job endpoints carry the confirmed ID;
- new story import remains backward compatible;
- response/error contains no internal path or private chapter content.

Frontend tests cover:

- warning renders after automatic existing-title Preview;
- explicit-target warning uses the correct wording;
- existing chapter/new/duplicate counts render;
- Import is disabled until confirmation;
- correct confirmed ID is sent in the request;
- confirmation resets after file, inbox, split-mode, target, or Preview changes;
- duplicate strategy changes update the summary and reset confirmation;
- 409 clears confirmation and requests a fresh Preview;
- new-story Preview does not show the warning or checkbox.

An integration test covers Preview of an already imported story, confirmation, and successful job submission without creating a second book.

## Security and Compatibility

- Authentication and ownership behavior remain unchanged.
- The confirmed ID is validated server-side and cannot select an inaccessible or nonexistent book.
- The server does not trust a client boolean or title string.
- Validation occurs before private artifact writes.
- Existing chapter content is changed only when the operator confirms the target and selects `overwrite`.
- Existing clients can continue importing genuinely new stories without the new field.
- Existing clients attempting to merge into an existing story must adopt the confirmation field and handle HTTP 409.

## Excluded Work

- fuzzy title matching or author-based identity redesign;
- schema changes to books or import history;
- automatic duplicate-book merge outside ebook import;
- undo/rollback UI;
- global toast or notification infrastructure;
- network-failure reconciliation for accepted import jobs;
- P1A backup metadata implementation, which remains paused while this feature is handled.

## Acceptance Criteria

The feature is complete when every ebook Preview that resolves an existing story produces an explicit warning, Import remains blocked until the exact existing book is confirmed, stale confirmation cannot authorize a changed target, backend validation happens before mutation, chapter duplicate strategies retain their existing semantics after confirmation, new-story imports remain compatible, and targeted/full verification passes without unrelated refactoring.
