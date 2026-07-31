# Workstream 6 — Controlled Maintainability Extraction

## Outcome

Workstream 6 executed exactly one approved extraction batch: the Reader
text-mode capability and fallback boundary. The batch is complete on branch
`refactor/ws6-reader-mode-boundary` at implementation commit `6a078b2`.

No endpoint, schema, database, artifact, job-state, browser-challenge, auth,
offline-cache, TTS, production configuration, container, or ingress behavior
changed. Nothing was deployed.

Baseline:

- main-worktree branch: `upgrade-b/00-baseline-and-agent-guidance`
- baseline commit: `f87a9d84e1a3c875b9c8ba52418fb17285978ce0`
- isolated worktree: `/home/thenam176/Novel-TNN-worktrees/ws6-reader-mode-boundary`
- Python 3.11.15, Node 22.23.0, npm 10.9.8
- baseline mandatory gate: 1,181 backend and 763 frontend tests passed
- `NOVEL_PIPELINE_IGNORE_DOTENV=1`; mutable tests used temporary data/DB paths

## Entry-gate decision

The gate was accepted because:

- WS1–WS5 repair reports record the P1 fixes and their contract tests;
- source adapter registration is canonical;
- Reader ownership, stale-request, raw/split, offline, mobile visual, dialog,
  and TOC contracts exist;
- auth/session, CSRF, cookie, rotation, logout, and retention contracts exist;
- production readiness/release identity is deployed and documented;
- a fresh baseline `scripts/verify.sh` run passed before extraction.

## Responsibility map

Line count was used only to locate ownership centers, not to justify extraction.

| Center | Current responsibility/public boundary | Side effects and state ownership | Test/evidence and safe seam |
| --- | --- | --- | --- |
| `app/database/db.py` (5,632 lines) | Compatibility facade for schema initialization/migration and DB domains including providers, books, chapters, jobs, sources, glossary, QA, Reader and operations | SQLite transactions; DB permissions; environment-backed operator seeding; no direct UI state | Broad backend coverage; already delegates auth, operations and Reader repositories. Continue only by bounded repository domain behind facade. High data risk. |
| `app/mobile_api/services/pipeline_service.py` (5,468) | `PipelineService` orchestrates import, translation, QA/glossary, Reader helpers, dictionary, TTS/export and job progress | DB, filesystem/artifacts, providers/network, job state, cancellation and publication | Strong workflow tests, but many transactional/idempotency edges. Defer until individual stages have explicit characterization tests. Highest correctness risk. |
| `web/src/components/ReaderView.tsx` (4,251 baseline) | Reader composition, surfaces, chrome, marks/search/dictionary/X-Ray/audio, pagination/progress, preferences and mode selection | React state/effects, history, DOM measurement; calls typed hooks/API clients; optional resources remain Reader-owned | 102 direct Reader tests plus Playwright. WS2/WS5 stabilized data ownership, modes, offline and TOC. Pure text-mode capability was the safest current seam. |
| `app/ingestion/source_adapters.py` (2,841) | Registry metadata, URL matching/policy, HTTP/stealth fetch contract and parser implementations | Network, proxy/cookie/browser integration, rate/cooldown policy and challenge boundary | Canonical registry and network-policy suites exist. Extraction is feasible but security-sensitive; metadata/parser/fetch separation must preserve protected challenge behavior. |
| `web/src/components/ImportPanel.tsx` (2,454) | Paste/file/ebook/URL/catalog wizard, preview/review/commit and optional job actions | Browser file reads, local wizard state, API staging/commit/job calls | Import workflow and mobile tests exist, but format and commit state remain coupled. Defer until format-adapter contracts are isolated. |
| `web/src/App.tsx` (2,133) | Authenticated route/shell composition, domain hooks, lazy views, selection and cross-view workflow orchestration | Session and navigation state, network through hooks/client, private-cache cleanup, retry/refresh orchestration | Broad App tests. Extract domain composition only after leaf boundaries; splitting now could create more shared state owners. |
| `web/src/state/readerCache.ts` (1,933) | Chapter/asset/audio cache, URL extraction/hydration, IndexedDB and localStorage fallback, quota/status/cleanup | IndexedDB, localStorage, object URLs, asset/audio blobs and cache events | Dedicated cache/offline tests. Good future adapter seam, but private-data/logout and offline security make it higher risk than the selected pure boundary. |
| `web/src/api/client.ts` (1,645) | `ApiClient`, `ApiError`, auth/CSRF request policy, endpoint methods and protected downloads | Fetch, credentials/cookies, refresh coordination, downloads | Very broad API/auth coverage. Future domain clients should share one transport; do not duplicate refresh/CSRF policy. |

## Extraction ranking

1. **Completed:** Reader text-mode capability/fallback — pure, typed, independently
   testable, protected by resource-combination and E2E contracts, no I/O.
