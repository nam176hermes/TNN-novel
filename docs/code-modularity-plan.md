# Code Modularity Plan

## Direct Answer

Yes, the code should be divided further, but only along measured responsibility and test boundaries. A rewrite or line-count-driven split is not justified. P2A and P2B proved that high-value performance fixes can be delivered through narrow seams while preserving the current architecture.

## Evidence

| Module | Lines | Approx. functions | Why it matters |
|---|---:|---:|---|
| `web/src/styles.css` | 12,244 | n/a | Entire visual system and responsive behavior share one change surface |
| `app/database/db.py` | 6,225 | 186 | Repositories for unrelated domains and lifecycle helpers are coupled |
| `app/mobile_api/services/pipeline_service.py` | 5,700 | 172 | Book, Reader, import, source, dictionary, annotation, and file behavior share one service |
| `web/src/components/ReaderView.tsx` | 5,251 | n/a | Fetching, text rendering, QA, audio, dictionary, annotations, offline state, and controls |
| `web/src/App.tsx` | 2,026 | n/a | Auth bootstrap, workflow routing, global fetch ownership, and orchestration |
| `web/src/components/ImportPanel.tsx` | 1,991 | n/a | Paste/file/ebook/URL/catalog review and commit state |
| `app/mobile_api/services/job_service.py` | 1,551 | n/a | Lifecycle, scheduling, retries, stale recovery, and job-domain execution |
| `web/src/components/SourcesView.tsx` | 982 | n/a | Catalog, managed sources, review/testing, and filters |
| `app/mobile_api/routers/import_routes.py` | 825 | n/a | Multiple import transports and commit orchestration |
| `app/mobile_api/routers/books.py` | 806 | n/a | Books, chapters, Reader, annotations, dictionaries, X-Ray, and cover routes |

The local import graph also contains a direct circular dependency: `pipeline_service -> qa_service -> pipeline_service`. Remove this through a small interface/extracted pure QA dependency before larger service moves.

## Recommended Splits

### Reader

- Current: `web/src/components/ReaderView.tsx`.
- Problem: route data ownership, text transformations, optional tools, polling, and UI chrome are coupled; P1 measured duplicate requests and QA up to 599 ms/5,182 DOM nodes.
- Proposed modules: `ReaderPage`, `ReaderDataController`, `ReaderTextStage`, `ReaderChrome`, `ReaderQaLayer`, and lazy `ReaderAudioPanel`/`ReaderDictionaryPanel`/`ReaderAnnotationPanel`.
- Dependency direction: page/controller owns data; pure text stage receives prepared view data; optional panels depend on narrow APIs.
- Sequence: first eliminate duplicate request ownership, then extract pure rendering, then lazy optional panels.
- Risk: high.
- Timing: after stale path migration and backup P1 work; regression coverage must remain green.

### Import

- Current: `web/src/components/ImportPanel.tsx`, `app/mobile_api/routers/import_routes.py`.
- Problem: transport selection, parsing UI, reviewed plan, duplicate decisions, and job actions share state. Performance is no longer the reason: P2B reduced 120 chapters to 144 ms route median.
- Proposed frontend: source selector, text/file adapter, ebook adapter, URL/catalog adapter, review screen, commit result.
- Proposed backend: keep route paths, extract text/ebook/URL orchestration functions behind current router.
- Dependency direction: adapters produce one reviewed-plan type; commit owns mutation; post-commit actions consume committed IDs.
- Sequence: add contract tests, extract pure review/result components, then adapters.
- Risk: medium-high.
- Timing: P2/P3, not before Reader correctness work.

### Database

- Current: `app/database/db.py`.
- Problem: lifecycle plus repositories for auth, books, jobs, glossary, sources, Reader, TTS, and operations.
- Proposed modules: `connection`, `auth_repository`, `book_repository`, `job_repository`, `reader_repository`, `glossary_repository`, `source_repository`, `tts_repository`, `operations_repository`.
- Dependency direction: services import domain repositories; repositories depend only on connection/schema primitives.
- Sequence: preserve a compatibility facade; extract one domain at a time, starting with jobs or auth, not the newly optimized library/import seams.
- Risk: medium-high due many callers.
- Timing: after a clean post-audit baseline and explicit contract/query-count tests.

### Pipeline Service

- Current: `app/mobile_api/services/pipeline_service.py`.
- Problem: unrelated domain behavior and circular QA dependency.
- Proposed modules: `book_service`, `reader_service`, `annotation_service`, `dictionary_service`, `import_commit_service`, `content_file_service`.
- Dependency direction: routers -> domain services -> repositories/file adapters; QA consumes a protocol/pure content input rather than importing PipelineService.
- Sequence: break circular dependency, extract content-file resolver, then Reader/annotation services.
- Risk: high.
- Timing: after DB repository seams exist.

### App Shell And API Client

- Current: `web/src/App.tsx` and broad API client/types.
- Problem: route orchestration and feature loading/error ownership are concentrated.
- Proposed modules: `AuthGate`, `WorkflowRouter`, feature loaders, and domain API clients retaining shared transport/auth handling.
- Dependency direction: domain hooks -> domain clients -> shared authenticated transport.
- Risk: medium.
- Timing: alongside feature extraction, not as a standalone rewrite.

### CSS

- Current: `web/src/styles.css`.
- Problem: 12,244-line global regression surface.
- Proposed files: tokens/base, shell/navigation, reader, import, library, operations, and responsive overrides.
- Dependency direction: shared tokens/base first, route styles imported with route chunks where Vite behavior remains verified.
- Sequence: add screenshot/overflow assertions, extract unchanged blocks, compare build and screenshots after every feature.
- Risk: medium-high visual regression risk.
- Timing: last.

## Files To Keep Unchanged For Now

- `app/mobile_api/security.py` and session/auth middleware: focused and security-sensitive.
- `app/mobile_api/config.py`: focused settings boundary.
- `app/database/schema.py`: keep additive schema ownership centralized until repository extraction stabilizes.
- `app/services/tts/*`: already domain-oriented; no measured structural blocker.
- Reader state modules under `web/src/state` that already have narrow ownership.
- Public API route paths and response contracts.

## Minimum-Risk Sequence

1. Migrate stale artifact paths with backup, copied-DB rehearsal, integrity checks, and rollback.
2. Fix backup listing and implement job-backed backup without changing restore format.
3. Remove Reader duplicate requests and establish data-contract tests.
4. Break the PipelineService/QA circular dependency.
5. Extract Reader pure rendering and optional panels.
6. Extract one database repository domain at a time behind compatibility exports.
7. Split Import by reviewed-plan adapters.
8. Split CSS only with screenshot and responsive regression coverage.

## Acceptance Rule

Each extraction must preserve API contracts, full verification, E2E library-to-Reader/import workflows, security tests, and measured route performance. No phase should combine behavior changes with broad file movement.
