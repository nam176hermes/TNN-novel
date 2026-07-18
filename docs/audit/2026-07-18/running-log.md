# Novel-TNN quality audit — running log

## 2026-07-18 — baseline and production read-only verification

- Confirmed the audit branch is clean at `f83fdf3`; no production files,
  containers, configuration, or database rows were changed.
- Passed Python compile, shell syntax, and lint.  `scripts/check-environment.sh`
  failed only on production-specific assumptions; this is AUD-002, not a
  service-health result.
- Rendered Compose successfully with the external production environment file
  without displaying secret values.
- Confirmed API and import worker are healthy, mount the same `/data` volume,
  and the API binds only to `127.0.0.1:7860`.
- Confirmed local and public HTTPS `GET /api/health` and `GET /api/ready`.
- Identified ingress architecture by read-only inspection: systemd user unit
  `trading-cf-tunnel.service` runs Cloudflare Tunnel, mapping the public Novel
  hostname to the loopback API origin.
- Confirmed public CORS accepts only the configured HTTPS origin and rejects a
  localhost origin; the public database-path probe returns a private 404.
- Ran read-only in-container SQLite integrity and foreign-key checks; both
  passed.  Recorded table/row-count baseline in the feature matrix.
- Discovered and recorded three actionable audit findings (AUD-001 through
  AUD-003).  No P0 condition is open at this point.

## 2026-07-18 — fixes and complete baseline gates

- Closed AUD-001 in `511efc2`: corrected the stale R2 >5 GiB runbook claim and
  added a regression assertion. The focused runner suite passed 6/6.
- Closed AUD-004 in `7b54aa4`: WSL tests now keep SQLite fixture files off an
  inherited Windows-mounted temp path. The focused TTS suite passes 25/25 in
  12.04 seconds under the normal shell environment.
- Closed AUD-005 in `aacc141`: corrected two stylesheet-relative scenery asset
  paths. The focused style suite passes 14/14 and the production build bundles
  the scenery asset without a warning.
- Closed AUD-002 in `541c04e`: added a strict, opt-in production mode to the
  environment checker and `scripts/verify.sh`. Four regression tests pass and
  the live external env file validates without displaying its values.
- Combined production-mode `scripts/verify.sh` passed: 1,103 backend tests in
  5m46s, frontend Vitest 82 files/732 tests, and a production build with the
  scenery asset bundled. Only known `passlib` and `jieba` deprecation warnings
  remain. The separately rerun Playwright suite passed 8/8.
- Reconfirmed artifact scan: 1,715 populated artifact paths, zero missing,
  outside-data, or legacy-prefix paths. Production F5 TTS returns the safe
  `tts_unavailable` result on the non-GPU host.
- Confirmed public/local health and readiness, disabled API documentation,
  protected unauthenticated books/backups, Cloudflare no-store behavior, worker
  health, shared data mount, and `0660` SQLite/WAL/SHM modes.
- Deep-security exhaustive discovery remains blocked by global Codex agent
  configuration; AUD-006 records the exact preflight result. AUD-003 remains
  intentionally open because replacing live Compose provenance needs a separate
  approved release window.

## 2026-07-18 — off-site backup retention audit

- Read-only validation of `~/.config/novel-tnn/backup.env` confirmed strict
  `0600` permissions, all required values, successful R2 authentication, and
  an enabled daily systemd timer. No secret values were displayed.
- R2 contains two encrypted archive sets. Each remote checksum equals the
  corresponding local checksum and each remote sidecar is encrypted, `READY`,
  and names its expected archive.
- Found AUD-007: the upload path was correct, but the raw-string regex used by
  remote retention escaped the archive extension twice and consequently matched
  no valid archive names. `4edf3b8` uses literal-dot regex escapes and adds a
  behavioral rotation regression. The production backup scheduler/API/job suite
  passes 40/40; the retention suite passes 23/23.

## 2026-07-18 — Reader long-chapter/QA audit

- The Reader cache-owner check is already covered: `App` delegates cache
  ownership to Reader in Reader view, and `useChapterText` does not re-read the
  current cache in that mode.
- Reproduced AUD-008 before the fix: QA overlay rendered paragraph 120 of a
  180-paragraph chapter immediately, bypassing the 80-paragraph progressive
  scroll limit used by normal translation mode.
- Closed AUD-008 in `cee8872`: non-rich QA overlay now uses the same bounded
  visible paragraph/rich-block inputs. The regression checks 80 initial blocks
  and 160 after a near-edge scroll. Reader plus chapter-text tests pass 105/105
  and TypeScript typecheck passes.

## 2026-07-18 — final non-security validation gate

- `scripts/lint.sh`, the production external-environment check, and four
  independent local/public `/api/health` and `/api/ready` probes passed.
- Combined production-mode `scripts/verify.sh` passed with 1,103 backend tests,
  Vitest 82 files/733 tests, typecheck, and the production build. Playwright
  workflow coverage also passed 8/8.
- The only remaining exhaustive-audit gap is AUD-006: deep-security discovery
  needs explicit operator approval for the global Codex `agents.max_depth`
  setting. No production change, deploy, or global configuration change was
  made during this audit pass.

## 2026-07-18 — deep-security completion and post-remediation gate

- Re-ran the approved deep-security workflow through seven discovery rounds.
  The authoritative 356-row worklist was covered to saturation; all sixteen
  canonical candidates have validation and attack-path receipts in the private
  scan bundle. No P0 was found.
- Three P1 source findings were reproduced and fixed as isolated commits:
  unsafe external API defaults (`28ad489`), externally bindable unauthenticated
  legacy dashboard (`7723ae7`), and request-controlled translation
  destination/credential egress (`5188adb`). `c0854d7` also rejects every
  non-global parser-candidate address; `00f69c3` hardens Host-header public
  classification.
- Remaining security work is explicitly bounded: direct/source-health DNS
  rebinding is P2, browser fallback is deferred pending a safe browser egress
  design, and authenticated parser/Reader resource ceilings are P3. These are
  registered as AUD-012 through AUD-014.
- Fresh current-checkout release gates passed without production mutation:
  `scripts/verify.sh` with the external production env file (1,112 backend
  tests, 733 frontend tests, production build), independent TypeScript
  typecheck, and Playwright 8/8. Both local and public `/api/health` and
  `/api/ready` returned `status: ok`.
- The live production containers were not rebuilt, recreated, or deployed in
  this workstream. The endpoint probes verify current service availability, not
  release of the new commits.

## 2026-07-18 — security artifact-retention correction

- The deep-security working bundle was stored beneath the system temporary
  directory and was pruned before its canonical final report could be sealed.
  No production data, repository source, Git commit, container, or operator
  configuration was lost or changed.
- Updated the audit record to avoid claiming the missing per-candidate receipt
  files are still available. `security-review.md` retains the durable finding,
  remediation, validation, and deployment-boundary summary. A future formal
  scan must use an operator-selected durable evidence directory before running.
