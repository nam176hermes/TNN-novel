# P11 — ImportPanel Durable Job UX

## Scope

P11 connects the P10 `useImportJob` state machine to the existing URL preview
and chapter-selection workflow. Paste, file, ebook, catalog preview, legacy
callbacks, source policy, and the existing bypass badge remain compatible. The
milestone does not change backend routes, worker behavior, retry policy, or
source/browser handling.

## User flow

1. Preview a supported URL through the existing source preview endpoint.
2. Select individual chapters, the current 25-row page, or a chapter-number
   range.
3. Create the durable job with `createImportJob`; the UI immediately switches
   to the progress section without waiting for chapter downloads.
4. Reconcile persisted events through the P10 authoritative GET snapshot.
5. Cancel an active job, retry retryable failures, or return to Library after a
   terminal result.
6. Resume the latest non-terminal job from the P10 versioned `job_id` storage
   after a page refresh.

When the canonical client prop is absent, the old blocking chapter callback and
the old URL-start callback remain available for compatibility. The production
`App` now passes the canonical `ApiClient` and no longer wires the blocking
chapter-fetch callback.

## Progress presentation

The job summary exposes total, queued, running, succeeded, failed, cancelled,
and elapsed time. Each visible task exposes:

- chapter number/title, task status, and pipeline stage;
- attempts and safe fetch-method label;
- stored text length, elapsed time, and import operation;
- a safe Vietnamese message derived from `error_code`, never raw source HTML or
  chapter content.

Fetch-method copy is fixed to:

| Contract value | UI label |
|---|---|
| `direct_http` | Kết nối trực tiếp |
| `stealth_browser_headed` | Trình duyệt ẩn danh |
| `browser_session` | Phiên trình duyệt |
| `user_verification_required` | Cần xác minh thủ công |

The P09 snapshot does not yet guarantee a distinct operation field. The
frontend accepts an optional operation and otherwise displays the conservative
terminal label `Đã lưu`; it does not invent `created` versus `updated`.

## Large-list behavior

- Source selection renders 25 chapters per page.
- “Select visible” mutates only the current page and keeps selections on other
  pages.
- Chapter-number range selection works across the full preview without
  rendering every checkbox.
- Job task details render 20 rows per page.

This bounds DOM size for thousand-chapter books without adding a virtualization
dependency.

## Accessibility and mobile behavior

- Progress is a labelled `aria-live="polite"` region.
- Reconnecting is a non-error busy state; it does not relabel the durable job as
  failed.
- Terminal and error headings receive programmatic focus.
- Buttons expose disabled/loading copy, and primary controls use at least a
  44px target.
- Counts, task metadata, range selection, and actions collapse at 760px and
  420px without horizontal task-list overflow.

## Verification coverage

- non-blocking create flow from selected chapters;
- event-driven snapshot reconciliation and partial success;
- cancel and retry-failed actions;
- refresh/resume and reconnecting presentation;
- visible-page and chapter-range selection correctness;
- fetch-method/operation/error presentation;
- task pagination, live-region semantics, focus management, and labelled
  controls;
- the existing ImportPanel, P10 hook, and P09 client regressions.

Final verification results:

- durable ImportPanel job UX: `7 passed in 50.40s`;
- CSS layer/ownership regression: `13 passed in 44.13s`;
- complete frontend suite: `82 test files passed`, `731 tests passed in
  543.02s`;
- existing mocked Import wizard Chromium smoke: `1 passed in 12.7s`;
- repository lint wrapper: passed;
- frontend typecheck: passed;
- production build: passed with the pre-existing unresolved
  `sidebar-scenery.png` runtime-resolution warning.
