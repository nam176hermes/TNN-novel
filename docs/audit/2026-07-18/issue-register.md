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
| AUD-006 | P2 | The configured deep-security workflow cannot begin exhaustive discovery. | Its capability preflight is `blocked`: current Codex runtime has `agents.max_depth=1`, but repository-wide deep scan requires 2. It also recommends eight worker slots; six are currently available. | Rerun the documented preflight after any approved global configuration change. | Obtain operator approval to change global Codex agent settings, then rerun the preflight before using the six-worker discovery protocol. | Blocked on explicit global-tooling approval; no repository or production change made. |

## Closed or ruled-out in this pass

| ID | Result | Evidence |
|---|---|---|
| AUD-001 | Closed — P1 operational documentation. | `511efc2` corrects the R2 multipart/resume runbook; `tests/test_production_backup_schedule.py` passes 6/6, including a regression assertion for the documented contract. |
| AUD-002 | Closed — P2 verifier usability. | `541c04e` adds opt-in `--production --env-file` validation without sourcing secrets. Its 4/4 regression tests pass, and the live external env file passes with public mode enabled and zero public-config errors. |
| AUD-004 | Closed — P2 WSL test performance. | `7b54aa4` keeps test SQLite fixtures on native `/tmp` only when a WSL process inherits a `/mnt/...` temp location. The formerly stalled 25-test TTS group passes in 12.04 seconds under the default environment. |
| AUD-005 | Closed — P3 desktop UI asset. | `aacc141` fixes two stylesheet-relative scenery URLs. Targeted stylesheet test passes 14/14 and Vite now emits `sidebar-scenery` without a resolution warning. |
| AUD-007 | Closed — P1 off-site backup retention. | Read-only R2 inspection found two complete archive sets while `r2_list_archive_names` returned none. `4edf3b8` corrects its raw-regex escaping; the behavioral regression seeds an old archive, retains one off-site copy, and verifies removal of the old archive, sidecar, and checksum. The related backup/API/job suite passes 40/40. |
| AUD-R01 | No public-ingress P0 at audit start. | HTTPS `GET /api/health` and `GET /api/ready` both returned `status: ok`; Cloudflare Tunnel terminates the public route and local API is loopback-only. |
| AUD-R02 | No SQLite integrity defect at audit start. | API-container read-only checks returned `integrity_check=ok` and zero `foreign_key_check` rows. |
| AUD-R03 | No direct public database exposure or unauthenticated operator-route access. | HTTPS `GET /data/pipeline.db`, docs/OpenAPI/Redoc return `404`; unauthenticated books and backups return `401` with `Cache-Control: private, no-store`. |

Do not close an open item solely because a historical report claimed it fixed.
