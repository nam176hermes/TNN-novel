# Modularization Readiness

## Decision

Further division is justified only for the remaining measured responsibility
and test boundaries. P2C completed the first approved extraction set; line count
alone is still not a reason for another split.

P2C has now established the approved first boundaries. This document remains a
readiness guide for subsequent work, not permission for a one-shot split.
Measurements below are preserved pre-P2C audit snapshots, not current file
counts or current dependency descriptions.

## ReaderView

- Pre-P2C audit baseline: 5,251 lines and a 181.73 KB route chunk.
- Baseline evidence: optional Reader tools loaded together; QA mode reached about 5,182 nodes and 599 ms; live App raw modes were disconnected from source text; request duplication existed.
- Remaining proposed boundary: keep `ReaderView` as controller while extracting only still-owned rendering, annotations, AI/X-Ray, and optional feature surfaces when their tests justify it.
- Dependency direction: controller -> data hooks and presentational feature modules; optional panels depend on narrow client interfaces, never on the controller.
- Sequence: preserve the P2C owners and extract one remaining surface at a time
  behind focused integration/performance tests.
- Risk: high. Recommendation-only after P2C.

P2C result: TOC ownership is in `ReaderTocSheet`/`useReaderToc`; presentational
chrome and settings composition are in `ReaderChrome`/`ReaderQuickControls`;
audio state is in `useReaderAudio` with lazy `ReaderAudioFeature`; offline cache
state is in `useReaderOfflineCache`. `ReaderView` still owns selected
book/chapter, fetching, progress, rendering, annotations, AI/X-Ray, and opening
feature surfaces. Further optional-panel work remains recommendation-only.

## ImportPanel

- Pre-P2C audit baseline: 1,991 lines and a 49.70 KB route chunk.
- Baseline evidence: 5 MB preview stayed under 0.45 seconds and 120 chapters under 0.16 seconds; the performance problem was server commit, not bundle parse.
- Proposed boundary: wizard shell, text source, ebook source, URL/catalog source, preview, duplicate policy, and result actions.
- Sequence: preserve the optimized server transaction and workflow tests, then
  extract source-specific views without changing state ownership.
- Risk: medium. Split for testability and workflow clarity, not as an urgent performance optimization.

## Backend Database and Services

- Pre-P2C audit baseline: `db.py` 5,989 lines; `pipeline_service.py` 5,543 lines.
- Baseline evidence: project connection setup cost 9.346 ms, library N+1 reached about 0.65-0.74 seconds at 59 books, and 120-chapter commit took 5.62 seconds.
- Remaining proposed boundary: extract only the still-centralized books/chapters, jobs, glossary, sources, TTS/audio, exports, import, and dictionary domains behind the existing compatibility surfaces.
- Sequence: retain the existing query-count/transaction coverage and extract
  one remaining repository at a time without changing service APIs.
- Risk: high. Performance fixes should establish seams before broad extraction.

P2C result: `connection`, `auth_repository`, `operations_repository`, and
`reader_repository` are authoritative behind `db.py` compatibility exports.
`ContentFileService` and `ReaderService` are composed by `PipelineService`, and
the QA runtime cycle is replaced by `ChapterContentReader`. Book/import and the
other repository domains remain intentionally in place.

## CSS

- Pre-P2C audit baseline: 12,236 lines and a 188.78 KB global payload.
- Baseline evidence: overlapping mobile rules caused two pointer blockers and all routes loaded the same CSS.
- Remaining proposed boundary: preserve the ordered manifest and feature ownership; consider route-lazy loading only if later measurement justifies it.
- Sequence: retain current screenshot/interaction and cascade coverage; change
  eager loading only after measuring a route-level benefit.
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
