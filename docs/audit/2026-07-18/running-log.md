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
- Full backend gate passed: 1,103 tests in 5m48s, with only known `passlib`
  and `jieba` deprecation warnings. Frontend Vitest passed 82 files/731 tests;
  Playwright passed 8/8; production build passed.
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
