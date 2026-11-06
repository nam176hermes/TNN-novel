# Scorecard


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

The arithmetic mean of the first 19 category scores is 7.46. Overall readiness is capped at 6.8 because open P1 recovery and release-control findings prevent certification. Scores do not increase merely because features exist.


| Category | Score | Previous | Evidence | Works | Fails or limit | Regression status | Confidence | Requirement for next score |
|---|---:|---:|---|---|---|---|---|---|
| Real-user usability | 7.2 | 7.7 | Five viewports and route screenshots | Daily read paths open | Recovery administration not trustworthy | Down 0.5 | REPRODUCED | Complete operator mutation journey in staging |
| Mobile UX/UI | 7.1 | 7.5 | Three required mobile widths | No overflow; touch targets pass | Bottom nav can cover content | Down 0.4 | REPRODUCED | Repair safe-area padding and retest |
| Mobile Reader | 7.4 | 7.4 | Reader and rapid-navigation traces | One surface; no stale visible overwrite | Settings focus and one duplicate read | Stable | REPRODUCED | Full live mode matrix and focus pass |
| Desktop UX/UI | 8.0 | 8.0 | Two desktop widths | Routes and Reader open cleanly | No full desktop mutation path | Stable | REPRODUCED | Complete keyboard and operator journey |
| Import experience | 7.5 | n/a | E2E plus backend fixtures | Paste, file, parser, duplicate contracts | No authorized third-party live import | New category | CODE_EVIDENCE | Isolated end-to-end staged commit and rollback |
| Translation workflow | 7.4 | n/a | E2E and backend tests | Create, retry, cancel, stale recovery contracts | No paid provider run | New category | CODE_EVIDENCE | Approved non-production provider smoke |
| Glossary and QA | 8.0 | n/a | Frontend and backend tests | Deterministic QA and bounded lists | No production-scale keyboard replay | New category | CODE_EVIDENCE | Full virtualized keyboard and screen-reader pass |
| Jobs and recovery | 7.0 | n/a | Jobs UI and workflow tests | Status, retry, cancellation contracts | Recovery receipt integration fails | New category | REPRODUCED | Receipt-integrated recovery exit 0 |
| TTS and audio readiness | 7.0 | n/a | API and low-level probes | No CPU fallback; typed unavailable | UI recommends CPU; no GPU test | New category | REPRODUCED | Fix guidance and approved GPU smoke |
| PWA and offline | 8.0 | prior Reader 7.4 | First-session, warmed, and adversarial lifecycle evidence | Offline paths, logout cleanup, and stale-cache cleanup pass | Public fresh-profile path excluded | Improved | REPRODUCED | Authorized public fresh-profile confirmation |
| Data integrity | 9.4 | 9.4 | SQLite and artifact scan | No corruption, orphan, duplicate, or missing active artifact | Continuous monitoring outside audit | Stable | REPRODUCED | Repeat after a controlled restore receipt pass |
| Backup and recovery | 5.0 | 8.4 | Archive and restore evidence | Existing encrypted archive restores | Future backup and receipt integration fail | Down 3.4 | REPRODUCED | Fix P1 and complete full drill exit 0 |
| Authentication and security | 8.8 | 8.1 | Session lifecycle, headers, SSRF, dependency audit | Rotation, reuse, CSRF, CORS, advisories pass | Token-like file purpose unknown | Up 0.7 | REPRODUCED | Resolve file ownership and public cookie confirmation |
| Performance | 7.7 | 7.7 | DOM, requests, bundles, runtime sample | Bounded DOM and no long tasks | Duplicate translation and no soak | Stable | REPRODUCED | Remove duplicate and run long-chapter soak |
| Accessibility | 6.8 | 7.4 | Focus and touch probes | More dialog and touch targets pass | Settings focus fails | Down 0.6 | REPRODUCED | All Reader dialogs pass focus lifecycle |
| Production runtime | 9.0 | 9.1 | Docker and endpoint snapshot | Hardened, healthy, no restarts | Graceful shutdown not fault-tested | Down 0.1 | REPRODUCED | Staging shutdown and restart recovery proof |
| Readiness and observability | 7.0 | 6.8 | Readiness tests and live payload | Worker, release, disk, TTS semantics | No delivery receipt; recovery states missing | Up 0.2 | REPRODUCED | Fresh receipts plus delivered alert |
| CI and release trust | 7.0 | 8.1 | Full gate and provenance | 12 E2E; source-image hashes match | Dirty worktree; stale runbook; API digest unknown | Down 1.1 | REPRODUCED | Clean tree and current copy-safe rollback record |
| Maintainability | 6.5 | 6.3 | Static scan and test baseline | Bounded extraction preserved contracts | Large ownership hotspots remain | Up 0.2 | CODE_EVIDENCE | One defect-backed narrow extraction |
| Overall private-production readiness | 6.8 | 8.0 | All reports | Core private use is healthy | Two open P1 certification blockers | Down 1.2 | REPRODUCED | Zero open P0/P1 and all release gates satisfied |


No category receives 9 or 10 for a workflow that lacked live failure and recovery evidence. Data integrity receives 9.4 because both live read-only checks and an isolated encrypted restore were completed, with the separate operational receipt failure kept visible.
