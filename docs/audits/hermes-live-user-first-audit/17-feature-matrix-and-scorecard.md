# Feature Matrix and Scorecard

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Feature matrix

| Capability | Live mobile | Live desktop | Isolated tests | Verdict |
|---|---|---|---|---|
| Login and session | PASS | PASS | PASS | GO |
| Dashboard and Library | PASS | PASS | PASS | GO |
| Reader online | PASS | PASS | PASS | GO |
| Reader offline, warmed | PASS | n/a | PASS | GO |
| Reader offline, first session | FAIL | n/a | Missing case | NO_GO until P1 fix |
| Jobs status | PASS | PASS | PASS | GO |
| Import | Read-only UI | Read-only UI | PASS | GO_WITH_LIMITATIONS |
| Translation | NOT_TESTED | NOT_TESTED | PASS | GO_WITH_LIMITATIONS |
| Sources and challenge | Read-only UI | Read-only UI | Contract tests | GO_WITH_LIMITATIONS |
| Glossary and style | PASS | PASS | PASS | GO |
| Providers | PASS | PASS | PASS | GO |
| Export | Read-only UI | Read-only UI | TXT PASS | GO_WITH_LIMITATIONS |
| TTS | Unavailable clearly | Unavailable clearly | Contract tests | GO_WITH_LIMITATIONS |
| Backup | Status visible | Status visible | Contract tests | GO_WITH_LIMITATIONS |
| Restore | n/a | n/a | Fresh full drill PASS | GO |
| Runtime hardening | n/a | n/a | Live contract PASS | GO |

## Weighted scorecard

| Category | Score | Weight |
|---|---:|---:|
| Live UX | 7.7 | 12% |
| Mobile | 7.5 | 10% |
| Desktop | 8.0 | 7% |
| Reader | 7.4 | 12% |
| API and runtime | 9.1 | 10% |
| Data integrity | 9.4 | 10% |
| Security | 8.1 | 10% |
| Backup and recovery | 8.4 | 8% |
| Observability | 6.8 | 6% |
| Accessibility | 7.4 | 6% |
| Performance | 7.7 | 4% |
| Maintainability | 6.3 | 3% |
| Release trust | 8.1 | 2% |
| **Weighted total** | **8.0** | **100%** |

Scores reflect fresh evidence described in reports 02 through 16. Weighting prioritizes Reader, live UX, runtime, data, and security for this private production system.