2. Reader optional panel adapters — defer; extract one optional owner at a time.
3. Source registry metadata/parser boundary — strong tests but protected security edge.
4. Reader cache storage adapters — useful isolation, higher private-data/offline risk.
5. Database bounded repositories — compatibility facade required; high data risk.
6. Pipeline stages — highest transaction/job/artifact risk; requires stage contracts first.
7. Import format/preview state — wait for stronger adapter-level characterization.
8. App/domain API clients — migrate callers only after transport interface is explicit.
9. CSS — last, with screenshot/visual coverage.

## Completed batch

### Before

```text
Reader source/translation/HTML props
        |
        v
ReaderView inline booleans
        |
        +--> quick-control availability
        |
        +--> inline effect with fallback ordering + persistence
```

Capability derivation, fallback priority, UI availability, and the persistence
effect were co-owned by the 4,251-line component. The behavior was covered only
through the full Reader render harness.

### After

```text
Reader source/translation/HTML props
        |
        v
readerTextModeCapabilities (pure, typed, no I/O)
        |                         |
        |                         +--> resolve compatible mode
        +--> availability flags          |
                    |                    v
                    +------------> ReaderView persistence effect

readerTextModeCapabilities --type-only--> reader/types
ReaderView ------------------------------> readerTextModeCapabilities
```

Dependency direction is one-way. The new module imports only `ReaderTextMode`
as a type, owns no React/browser state, and has no reverse import to ReaderView,
settings, API, or cache modules. Typecheck/build confirm the graph; the direct
import inspection shows no new cycle.

Public contract:

- `deriveReaderTextModeCapabilities(resources)` returns raw, translation,
  split and raw-collapsed availability from one canonical resource set;
- rich EPUB HTML remains translated content;
- whitespace-only resources remain unavailable;
- `resolveReaderTextMode(mode, capabilities)` preserves the established
  translation/raw fallback order and QA-overlay behavior;
- ReaderView remains responsible only for applying/persisting a changed mode.

## Characterization and regression tests

Before moving code, the existing Reader tests passed for:

- Vietnamese/raw/split rendering;
- source-only capability;
- translation-only truthful disabled reasons;
- persisted unsupported-mode fallback.

The new independent test module covers all five Reader text modes across:

- source + translation;
- source only;
- translation only;
- rich HTML only;
- whitespace/empty content.

The test was first run before implementation and failed because the extraction
module did not yet exist. After implementation:

- focused capability/Reader tests: 9 passed;
- complete ReaderView + capability tests: 107 passed;
- full frontend: 86 files, 768 tests passed;
- Reader Playwright: 4/4 passed, including mobile resource availability,
  Reader handoff and offline reload;
- typecheck and production build passed;
- full mandatory verification after commit: 1,181 backend and 768 frontend
  tests passed; two pre-existing dependency deprecation warnings remain.

## Measurements

| Metric | Before | After | Assessment |
| --- | ---: | ---: | --- |
| `ReaderView.tsx` lines | 4,251 | 4,246 | Small ownership move; line reduction was not the goal. |
| Independent capability tests | 0 | 5 | Boundary can now be tested without rendering Reader. |
| Frontend test files/tests | 85 / 763 | 86 / 768 | Five contract cases added. |
| Vite transformed modules | 1,857 | 1,858 | Expected new module. |
| Reader chunk | 193.27 kB / 54.24 kB gzip | 193.64 kB / 54.31 kB gzip | +0.37 kB raw, +0.07 kB gzip; explained function/module boundary, no performance improvement claimed. |
| Main index chunk | 355.48 / 110.27 kB gzip | 355.48 / 110.27 kB gzip | Unchanged. |

No wall-clock performance claim is made. The changed boundary performs only a
few string trims and boolean comparisons already performed inline.

## Files and commits

Implementation:

- `web/src/components/ReaderView.tsx`
- `web/src/components/reader/readerTextModeCapabilities.ts`
- `web/src/components/reader/readerTextModeCapabilities.test.ts`

Commit:

- `6a078b2 refactor(reader): extract text mode capability boundary`

## Security, data and rollback

- No network, storage, token, cookie, HTML rendering or cache policy moved.
- No raw/private content is logged or added to reports.
- No production state, DB or artifact was read or modified by implementation.
- Rollback is code-only: revert `6a078b2`, then rerun Reader and mandatory gates.
- No migration, container rebuild or production restart is required for review.

## Deferred work

All other ownership centers and Reader seams are deliberately deferred. A new
Codex task must approve exactly one next batch and add characterization tests
before moving it. In particular, this task does not authorize broad Reader
decomposition, source/challenge changes, DB repository migration, pipeline
stage movement, API transport duplication, ImportPanel extraction, or CSS split.

## Recommendation

**GO for operator review and controlled merge of this single batch.**

**GO for Workstream 7 certification only after merge and a clean main-worktree
verification.** If further MAINT-001 extraction is desired instead, start a new
WS6 batch prompt and select only one deferred seam.
