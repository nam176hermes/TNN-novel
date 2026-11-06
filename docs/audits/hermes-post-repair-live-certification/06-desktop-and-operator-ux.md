# Desktop and operator UX


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Coverage

Desktop black-box checks ran at 1366x768 and 1440x1000 against the isolated production image. Dashboard, Library, Jobs, and Reader opened without horizontal overflow or page errors. Redacted screenshots are preserved. [Source: evidence/browser-summary.json] [Source: evidence/screenshots/]

## Operator surfaces

| Surface | Result | Evidence limit |
|---|---|---|
| Dashboard | PASS | Read-only observation only |
| Library | PASS | Book selection and Reader launch passed |
| Jobs | PASS_WITH_LIMITATIONS | Statuses visible; no live retry or cancellation |
| Import | PASS_WITH_LIMITATIONS | Mocked E2E and backend fixtures, no paid or third-party mutation |
| Sources | PASS_WITH_LIMITATIONS | Local contracts only; protected challenge not live-tested |
| Glossary and QA | PASS | Tests and bounded DOM evidence |
| Providers | PASS_WITH_LIMITATIONS | Configuration display only; no paid provider call |
| Export | PASS_WITH_LIMITATIONS | E2E TXT and backend tests; no production export mutation |
| Backup and status | FAIL for certification | Current receipt integration and future backup preflight fail |
| Settings | PASS_WITH_LIMITATIONS | Reader settings focus defect |

## Clarity

Core status and unavailable TTS behavior are visible. The Reader audio message remains policy-inconsistent because one frontend path recommends CPU TTS. Recovery status cannot be truthful until receipts are published and ingested. [Source: `web/src/components/reader/useReaderAudio.ts`] [Source: evidence/production-data-integrity.json]

## Verdict

**GO_WITH_LIMITATIONS.** Daily desktop use works. Recovery administration and complete mutation workflows are not certified.
