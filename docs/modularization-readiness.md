# Modularization Readiness

## Decision

Further division is justified, but only after the measured P1 correctness/performance fixes and a new green commit. Line count alone is not the reason; measured change risk, optional feature loading, duplicate requests, and transaction behavior are.

## ReaderView

- Current: 5,251 lines and 181.73 KB route chunk.
- Evidence: optional Reader tools load together; QA mode reached about 5,182 nodes and 599 ms; live App raw modes are disconnected from source text; request duplication exists.
- Proposed boundary: `ReaderController`, `ReaderDataLoader`, `ReaderChrome`, `ReaderTextModes`, `ReaderQaOverlay`, and lazy optional panels for audio, X-Ray/AI, dictionary, marks, and import/export.
- Dependency direction: controller -> data hooks and presentational feature modules; optional panels depend on narrow client interfaces, never on the controller.
- Sequence: fix request ownership and raw contract, add integration/performance tests, extract pure mode/QA logic, then lazy-load panels.
- Risk: high. Do after P1 fixes, not during this audit.

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

## CSS

- Current: 12,236 lines and 188.78 KB global payload.
- Evidence: overlapping mobile rules caused two pointer blockers; all routes load the same CSS.
- Proposed boundary: tokens/base, shell/navigation, library, import, Reader, operations, and responsive overrides colocated with each feature.
- Sequence: add screenshot/interaction regressions, consolidate mobile cascade conflicts, then split without visual changes.
- Risk: medium-high due cascade order.

## Keep Unchanged Now

- Existing reader state modules, API client method boundaries, TTS chunker/normalizer/audio QA modules, authentication/session design, protected file routes, and source policy modules already have useful domain boundaries.
