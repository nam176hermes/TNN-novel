# Workstream 5 — Mobile Accessibility and Large-List Performance

## Outcome

Workstream 5 is complete in the isolated branch `repair/ws5-mobile-a11y-performance`.
It fixes A11Y-001, A11Y-002, and PERF-001 without changing backend, database,
job, browser-challenge, artifact, authentication, or TTS contracts. No production
container, configuration, data, ingress, provider, or GPU workload was touched.

Baseline:

- repository: `/home/thenam176/Novel-TNN`
- isolated worktree: `/home/thenam176/Novel-TNN-worktrees/ws5-mobile-a11y-performance`
- baseline commit: `ee48c37e27c1ab25e0f9c739892397a27da75af3`
- Python: 3.11.15 from `.venv`
- Node: 22.23.0
- npm: 10.9.8
- Playwright: 1.61.1
- Docker: 29.1.3; Compose: 2.40.3
- isolated mandatory baseline: 1,181 backend tests and 758 frontend tests passed

The external production environment file was supplied only to the repository's
read-only environment validator. `NOVEL_PIPELINE_IGNORE_DOTENV=1` remained set,
and all mutable tests used their normal isolated temporary databases and data
directories.

## Reproduction and root causes

### A11Y-001 — Reader and shell More dialogs

Reproduction tests initially showed that focus remained on the trigger after a
dialog opened. The Reader dialog also allowed its handled Escape event to reach
the Reader's global Escape shortcut, which could leave Reader instead of only
closing the dialog.

Root causes:

- no shared dialog focus lifecycle;
- no initial-focus target or Tab/Shift+Tab containment;
- no focus restoration or body-scroll ownership;
- Reader's global Escape handler did not ignore a previously handled event;
- Reader More lacked consistent backdrop-click behavior.

The shared `useDialogFocusLifecycle` hook now owns initial focus, containment,
Escape, restoration, and body scroll for both dialogs. Dialogs have an
accessible name and modal semantics. Reader Escape respects `defaultPrevented`.
Relevant mobile transitions honor reduced-motion preferences.

### A11Y-002 — visible mobile touch targets

The new browser regression probe reproduced controls below the 44 CSS-pixel
policy on Dashboard before the fix, including:

- Logout: `115 × 38`;
- system-status icon action: `40 × 40`;
- recent/system detail text actions: approximately `149–150 × 25`;
- Import now: `172 × 38`.

The audit also recorded undersized visible controls in Sources, Jobs, Status,
Dashboard, Reader More, and other dense surfaces. A shell-level mobile policy
now gives visible buttons, links, selects, text inputs, and textareas at least a
44-pixel hit area. It is intentionally applied after feature CSS so a later
compact feature rule cannot silently override it.

Approved exceptions:

- hidden and file inputs;
- native range tracks;
- native checkbox and radio glyph geometry.

Those controls use their visible label/container as the interaction area and
are excluded from the automated geometry probe. The exception does not include
ordinary visible buttons, links, selects, or text fields.

The browser test covers Dashboard, Jobs, Sources, Status/Settings, Reader More,
and Reader font settings, and verifies no horizontal overflow at `360×740`,
`390×844`, and `412×915`.

### PERF-001 — Glossary and Reader TOC

The pre-fix regression fixtures reproduced full materialization:

- 600 glossary terms produced 601 table rows;
- 700 translated chapters produced 700 TOC buttons.

The Hermes production-scale audit had measured:

- Glossary: 16,813 DOM nodes and 3,510 interactive elements;
- Reader TOC: 5,342 DOM nodes and 707 controls.

Both surfaces now use the dependency-free `useWindowedList` boundary. The hook
keeps only a viewport plus overscan in the DOM. Glossary rows stay in normal
table flow and measure their rendered average height, so multi-line and mobile
card rows do not overlap. Spacer rows are hidden from accessibility APIs.

Glossary preserves:

- table semantics and total `aria-rowcount`;
- search and status filtering across the complete dataset;
- row positions through `aria-rowindex`;
- editable fields, review, lock, and save actions;
- empty and no-match states;
- dynamic-height rows.

Reader TOC preserves:

- current chapter anchoring on open and reopen;
- first/latest shortcuts and direct selection;
- sort and unaccented search;
- long-title labels and `title` text;
- set position/size metadata;
- Arrow Up/Down and Home/End navigation across recycled windows;
- focus stability while search or sort controls are used.

