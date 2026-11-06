# Feature matrix


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`


| Feature | Mobile live or staging | Desktop live or staging | Deterministic tests | Verdict |
|---|---|---|---|---|
| Login and session | PASS | PASS | PASS | GO |
| Dashboard | PASS_WITH_LIMITATIONS | PASS | PASS | GO_WITH_LIMITATIONS |
| Library | PASS | PASS | PASS | GO |
| Reader Vietnamese | PASS | PASS | PASS | GO |
| Reader Raw | E2E PASS | E2E PASS | PASS | GO_WITH_LIMITATIONS |
| Reader Raw compact | NOT_RETESTED in custom browser | NOT_RETESTED | PASS | GO_WITH_LIMITATIONS |
| Reader Split | E2E PASS | E2E PASS | PASS | GO_WITH_LIMITATIONS |
| Reader QA overlay | PARTIAL | PARTIAL | PASS | GO_WITH_LIMITATIONS |
| Rapid navigation | PASS_WITH_LIMITATIONS | PASS_WITH_LIMITATIONS | PASS | GO_WITH_LIMITATIONS |
| First-session offline | PASS | n/a | PASS | GO |
| Warmed offline | PASS | n/a | PASS | GO |
| Reader More dialog | PASS | PASS | PASS | GO |
| Reader settings dialog | FAIL keyboard focus | FAIL keyboard focus | Gap | GO_WITH_LIMITATIONS |
| Reader TOC | NOT_RETESTED by custom selector | NOT_RETESTED | PASS | GO_WITH_LIMITATIONS |
| Notes, bookmark, highlight | NOT_TESTED | NOT_TESTED | Partial tests | NOT_TESTED |
| Import paste, TXT, EPUB | Isolated only | Isolated only | PASS | GO_WITH_LIMITATIONS |
| URL and managed source | Local contracts only | Local contracts only | PASS | GO_WITH_LIMITATIONS |
| Protected challenge | BLOCKED by authorization | BLOCKED | PASS local contract | GO_WITH_LIMITATIONS |
| Translation jobs | Isolated and mocked | Isolated and mocked | PASS | GO_WITH_LIMITATIONS |
| Glossary and QA | PASS_WITH_LIMITATIONS | PASS | PASS | GO_WITH_LIMITATIONS |
| Jobs retry and cancel | UI only | UI only | PASS | GO_WITH_LIMITATIONS |
| TTS unavailable | PASS | PASS | PASS | GO_WITH_LIMITATIONS |
| Real GPU TTS | NOT_TESTED | NOT_TESTED | Fixture only | NOT_TESTED |
| Export | Mocked E2E | Mocked E2E | PASS | GO_WITH_LIMITATIONS |
| Backup archive | Status only | Status only | Existing artifact verified | NO_GO continuity |
| Restore core | n/a | n/a | Fresh drill core PASS | GO_WITH_LIMITATIONS |
| Restore receipt | n/a | n/a | Publisher unit PASS | NO_GO integration |
| Runtime hardening | n/a | PASS | PASS | GO |
| Readiness | PASS | PASS | PASS | GO |
| Operational metrics | Auth probe blocked by staging login rejection | Same | PASS | GO_WITH_LIMITATIONS |
| Alert delivery | NOT_TESTED | NOT_TESTED | Rule evaluation PASS | NOT_TESTED |
| Release provenance | n/a | PASS_WITH_LIMITATIONS | PASS | GO_WITH_LIMITATIONS |
| Rollback | n/a | Stale canonical runbook | Overlay exists | NO_GO |


`NOT_TESTED` is not treated as passed. Mutation-capable production workflows were intentionally excluded.
