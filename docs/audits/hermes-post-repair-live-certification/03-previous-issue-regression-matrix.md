# Previous issue regression matrix


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

Only the required status vocabulary is used in the matrix. [Source: evidence/test-summary.json] [Source: evidence/browser-summary.json]


| Previous issue or repaired contract | Current status | Live evidence | Test evidence | Runtime evidence | Regression found |
|---|---|---|---|---|---|
| `OPS-001` verification masking | VERIFIED_FIXED | Forced failing gate returned non-zero | Self-test exit 97; missing browser exit 1 | Full gate exit 0 | No |
| `SEC-001` browser private network isolation | VERIFIED_FIXED | Live third-party bypass intentionally excluded | Focused SSRF and browser tests pass | Protected browser path unchanged | No |
| `TEST-001` stale adapter registry | VERIFIED_FIXED | Not a live mutation | Canonical registry tests pass | Production image matches source | No |
| `READ-001` Reader source ownership | VERIFIED_FIXED | One Reader surface after rapid navigation | Current-chapter raw and split E2E pass | Source, translation, and QA APIs returned 200 in staging | No stale visible overwrite |
| `PERF-002` duplicate Reader requests | PARTIALLY_FIXED | Two chapter changes produced 2 source, 2 QA, and 3 translation reads | Ownership tests pass | No failed API request | One extra translation read remains |
| Raw and Split availability | VERIFIED_FIXED | Custom exact-name locator inconclusive | Release E2E passes raw and split | Source and translation artifacts exist | No known correctness regression |
| `READ-002` / `UX-PWA-001` first-session offline | VERIFIED_FIXED | Isolated first-session reload returned one Reader surface and cached text | First-session E2E passes | Service worker controlled client and shell/runtime caches existed | No |
| Warmed offline Reader | VERIFIED_FIXED | Warmed reload returned one Reader surface | Warmed E2E passes | Cache names stable | No |
| Corrupted and shell-only offline failure handling | VERIFIED_FIXED | Isolated rerun retained the Reader shell and one readable surface with zero page errors | Lifecycle tests pass | Harness exit 0 | No |
| Logout private Reader storage cleanup | VERIFIED_FIXED | Isolated logout cleared Reader localStorage keys and reduced cached chapters from 1 to 0 | Logout cache tests pass | Login surface returned | No |
| Stale Reader cache revision cleanup | VERIFIED_FIXED | Stale v1 shell and runtime caches were purged while an unrelated cache remained | Cache-revision tests pass | Current v6 shell cache remained | No |
| `A11Y-001` Reader More dialog focus | VERIFIED_FIXED | All five viewports passed entry, containment, Escape, and restoration | Release accessibility tests pass | n/a | No |
| Reader settings dialog focus | REGRESSION | All five viewports failed entry and restoration | Existing gate did not catch this dialog | n/a | Yes, `A11Y-SETTINGS-003` |
| `A11Y-002` touch targets | VERIFIED_FIXED | No visible undersized controls in sampled routes | Touch-target E2E passes | n/a | No |
| `SEC-002` browser-readable refresh token | VERIFIED_FIXED | localStorage empty; sessionStorage held only access token key | Auth tests pass | Refresh cookie HttpOnly in lifecycle probe | No |
| CSRF and session lifecycle | VERIFIED_FIXED | Rotation, reuse rejection, logout and logout-all pass in staging | Security and repository tests pass | No production login mutation | No |
| `SEC-003` security headers | VERIFIED_FIXED | CSP, HSTS, DENY, nosniff present | Header tests pass | Hostile CORS origin rejected | No |
| `SEC-004` session retention | VERIFIED_FIXED | n/a | Retention tests pass | 0 expired-unrevoked and 0 older than 30 days | No |
| `OPS-002` API container hardening | VERIFIED_FIXED | n/a | Runtime contract tests pass | Non-root, read-only root, cap drop, limits, no-new-privileges | No |
| `OPS-004` worker-aware readiness | VERIFIED_FIXED | Public and local readiness pass | Missing, stale, and mismatch tests pass | Fresh heartbeat and release match | No |
| `TTS-001` GPU-only invariant | VERIFIED_FIXED | API returns typed 503 in staging | API, pipeline, and engine tests pass | Production reports `gpu_unavailable` without CPU | Backend fixed; UI guidance regressed |
| `OPS-003` release provenance | PARTIALLY_FIXED | Public version exposes Git SHA and release | Runtime identity tests pass | Docker image IDs and file hashes reconcile; API digest is unknown | Bounded P2 gap |
| `OBS-001` metrics and alerts | PARTIALLY_FIXED | Unauthenticated endpoint denied | Metrics and alert rules pass | External delivery not demonstrated | No exporter regression; delivery gap remains |
| `OPS-REC-003` recovery freshness | REOPENED | Receipts missing | Receipt parser and publisher tests pass | Backup preflight and restore receipt integration fail | Yes, P1 |
| Mandatory browser E2E gate | VERIFIED_FIXED | n/a | 12 of 12 Chromium tests pass | Gate is required by verification script | No |
| `PERF-001` large Glossary and TOC DOM | VERIFIED_FIXED | Sampled operator trees remain bounded | Virtualization tests pass | Reader initial DOM 327 to 479 nodes | No |
| `PRIV-TTS-005` TTS log privacy | VERIFIED_FIXED | Bounded log scan found no content or secret markers | TTS tests pass | 22 log files and 377,886 bytes scanned | No |
| `SEC-DEP-004` dependency advisories | VERIFIED_FIXED | n/a | npm and Python audits exit 0 | 0 current advisories in captured reports | No |
| `ARCH-006` bounded extraction | PARTIALLY_FIXED | n/a | Full suites pass | 24 modules remain over 1,000 lines | No behavioral regression |


All eight P1 findings from the mobile-first deep audit were retested and are verified fixed. The final PWA adversarial rerun recorded zero harness errors and all seven explicit assertions true. Initial unauthenticated `/api/auth/refresh` HTTP 401 responses were expected session-bootstrap denials and did not produce page errors. Recovery freshness was previously P2 and is reopened and promoted as the new combined P1 `OPS-RECOVERY-001`. The previous More-dialog P1 is fixed; the separate settings dialog focus defect is new P2 debt. [Source: evidence/pwa-adversarial.json]