Production-scale regression fixtures now render fewer than 50 rows/buttons for
600/700 records. The unit-test viewport normally materializes about 15 glossary
rows and 20 TOC buttons, but the contract deliberately asserts a safe upper
bound rather than an implementation-specific exact count. Live production DOM,
memory, and long-task measurements remain a post-deployment certification item;
this workstream did not deploy or read private chapter content.

## Files changed

- `web/src/hooks/useDialogFocusLifecycle.ts`
- `web/src/hooks/useWindowedList.ts`
- `web/src/components/WorkflowShell.tsx`
- `web/src/components/WorkflowShell.test.tsx`
- `web/src/components/ReaderView.tsx`
- `web/src/components/ReaderView.test.tsx`
- `web/src/components/GlossaryStyleView.tsx`
- `web/src/components/GlossaryStyleView.test.tsx`
- `web/src/components/reader/ReaderTocSheet.tsx`
- `web/src/components/reader/ReaderTocSheet.test.tsx`
- `web/src/styles/shell.css`
- `web/src/styles/reader.css`
- `web/src/styles/features.css`
- `web/e2e/novel-tnn.spec.ts`

## Commits

- `0f2d137 fix(a11y): implement reader dialog focus lifecycle`
- `8fa8fe5 fix(mobile): enlarge visible touch targets`
- `6177425 perf(glossary): virtualize large term list`
- `dee3033 perf(reader): virtualize chapter toc`
- `205093d fix(glossary): measure dynamic virtual rows`

The fifth focused commit is a post-implementation hardening found during review:
fixed row estimates were insufficient for tall mobile glossary cards, so the
window now measures rendered rows while preserving the logical scroll position.

## Verification evidence

Targeted and related checks:

```text
npm test -- src/components/WorkflowShell.test.tsx src/components/ReaderView.test.tsx
npm test -- src/components/GlossaryStyleView.test.tsx
npm test -- src/components/reader/ReaderTocSheet.test.tsx
npm run typecheck
npm run build
npm run test:e2e -- --grep "visible mobile controls"
npm run test:e2e
```

Results:

- dialog/Reader focused unit suite: 108/108 passed during implementation;
- Glossary tests: 8/8 passed;
- Reader TOC tests: 8/8 passed;
- full frontend suite: 85 files, 763 tests passed;
- typecheck passed;
- production frontend build passed (1,857 modules);
- Playwright: 11/11 scenarios passed, including dialog keyboard/touch behavior,
  mobile geometry, Reader raw/split, offline Reader, and no horizontal overflow.

Mandatory gate:

```text
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
NOVEL_PIPELINE_PRODUCTION_ENV_FILE=/home/thenam176/.config/novel-tnn/production.env \
scripts/verify.sh
```

Results:

- Python compile: pass;
- shell syntax: pass;
- environment and package consistency: pass;
- lint/typecheck: pass;
- backend: 1,181 passed, 2 pre-existing deprecation warnings;
- frontend: 763 passed;
- frontend production build: pass;
- aggregate mandatory gate: pass.

`git diff --check` also passed. Browser verification used the repository's local
Playwright suite because an interactive browser MCP was not available in this
session.

## Security, data, and rollback review

- No authenticated response, token, cookie, private content, filename, or
  production path is added to client caches or logs.
- No backend/API/database schema or artifact behavior changed.
- No source/challenge automation or network policy changed.
- No production state was modified and no migration is required.
- Rollback is code-only: revert the focused commit(s), rebuild, and rerun the
  frontend and mandatory gates. There is no data rollback step.

## Remaining limitations

- This workstream does not claim full WCAG conformance; screen-reader testing
  across multiple assistive technologies remains certification work.
- Live production memory, long-task, and DOM totals must be measured after an
  explicitly approved deployment. Current evidence uses the original audit
  measurements plus isolated production-scale fixtures.
- Virtual window estimates are deliberately approximate. Glossary dynamically
  measures visible rows; extreme row-height variance can still cause a small
  scrollbar adjustment but cannot materialize the complete dataset.
- No broad Reader or Glossary decomposition was attempted.

## Recommendation

**GO for operator review and merge of Workstream 5.**

**GO for Workstream 6 only after this branch is reviewed and merged.** Workstream
6 must remain controlled extraction in small batches; it must not use this
performance work as authorization for a broad Reader, Glossary, or CSS rewrite.
Production deployment was not part of this workstream and remains a separate
operator approval decision.
