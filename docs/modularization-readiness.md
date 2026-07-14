# Modularization Readiness

## Decision

Further division is justified, but only after the measured P1 correctness/performance fixes and a new green commit. Line count alone is not the reason; measured change risk, optional feature loading, duplicate requests, and transaction behavior are.

P2C has now established the approved first boundaries. This document remains a
readiness guide for subsequent work, not permission for a one-shot split.

## ReaderView

- Current: 5,251 lines and 181.73 KB route chunk.
- Evidence: optional Reader tools load together; QA mode reached about 5,182 nodes and 599 ms; live App raw modes are disconnected from source text; request duplication exists.
- Proposed boundary: `ReaderController`, `ReaderDataLoader`, `ReaderChrome`, `ReaderTextModes`, `ReaderQaOverlay`, and lazy optional panels for audio, X-Ray/AI, dictionary, marks, and import/export.
- Dependency direction: controller -> data hooks and presentational feature modules; optional panels depend on narrow client interfaces, never on the controller.
- Sequence: fix request ownership and raw contract, add integration/performance tests, extract pure mode/QA logic, then lazy-load panels.
- Risk: high. Do after P1 fixes, not during this audit.

P2C result: TOC ownership is in `ReaderTocSheet`/`useReaderToc`; presentational
chrome and settings composition are in `ReaderChrome`/`ReaderQuickControls`;
audio state is in `useReaderAudio` with lazy `ReaderAudioFeature`; offline cache
state is in `useReaderOfflineCache`. `ReaderView` still owns selected
book/chapter, fetching, progress, rendering, annotations, AI/X-Ray, and opening
feature surfaces. Further optional-panel work remains recommendation-only.

## ImportPanel

- Current: 1,991 lines and 49.70 KB route chunk.
- Evidence: 5 MB preview stayed under 0.45 seconds and 120 chapters under 0.16 seconds; the performance problem is server commit, not bundle parse.
- Proposed boundary: wizard shell, text source, ebook source, URL/catalog source, preview, duplicate policy, and result actions.
- Sequence: fix server transaction behavior and add workflow tests, then extract source-specific views without changing state ownership.
- Risk: medium. Split for testability and workflow clarity, not as an urgent performance optimization.

## Backend Database and Services

- Current: `db.py` 5,989 lines; `pipeline_service.py` 5,543 lines.
- Evidence: project connection setup costs 9.346 ms, library N+1 reaches about 0.65-0.74 seconds at 59 books, and 120-chapter commit takes 5.62 seconds.
- Proposed boundary: domain repositories for books/chapters, jobs, glossary/QA, sources, Reader, TTS/audio, exports, and operations. A single connection/transaction policy belongs below services.
- Sequence: add query-count/transaction tests, implement aggregate library query, make migrations startup-scoped, extract one repository at a time, retain service APIs.
- Risk: high. Performance fixes should establish seams before broad extraction.

P2C result: `connection`, `auth_repository`, `operations_repository`, and
`reader_repository` are authoritative behind `db.py` compatibility exports.
`ContentFileService` and `ReaderService` are composed by `PipelineService`, and
the QA runtime cycle is replaced by `ChapterContentReader`. Book/import and the
other repository domains remain intentionally in place.

## CSS

- Current: 12,236 lines and 188.78 KB global payload.
- Evidence: overlapping mobile rules caused two pointer blockers; all routes load the same CSS.
- Proposed boundary: tokens/base, shell/navigation, library, import, Reader, operations, and responsive overrides colocated with each feature.
- Sequence: add screenshot/interaction regressions, consolidate mobile cascade conflicts, then split without visual changes.
- Risk: medium-high due cascade order.

P2C result: `styles.css` declares the fixed cascade order and imports tokens,
base, shell, shared components/features, Reader, Library, Import, Operations,
and utilities. Feature media queries are colocated with their owning feature
file. Selector names were preserved; no route-lazy CSS or redesign was added.

## Keep Unchanged Now

- Existing reader state modules, API client method boundaries, TTS chunker/normalizer/audio QA modules, authentication/session design, protected file routes, and source policy modules already have useful domain boundaries.

## Remaining limits

- The backup runner and retention scheduler are process-local, not a durable
  multi-node worker system.
- App shell and ImportPanel remain large surfaces.
- `db.py` and `PipelineService` remain compatibility facades and still contain
  domains outside the P2C scope.
- Reader annotations/AI/X-Ray/rendering remain in the route controller.
- CSS is layered but still eagerly loaded as one deterministic manifest.
