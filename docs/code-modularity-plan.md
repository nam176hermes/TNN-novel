# Code Modularity Plan

## Answer
Yes. The codebase should be divided further, but not as a wholesale rewrite. The right move is to split the few largest modules that currently mix orchestration, business logic, and UI rendering.

## Backend Splits

### `app/database/db.py`
- Current responsibilities: schema helpers, CRUD, auth/session storage, reader state, glossary, jobs, source catalog, operational events, backup-related queries
- Problem: one module is acting as a database layer, repository layer, and operational utility layer
- Proposed split:
  - `app/database/core.py`
  - `app/database/books.py`
  - `app/database/jobs.py`
  - `app/database/auth.py`
  - `app/database/glossary.py`
  - `app/database/reader.py`
  - `app/database/operations.py`
- Dependency direction: feature services import only the feature repository module, not the entire DB surface
- Sequence: extract reader/auth/job queries first, then glossary/source catalog, then operational helpers
- Risk: medium, because callers are widespread

### `app/mobile_api/services/pipeline_service.py`
- Current responsibilities: import, book/chapter CRUD, reader state, glossary, QA, source adapters, dictionary cache, annotations, export support, TTS-adjacent helpers
- Problem: too many domain behaviors in one service
- Proposed split:
  - `services/book_service.py`
  - `services/reader_service.py`
  - `services/import_service.py`
  - `services/glossary_service.py`
  - `services/source_service.py`
  - `services/annotation_service.py`
- Dependency direction: routers call thin domain services, domain services call repository helpers
- Sequence: reader/book extraction first, then import and glossary
- Risk: medium-high

### `app/mobile_api/routers/import_routes.py`
- Current responsibilities: paste import, wizard import, URL preview, ebook upload/preview, source list, source catalog actions, import job creation
- Problem: import orchestration and catalog management are coupled
- Proposed split:
  - `routers/import_text.py`
  - `routers/import_ebook.py`
  - `routers/import_url.py`
  - `routers/source_catalog.py`
- Sequence: extract ebook and wizard flows first because they are the most isolated

### `app/mobile_api/routers/books.py`
- Current responsibilities: books, chapters, reader progress, annotations, dictionaries, X-ray, reader sync, cover upload, raw/translation access
- Problem: this is effectively multiple routers in one file
- Proposed split:
  - `routers/books.py`
  - `routers/reader.py`
  - `routers/dictionaries.py`
  - `routers/annotations.py`
- Keep the public route shape stable during migration

### `app/mobile_api/routers/jobs.py`
- Current responsibilities: job create/start, job lists, logs, attempts, SSE, cost estimation, cancellation, retries
- Problem: jobs orchestration plus diagnostics plus transport concerns
- Proposed split:
  - `routers/jobs.py`
  - `routers/job_logs.py`
  - `routers/job_estimates.py`
  - `routers/job_events.py`

## Frontend Splits

### `web/src/components/ReaderView.tsx`
- Current responsibilities: chapter loading, reader mode logic, QA overlay, search, audio, dictionary, marks, offline cache, progress, AI/X-Ray, drawers, selection popovers, and scroll state
- Problem: too many concerns for one component
- Proposed split:
  - `reader/ReaderPage.tsx`
  - `reader/ReaderChrome.tsx`
  - `reader/ReaderTextStage.tsx`
  - `reader/ReaderModeSwitch.tsx`
  - `reader/ReaderOverlayHost.tsx`
- Sequence: extract rendering shell first, then mode-specific subviews
- Risk: high if done without tests; lower if done incrementally with snapshot/integration coverage

### `web/src/components/ImportPanel.tsx`
- Current responsibilities: paste, file, ebook, URL, catalog, wizard imports, preview, validation, and job launching
- Proposed split:
  - `import/ImportPaste.tsx`
  - `import/ImportFile.tsx`
  - `import/ImportEbook.tsx`
  - `import/ImportUrl.tsx`
  - `import/ImportCatalog.tsx`
  - `import/ImportWizard.tsx`

### `web/src/App.tsx`
- Current responsibilities: global routing, auth, state orchestration, workflow switching, loading/error handling, and coordination of many feature hooks
- Proposed split:
  - keep shell orchestration in `App.tsx`
  - move workflow composition into `WorkflowCoordinator.tsx`
  - move auth/session bootstrap into `AuthGate.tsx`

### `web/src/styles.css`
- Current responsibilities: essentially the whole visual system
- Proposed split:
  - `styles/tokens.css`
  - `styles/layout.css`
  - `styles/reader.css`
  - `styles/import.css`
  - `styles/jobs.css`
  - `styles/admin.css`

## Files That Should Stay Put For Now
- `app/mobile_api/config.py`
- `app/mobile_api/security.py`
- `web/src/state/*` hooks that already encapsulate focused behavior
- `app/services/tts/*` unless a TTS-specific refactor is separately scoped

## Recommended Sequence
1. Fix environment drift and test baselines
2. Extract backend reader and auth/session repositories
3. Split `ReaderView.tsx`
4. Split `ImportPanel.tsx`
5. Split `styles.css`
6. Split router files only after the frontend and service seams are stable

## Bottom Line
- The codebase does not require a rewrite
- It does require smaller domain modules for reader, import, and database access if future change speed matters
