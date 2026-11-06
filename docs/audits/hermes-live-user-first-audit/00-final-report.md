# Novel-TNN Live User-First Audit: Final Report

Status: COMPLETE

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Executive verdict

**GO_WITH_LIMITATIONS** for Nam's private production use on mobile and desktop.

The release has strong runtime, data, security, recovery, and automated-test evidence. Core Library and Reader workflows work live. The main user-facing defect is a first-session PWA lifecycle gap: after the app reports that the current chapter was cached, an immediate offline reload can render a blank page until one online reload has warmed the runtime asset cache. [Source] `/tmp/novel-tnn-live-audit/controller/browser-fresh/pwa-valid-no-route-result.json`; `/tmp/novel-tnn-live-audit/controller/browser-fresh/pwa-valid-online-reload-result.json`; `web/public/reader-offline-sw.js`

Overall score: **8.0/10**. [Source] `17-feature-matrix-and-scorecard.md`

## Release decisions

| Scope | Verdict | Reason |
|---|---|---|
| Local private use | GO | Core workflows, full verification, data integrity, and recovery drill pass. |
| Public private-production | GO_WITH_LIMITATIONS | Authentication and runtime are strong; recovery freshness is not visible in runtime metrics. |
| Mobile | GO_WITH_LIMITATIONS | Responsive shell and Reader work; first-session offline reload can be blank. |
| Desktop | GO | Operator pages are usable and stable; some tables are dense. |
| Data safety | GO | SQLite integrity, foreign keys, artifacts, and fresh isolated restore all pass. |
| Security | GO_WITH_LIMITATIONS | Strong session, CSRF, CORS, headers, SSRF, and runtime controls; Python advisory debt remains. |
| Backup and recovery | GO | Fresh encrypted backup and fresh isolated restore passed. |
| Observability | GO_WITH_LIMITATIONS | Health and worker telemetry are clear; external backup and restore freshness are not ingested. |
| Release trust | GO_WITH_LIMITATIONS | Unit, build, full backend, and Playwright E2E pass; E2E is not a mandatory verify or CI gate. |
| Accessibility | GO_WITH_LIMITATIONS | Touch targets, landmarks, focus trap, Escape, and focus return pass; formal contrast and assistive-technology certification remain open. |

## Highest-priority findings

1. **P1 UX-PWA-001:** first-session offline reload can be blank after a successful cache message.
2. **P2 TEST-PWA-002:** the E2E test performs an online reload before testing offline, so it misses UX-PWA-001.
3. **P2 OPS-REC-003:** runtime cannot report external backup freshness or latest restore-drill status.
4. **P2 SEC-DEP-004:** Python audit reports three unique advisory pairs.
5. **P2 PRIV-TTS-005:** F5 upstream debug capture can log raw upstream output.
6. **P2 ARCH-006:** several core files and classes are oversized change-risk hotspots.

Full reproduction and evidence: [`18-issue-register.md`](18-issue-register.md).

## Verification summary

- Production-env-aware full verification: exit `0`.
- Backend: `1,181 passed`.
- Frontend: `768 passed` across 86 files.
- Production build: PASS.
- Playwright E2E: `11 passed`.
- Runtime hardening contract: API PASS, worker PASS.
- Fresh restore drill: integrity `ok`, foreign keys `0`, artifact paths `1,774`, authenticated Reader smoke PASS.
- Production DB: integrity `ok`, foreign-key violations `0`, missing artifacts `0`, zero-byte artifacts `0`.

[Source] `/tmp/novel-tnn-live-audit/controller/verify-production-env.log`; Playwright command `npm --prefix web run test:e2e`; `/tmp/novel-tnn-live-audit/restore-drill.log`; `/tmp/novel-tnn-live-audit/restore-drills/restore-drill-20260724T015034Z-Vsdg5X-validation.json`

## Untested boundaries

- No live import, translation, TTS, export, retry, cancel, or restore mutation was triggered.
- No live protected challenge or paid provider call was attempted.
- No real GPU TTS was available.
- No low-end physical Android device or formal screen-reader session was available.

## Exact next Hermes Goal recommended

**Implement and verify one PR-sized P1 fix for first-session Reader offline readiness. Make the service worker serve newly installed app-shell assets immediately, add a first-session E2E case with no preparatory online reload, preserve protected API non-caching, then run full verification and a live two-path offline certification.**
