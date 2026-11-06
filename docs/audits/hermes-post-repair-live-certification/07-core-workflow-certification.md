# Core workflow certification


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Test basis

The production-aware gate passed 1,247 backend tests, 778 frontend tests, the production frontend build, and 12 Chromium E2E tests. A separate focused security, workflow, TTS, parser, export, backup, readiness, and recovery run passed 382 tests. [Source: evidence/test-summary.json]

## Import

Paste, TXT, EPUB, URL fixture, duplicate handling, staged review, upload limits, parser boundaries, cancellation, retry, stale recovery, and backup job services are covered by deterministic tests. The release E2E opened the current paste flow with mocked backend data. No production import or unauthorized challenge target was used.

Status: **GO_WITH_LIMITATIONS**. A real third-party URL import and browser challenge were excluded by authorization and safety.

## Translation and QA

Translation job creation from a raw chapter passed E2E. Provider failures, cancellation, retry, stale recovery, deterministic QA, and glossary behavior passed backend tests using mocks or local fixtures. No paid provider was called.

Status: **GO_WITH_LIMITATIONS**.

## TTS

Both reachable staging APIs returned HTTP 503 with typed `tts_unavailable`. Low-level availability and engine-load calls raised `TTSUnavailableError`. Job counts remained unchanged and no CPU path was selected. [Source: evidence/tts-gpu-only.json]

Status: **GO_WITH_LIMITATIONS** because no supported GPU synthesis was approved. Backend policy is safe; frontend CPU guidance is P2 debt.

## Export

Safe filenames, authorization, partial cleanup, and export behavior passed tests. TXT E2E completed without a live provider call. No internal path leakage was observed.

Status: **GO_WITH_LIMITATIONS** because production export was not mutated.

## Protected challenge integration

Status: **preserved and regression-tested locally; not live-tested**.
