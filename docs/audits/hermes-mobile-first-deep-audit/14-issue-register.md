# Issue Register

Severity: P0 means data loss, exposure, auth bypass, or outage. P1 means material correctness, security, recovery, or availability risk. P2 means bounded operational, performance, accessibility, test, or maintainability debt.

Each evidence summary resolves to a numbered audit document or preserved command/browser artifact. [Source: `01-methodology-safety-and-evidence.md`]

| ID | Severity | Confidence | Finding | Evidence | Smallest safe workstream |
|---|---|---|---|---|---|
| SEC-001 | P1 | REPRODUCED | Browser private top-level and subresource targets are continued instead of aborted | Two baseline pytest failures | Repair network guard without changing challenge behavior; add top-level, subresource, redirect, and teardown tests |
| OPS-001 | P1 | REPRODUCED | Verification wrapper can return zero after failed gates | Baseline process returned zero with three pytest failures | Make verification fail-fast or aggregate statuses; test exit propagation |
| READ-001 | P1 | REPRODUCED | Reader disables raw and split modes while source API returns Chinese content | Source response 3,701 chars and 2,783 CJK; modes disabled | Add chapter-selection race test, fix one canonical source-state owner |
| READ-002 | P1 | REPRODUCED | Offline Reader reload loses content with no offline explanation | Three mobile viewports render zero articles offline | Define private cache policy, cache selected content safely, add offline E2E |
| SEC-002 | P1 | CODE_EVIDENCE | Access and refresh tokens are stored in localStorage | `web/src/state/session.ts` | Move refresh token to HttpOnly cookie and define CSRF/logout/rotation contract |
| OPS-002 | P1 | REPRODUCED | Public API container lacks worker-equivalent runtime controls | Docker inspect | Align API caps, no-new-privileges, memory, CPU, and PID limits in approved release |
| OPS-004 | P1 | CODE_EVIDENCE | API readiness ignores worker heartbeat and TTS capability | Readiness response and health route | Aggregate worker heartbeat and explicit optional capability states |
| A11Y-001 | P1 | REPRODUCED | Mobile More dialog lacks focus entry, Escape close, and focus containment | Focused keyboard probe | Implement dialog focus lifecycle and Playwright keyboard regression |
| SEC-003 | P2 | REPRODUCED | Public and local responses lack audited browser security headers | Curl header probes | Define app/Cloudflare header ownership and regression tests |
| SEC-004 | P2 | CODE_EVIDENCE | Auth sessions accumulate without observed pruning | 7,147 total, 4,176 expired | Add bounded retention job and safe aggregate metrics |
| PERF-001 | P2 | REPRODUCED | Glossary and TOC materialize very large DOM trees | 16,813 and 5,342 nodes | Virtualize with keyboard/current-item tests |
| PERF-002 | P2 | REPRODUCED | Reader and status flows issue duplicate requests | Rapid navigation and browser network logs | Centralize ownership, dedupe, cancel stale requests |
| OPS-003 | P2 | REPRODUCED | Runtime image identity cannot be tied to source commit | Different image tags, no Git SHA | Embed and expose commit, image, and build identity |
| OBS-001 | P2 | CODE_EVIDENCE | Metrics remain in memory with no exporter or alerts | No snapshot caller or monitoring config | Expose authenticated low-cardinality metrics and alert on core signals |
| A11Y-002 | P2 | REPRODUCED | Many visible controls are below target size | Mobile scan | Increase visible control hit areas, exclude hidden inputs from metric |
| TEST-001 | P2 | REPRODUCED | Adapter registry test contract is stale | One baseline failure and five omitted domains | Declare one canonical registry and derive expectations |
| TTS-001 | P2 | CODE_EVIDENCE | Low-level F5 engine can fallback to CPU if called outside guarded entry points | Engine device resolver | Make GPU-only invariant local to engine and retain API 503 tests |
| MAINT-001 | P2 | CODE_EVIDENCE | Core modules concentrate thousands of lines and responsibilities | Static line-count scan | Extract only after behavior repairs and contract tests |

## Repair order

1. `SEC-001`, `OPS-001`.
2. `READ-001`, `READ-002`.
3. `SEC-002`, `OPS-002`, `OPS-004`.
4. `A11Y-001`, `A11Y-002`.
5. `PERF-001`, `PERF-002`.
6. Remaining P2 hardening and maintainability work.

## Approval boundary

This register is a repair plan only. No item is authorized for implementation, production restart, or deployment until the operator approves its workstream.
