# Core Workflow Evidence

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Live read-only proof

| Workflow | Evidence | Result |
|---|---|---|
| Login | Browser login and protected API navigation | PASS |
| Library | Live mobile and desktop navigation | PASS |
| Book to Reader | Live navigation to a production chapter | PASS |
| Reader | Text, article, previous and next controls | PASS |
| Jobs list | Live read-only status rendering | PASS |
| Provider and Status views | Live operator navigation | PASS |
| Offline Reader, warmed | Explicit cache and offline reload | PASS |
| Offline Reader, first session | Explicit cache and immediate offline reload | FAIL |

## Isolated mutable proof

Playwright E2E passed 11 scenarios covering login protection, provider layout, paste import flow, translation job start, Reader controls, mobile Reader modes, warmed offline cache, mobile feature pages, touch targets, and TXT export. [Source] fresh `npm --prefix web run test:e2e`

The backend full suite passed 1,181 tests using isolated test database and data fixtures. [Source] `/tmp/novel-tnn-live-audit/controller/verify-production-env.log`; `tests/conftest.py`

## Not tested live

Import, translation, TTS, export, backup, restore, retry, cancellation, paid providers, and protected challenges were not mutated in production.
