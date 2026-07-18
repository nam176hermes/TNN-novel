# Novel-TNN quality audit — issue register

This register records only findings reproduced against the native-WSL
deployment or current checkout on 2026-07-18.  Historic audit documents are
context, not evidence of the current release.

## Severity policy

- **P0** — data loss/exposure, authentication bypass, public outage, or an
  unsafe production action. Stop affected work until contained.
- **P1** — a material correctness, security, recovery, or availability risk.
- **P2** — operational, workflow, performance, or maintainability debt with a
  bounded workaround.
- **P3** — polish, low-risk documentation, or developer-experience debt.

## Open findings

| ID | Severity | Finding | Reproduction/evidence | Regression coverage | Smallest safe resolution | Status |
|---|---|---|---|---|---|---|
| AUD-003 | P2 | The running containers retain superseded external Compose overlays in their provenance labels. | `docker inspect` lists the historical Phase 4 and TTS overlays under `~/.local/state/...`; the canonical runbook says new release commands should instead use the tracked runtime-hardening overlay. Current image tags match the intended runtime-hardening images. | Render the canonical two-file Compose chain with production env and compare its image/service contract to the live containers. | During an explicitly approved release window, recreate only from the canonical tracked overlay chain; retain documented rollback images. | Verified; no production action authorized in this audit pass. |
| AUD-012 | P2 | Direct import and source-health URL preflight are not bound to the later HTTP peer address (DNS rebinding). | Immutable-snapshot scan DS-002 and DS-006 prove policy resolves an accepted hostname before `requests` resolves it again; no useful sensitive internal target was exercised. | Existing URL-policy/source-health tests cover literal non-global IP rejection but not peer-address binding. | Design one shared safe HTTP transport that binds a vetted DNS answer to the connection, with redirect and TLS semantics tested across all callers. | Open; do not represent DNS preflight alone as a complete SSRF control. |
| AUD-013 | P2 | Browser-fallback import still navigates by hostname after validation. | DS-003 static trace shows `page.goto` receives the hostname; browser-specific connection pinning and useful-target impact were not proven. | No applicable safe Chromium-pinning regression exists. | Establish an explicit browser egress/pinning policy and validate it in an isolated test environment before changing fallback navigation. | Deferred with an explicit proof/design gap, not treated as a confirmed P1. |
| AUD-014 | P3 | Several authenticated import/Reader resource limits remain unbounded. | DS-004, DS-007, DS-008, DS-014, DS-015 and DS-016 establish CSS recursion/reparse, gzip/aggregate decode, regex backtracking, and parser materialization paths. No persistent service outage was demonstrated. | Focused current tests protect existing behavior, not the proposed resource budgets. | Schedule small independent hardening changes: CSS work/cache budgets, streaming aggregate decode, bounded regex execution, and dictionary record/stream limits. | Open technical debt; none is a P0/P1 under the recorded attack-path policy. |

## Closed or ruled-out in this pass

| ID | Result | Evidence |
|---|---|---|
| AUD-001 | Closed — P1 operational documentation. | `511efc2` corrects the R2 multipart/resume runbook; `tests/test_production_backup_schedule.py` passes 6/6, including a regression assertion for the documented contract. |
| AUD-002 | Closed — P2 verifier usability. | `541c04e` adds opt-in `--production --env-file` validation without sourcing secrets. Its 4/4 regression tests pass, and the live external env file passes with public mode enabled and zero public-config errors. |
| AUD-004 | Closed — P2 WSL test performance. | `7b54aa4` keeps test SQLite fixtures on native `/tmp` only when a WSL process inherits a `/mnt/...` temp location. The formerly stalled 25-test TTS group passes in 12.04 seconds under the default environment. |
| AUD-005 | Closed — P3 desktop UI asset. | `aacc141` fixes two stylesheet-relative scenery URLs. Targeted stylesheet test passes 14/14 and Vite now emits `sidebar-scenery` without a resolution warning. |
| AUD-007 | Closed — P1 off-site backup retention. | Read-only R2 inspection found two complete archive sets while `r2_list_archive_names` returned none. `4edf3b8` corrects its raw-regex escaping; the behavioral regression seeds an old archive, retains one off-site copy, and verifies removal of the old archive, sidecar, and checksum. The related backup/API/job suite passes 40/40. |
| AUD-008 | Closed — P1 Reader QA-overlay rendering. | The new regression initially reproduced the defect: the 120th paragraph of a 180-paragraph QA-overlay chapter rendered immediately. `cee8872` applies the existing 80-paragraph progressive-scroll contract to QA overlay; it verifies 80 initial paragraph blocks and 160 after one near-edge scroll. Reader and chapter-text suites pass 105/105. |
| AUD-006 | Closed — exhaustive deep-security discovery. | Seven discovery rounds covered the 356-row worklist to saturation. All 16 canonical candidates have validation and attack-path receipts under the private scan bundle; three P1 findings were remediated in `5188adb`, `7723ae7`, and `28ad489`. |
| AUD-009 | Closed — P1 unsafe external API defaults. | DS-001 proved an externally bound API could run with known administrator defaults. `28ad489` makes non-loopback binds require public-deploy safety checks and non-default credentials; focused security tests plus the fresh full gate pass. |
| AUD-010 | Closed — P1 unauthenticated legacy dashboard. | DS-011 found 13 unguarded legacy FastAPI routes when externally bound. `7723ae7` makes the legacy dashboard loopback-only; `tests/test_web_dashboard_security.py` passes. |
| AUD-011 | Closed — P1 request-controlled translation egress/credential exposure. | DS-012 proved an authenticated job could select an arbitrary translation host while the client could fall back to configured credentials. `5188adb` permits host selection only through registered providers; focused tests and the full gate pass. |
| AUD-R04 | No P0 from the completed security scan. | Attack-path policy calibrated all remaining reproducible security candidates to P2/P3 or explicit deferred/ignore. The current checkout passes 1,112 backend tests, 733 frontend tests, typecheck, build, Playwright 8/8, and local/public health/readiness. |
| AUD-R01 | No public-ingress P0 at audit start. | HTTPS `GET /api/health` and `GET /api/ready` both returned `status: ok`; Cloudflare Tunnel terminates the public route and local API is loopback-only. |
| AUD-R02 | No SQLite integrity defect at audit start. | API-container read-only checks returned `integrity_check=ok` and zero `foreign_key_check` rows. |
| AUD-R03 | No direct public database exposure or unauthenticated operator-route access. | HTTPS `GET /data/pipeline.db`, docs/OpenAPI/Redoc return `404`; unauthenticated books and backups return `401` with `Cache-Control: private, no-store`. |

Do not close an open item solely because a historical report claimed it fixed.
