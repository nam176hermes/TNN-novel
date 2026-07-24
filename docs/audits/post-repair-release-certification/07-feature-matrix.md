# Post-repair feature matrix

Statuses: `GO`, `GO_WITH_LIMITATIONS`, `NO_GO`, `NOT_TESTED`, `BLOCKED`.

| Feature | Mobile | Desktop/API | Integrity/security | Evidence / limitation |
|---|---|---|---|---|
| Login/session | GO | GO | GO_WITH_LIMITATIONS | Cookie refresh, CSRF, rotation/reuse/logout tests pass; dependency P2 remains. |
| Dashboard | GO | GO | GO | Required viewports, health/status data, no overflow. |
| Library | GO | GO | GO | Real staging data list and navigation pass. |
| Book detail | GO | GO | GO | Covered by Reader/library flows and component tests. |
| Reader Vietnamese | GO | GO | GO | Visible text and chapter navigation pass. |
| Reader Raw | GO | GO | GO | Enabled only for current chapters with source. |
| Reader Raw compact | GO | GO | GO | Same truthful source contract. |
| Reader Split | GO | GO | GO | Requires source + translation; pass. |
| Reader QA overlay | GO | GO | GO | Present/absent states and focused tests pass. |
| Reader rapid navigation | GO | GO | GO | No stale overwrite; one core request per transition/resource. |
| Reader offline/PWA | GO_WITH_LIMITATIONS | GO_WITH_LIMITATIONS | GO | Cached content or explicit offline shell; live-domain offline not mutated. |
| Reader audio/TTS controls | GO_WITH_LIMITATIONS | GO_WITH_LIMITATIONS | GO | Safe unavailable state without GPU; no real synthesis. |
| Reader dialog/TOC | GO | GO | GO_WITH_LIMITATIONS | Focus and virtualization pass; no full screen-reader certification. |
| Import paste/TXT/EPUB/URL | GO | GO | GO | Isolated tests and mocked E2E; no third-party live import. |
| Translation jobs | GO | GO | GO | Mock/local provider, lifecycle, retry/cancel/stale recovery pass. |
| Glossary/style | GO | GO | GO | Virtualized production-scale list, search/filter tests. |
| QA reports | GO | GO | GO | Deterministic/glossary QA suite passes. |
| Sources/catalog | GO | GO | GO | Canonical registry and safe URL/browser policy pass. |
| Protected challenge integration | NOT_TESTED | GO_WITH_LIMITATIONS | GO_WITH_LIMITATIONS | Local contract preserved; no live third-party challenge test. |
| Providers/settings | GO | GO | GO | Secret masking and protected configuration tests pass; no paid call. |
| Export | GO | GO | GO | TXT E2E and focused format/auth tests pass. |
| Backup | GO | GO | GO_WITH_LIMITATIONS | Fresh encrypted backup; metrics do not yet ingest external freshness. |
| Restore drill | GO | GO | GO | Fresh isolated encrypted restore passed all mandatory checks. |
| Operational metrics | GO | GO | GO_WITH_LIMITATIONS | Authenticated/redacted; external recovery freshness gap remains. |
| Readiness | GO | GO | GO | Worker-aware and capability-aware; optional TTS degrades honestly. |
| Runtime hardening | n/a | GO | GO | API/worker runtime contract passes. |
| Release provenance | n/a | GO | GO | Shared release ID, Git SHA, image IDs, schema recorded. |
| Rollback | n/a | GO_WITH_LIMITATIONS | GO | Pinned overlay and commands; live rollback not executed. |
| Accessibility | GO_WITH_LIMITATIONS | GO_WITH_LIMITATIONS | GO_WITH_LIMITATIONS | Audited regressions pass; no formal WCAG certification. |

No row is `NO_GO` or `BLOCKED`. `NOT_TESTED` is limited to explicitly protected
or unavailable external behavior and is not represented as passed.
