# Canonical Issue Register

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Severity definitions

- P0: active data loss, compromise, or total outage.
- P1: core workflow failure or serious release-trust gap requiring the next repair cycle.
- P2: meaningful reliability, privacy, operations, or maintainability weakness.
- P3: polish or low-risk hardening.

## Open findings

### UX-PWA-001 | P1 | REPRODUCED + CODE_EVIDENCE

**First-session Reader offline reload can be blank after successful cache feedback.**

Reproduction:
1. Start a fresh browser context.
2. Login and open a Reader chapter.
3. Wait for service-worker readiness without reloading online.
4. Select `Tải chương hiện tại offline`.
5. Confirm success feedback and manifest persistence.
6. Go offline and reload.

Expected: cached Reader shell, chapter content, and offline indicator render.

Actual: blank page, zero text, no article, no offline indicator. The warmed control path passes after one online controlled reload.

Impact: user trusts a successful offline action and can lose access when connectivity drops immediately.

Evidence: first-session and warmed PWA JSON and screenshots under `/tmp/novel-tnn-live-audit/controller/browser-fresh/`; `web/public/reader-offline-sw.js`.

Repair: make shell-cache assets immediately available to fetch handling, or delay success until app-shell readiness is verified.

### TEST-PWA-002 | P2 | CODE_EVIDENCE

**Current E2E misses the first-session offline path.**

The test reloads online after service-worker readiness before going offline. It proves only the warmed path. Add a fresh-context case with no preparatory reload and retain the protected-API non-caching assertions.

Evidence: `web/e2e/novel-tnn.spec.ts` offline test.

### OPS-REC-003 | P2 | REPRODUCED + CODE_EVIDENCE

**Runtime cannot prove external backup or restore freshness.**

The backup directory is outside container mounts. The runtime restore-status file is absent. Status and metrics can therefore be green while the latest external backup or drill is stale.

Evidence: Docker mount inspection, operator backup scan, `/data/logs/runtime/restore-drill.status.json` probe.

Repair: ingest minimal signed or permission-controlled receipts containing timestamp, status, archive identity hash, and age. Never mount passphrases or backup contents into the API.

### SEC-DEP-004 | P2 | REPRODUCED

**Python dependency advisory debt remains.**

Fresh pip audit reports four rows across three unique package and advisory pairs. Pytest and setuptools have fixes; ECDSA has none in the report.

Evidence: `/tmp/novel-tnn-live-audit/controller/pip-audit.json`.

Repair: upgrade fixed tooling, verify JWT algorithm reachability, and replace or isolate ECDSA if any signing path is reachable.

### PRIV-TTS-005 | P2 | CODE_EVIDENCE

**F5 upstream DEBUG capture is not content-redacted.**

`_capture_upstream_output` can log the final 4,000 characters of raw stdout and stderr.

Evidence: `app/services/tts/f5_vietnamese_engine.py:133-142`.

Repair: structured allowlist logging only. Never emit chapter text, private paths, model prompts, or provider payloads.

### ARCH-006 | P2 | CODE_EVIDENCE

**Core change-risk hotspots remain oversized.**

Twenty-seven source files exceed 1,000 lines. PipelineService spans about 3,315 lines and ReaderView exceeds 4,200 lines.

Evidence: fresh line and AST scan.

Repair: defer until P1 is fixed, then extract one contract at a time with caller-impact analysis and behavior-preserving tests.

### UX-MOB-007 | P2 | REPRODUCED

**Fixed mobile controls can cover lowest visible content.**

Dashboard and Jobs screenshots show lower copy entering the bottom-navigation region; Reader has the same risk near chapter controls.

Evidence: mobile screenshots and vision review.

Repair: enforce dynamic safe-area and bottom-control padding at all short viewports.

### UX-DISC-008 | P3 | REPRODUCED

**Reader mode and offline actions have weak discoverability.**

Raw, Split, QA, and offline actions are nested under More. The online reading surface remains usable.

Evidence: live Reader button inventory and More menu review.

Repair: surface stateful mode access without crowding the reading canvas.

### OPS-CSP-009 | P3 | REPRODUCED

**Cloudflare Analytics injection creates CSP console noise.**

The CSP correctly blocks the beacon, but recurring console errors reduce diagnostic signal.

Evidence: live browser console; public CSP headers.

Repair: disable unwanted injection or explicitly decide and document a minimal allowlist.

### A11Y-VIS-010 | P3 | REPRODUCED + SUSPECTED

**Dense tables and muted secondary copy need formal contrast and zoom certification.**

Touch targets and keyboard focus behavior pass. Small provider and glossary text remains visually dense.

Evidence: desktop screenshots; fresh keyboard and touch audit.

Repair: run measured contrast, 200 percent zoom, and screen-reader certification before changing typography.

## Closed or non-issues

- General offline Reader failure: closed. Warmed protocol passes.
- TTS unavailable without GPU: policy-compliant degradation, not a defect.
- Production data corruption: not observed.
- Active stale jobs or leases: not observed.
- Missing production artifacts: not observed.
- CORS hostile origin acceptance: denied in fresh probe.

## Counts

- P0: 0
- P1: 1
- P2: 6
- P3: 3
- Open total: 10
