# Code Modularity Plan

## Direct Answer

Yes, the code should be divided further, but only along measured responsibility and test boundaries. A rewrite or line-count-driven split is not justified. P2A and P2B proved that high-value performance fixes can be delivered through narrow seams while preserving the current architecture.

## P2C status

P2C implemented the first approved seams without a broad rewrite:

- database connection, auth, operations, and Reader repositories now have one
  authoritative module each, with identity-compatible exports from `db.py`;
- `ContentFileService` owns bounded artifact reads and `ReaderService` owns
  Reader progress/annotation/content orchestration; `PipelineService` preserves
  existing method signatures through delegates;
- `QAService` consumes the narrow `ChapterContentReader` protocol and no longer
  imports `PipelineService` at runtime;
- Reader TOC, chrome/quick controls, lazy audio, and offline cache state live in
  focused modules while `ReaderView` remains the route/data controller;
- `styles.css` is an ordered layer/import manifest and feature rules, including
  responsive rules, are owned by feature stylesheets.

These are compatibility facades, not duplicate implementations. Books/import,
glossary, sources, TTS, App-shell orchestration, and ImportPanel remain future
seams and must not be moved only to reduce line count.

## Baseline evidence before P2C

These measurements are the original pre-P2C audit snapshot, not current line
counts or current ownership.

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

At this pre-P2C baseline, the local import graph also contained the direct
`pipeline_service -> qa_service -> pipeline_service` cycle. P2C removed that
runtime cycle through `ChapterContentReader`; it is not current work.

## Recommended Splits

### Reader

- Current after P2C: `ReaderView` remains the route/data controller; TOC,
  chrome/quick controls, lazy audio, and offline cache have focused owners.
- Remaining problem: rendering, annotations, AI/X-Ray, and some feature-opening
  orchestration remain in the controller.
- Deferred modules: extract only those remaining surfaces behind narrow APIs;
  do not re-extract the P2C-owned Reader features.
- Dependency direction: page/controller owns data; pure text stage receives prepared view data; optional panels depend on narrow APIs.
- Sequence: extract one remaining surface at a time behind the existing
  controller and focused regression tests.
- Risk: high.
- Timing: recommendation-only after P2C; regression coverage must remain green.

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

- Current after P2C: connection, auth, operations, and Reader repositories are
  authoritative behind identity-compatible `db.py` exports.
- Remaining problem: books, jobs, glossary, sources, and TTS domains are still
  centralized in the compatibility facade.
- Deferred modules: `book_repository`, `job_repository`,
  `glossary_repository`, `source_repository`, and `tts_repository`.
- Dependency direction: services import domain repositories; repositories depend only on connection/schema primitives.
- Sequence: preserve the compatibility facade and extract one remaining domain
  at a time where contract/query-count tests establish the boundary.
- Risk: medium-high due many callers.
- Timing: after a clean post-audit baseline and explicit contract/query-count tests.

### Pipeline Service

- Current after P2C: `ContentFileService` and `ReaderService` own content
  resolution plus Reader content/progress/annotation orchestration;
  `PipelineService` delegates those public methods, and the QA runtime cycle is
  removed.
- Remaining problem: book, dictionary, import, and other non-Reader domains
  still share the compatibility service.
- Deferred modules: `book_service`, `dictionary_service`, and
  `import_commit_service` where contract tests support extraction.
- Dependency direction: routers -> domain services -> repositories/file adapters; QA consumes a protocol/pure content input rather than importing PipelineService.
- Sequence: keep the implemented content/Reader delegates stable and extract
  only one remaining non-Reader domain at a time.
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

- Current after P2C: `styles.css` is a small ordered manifest; tokens, base,
  shell, shared components, features, utilities, and overrides have explicit
  order, and responsive rules are colocated with Reader, Library, Import, and
  Operations ownership.
- Remaining problem: the deterministic manifest is still eagerly loaded.
- Deferred work: consider route-lazy CSS only if measurement and cascade tests
  justify the loading change.
- Dependency direction: shared tokens/base first, route styles imported with route chunks where Vite behavior remains verified.
- Sequence: retain current cascade/screenshot coverage and change loading only
  after measuring a route-level benefit.
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

1. Preserve the P2C compatibility facades and focused regression coverage.
2. Extract only remaining Reader rendering/optional surfaces, one tested owner
   at a time.
3. Extract one remaining database repository domain at a time behind existing
   compatibility exports.
4. Split Import by reviewed-plan adapters.
5. Split App-shell orchestration only with route/auth regression coverage.
6. Change eager CSS loading only with measured need plus screenshot and
   responsive regression coverage.

## Acceptance Rule

Each extraction must preserve API contracts, full verification, E2E library-to-Reader/import workflows, security tests, and measured route performance. No phase should combine behavior changes with broad file movement.

## P2C rollback map

For the affected seam, run `git revert <commit>` once per commit, newest first.
These boundaries are inclusive:

- backup jobs/publication/terminal audit: revert `f744b25`, then `a4eac8c`,
  then `3f3b83d`, then `de94de7`, then `9d04ffe`,
  then every backup-seam commit from `04ad491` backward through and including
  `b77fa38`;
- retention/repository foundation: revert every affected commit from `56534d9`
  backward through and including `38156ce`;
- Reader modules: revert every affected commit from `987aea0` backward through
  and including `31093ba`;
- CSS ownership: revert every affected commit from `2a77755` backward through
  and including `46759eb`;
- Reader repository/services: revert `9f47a41`, then `6c2ba0a`.

All P2C extractions preserve the schema and public routes except the documented
backup POST `202` contract. Rollback therefore uses `git revert`, focused tests,
and a normal redeploy; it does not require database downgrade SQL.
