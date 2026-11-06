# Issue register


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

Open counts: P0 0, P1 2, P2 7, P3 1. P1 confidence is one `REPRODUCED` finding and one `CODE_EVIDENCE` finding. `NOT_TESTED` alert delivery is tracked as P2 debt but is not called a reproduced failure.


## OPS-RECOVERY-001: recovery continuity permission and identity contract

- Severity: P1
- Confidence: REPRODUCED
- Status: REGRESSION
- Previous related issue: `OPS-REC-003`, `OBS-002`
- User impact: the next scheduled backup can fail before publication, and a restore drill can complete core recovery but fail to publish its receipt.
- Reproduction: source current `backup.env`; run `scripts/production_backup.sh --validate-config`; run isolated `scripts/production_restore_drill.sh` with the digest-addressed image and isolated source root.
- Expected: config preflight passes, backup remains executable, restore exits 0, and both receipts become fresh.
- Actual: producer version is missing; image is not digest-pinned; host runner cannot validate the UID 10001-only runtime path; staging receipt publication raises `PermissionError`.
- Evidence: `evidence/backup-config-validation.log`, `evidence/backup-live-data-root-comparison.json`, `evidence/restore-validation.json`.
- Affected components: backup timer, backup script, restore script, recovery receipt publisher, runtime status.
- Data or security risk: future backup continuity and recovery observability are not trustworthy; existing encrypted archive remains valid.
- Smallest safe repair: align host preflight and UID 10001 publisher access without weakening data-root confidentiality; set the approved producer version and digest-addressed image.
- Regression plan: config cases, non-root publisher, complete encrypted restore, receipt parse, status and metrics freshness, failed-publication preservation.
- Validation commands: focused recovery tests, `--validate-config`, isolated restore drill, authenticated status smoke, full `scripts/verify.sh --with-e2e`.
- Approval: protected env edit, permission or ACL change, systemd run, backup creation, and production receipt publication require operator approval.
- Workstream: `workstreams/01-recovery-continuity-and-receipts.md`.

## OPS-RUNBOOK-002: canonical release and rollback runbook is stale

- Severity: P1
- Confidence: CODE_EVIDENCE
- Status: REGRESSION
- Previous related issue: `OPS-003`
- User impact: copy-pasting the canonical procedure selects the previous release and rollback overlays rather than the running Upgrade B release.
- Reproduction: inspect `docs/production-release-runbook.md` lines 14 to 15 and compare with current overlays under `deploy/production/`.
- Expected: exact current release and immediate previous rollback identities and commands are documented.
- Actual: current overlays exist, but canonical variables and expected image examples still name `ux-pwa-001-production-20260724-r1`.
- Evidence: source files and `evidence/live-runtime-second-snapshot.json`.
- Affected components: release, rollback, incident response.
- Data or security risk: delayed or incorrect rollback during an incident.
- Smallest safe repair: update the runbook and add a consistency test that compares its current overlay variables with the tracked release record.
- Regression plan: render Compose images with current and rollback overlays in `config --images` mode; do not restart services.
- Validation commands: documentation contract test, `git diff --check`, full verification.
- Approval: editing docs is safe; executing rollback, restart, merge, or deploy needs explicit approval.
- Workstream: `workstreams/02-release-and-rollback-trust.md`.

## A11Y-SETTINGS-003: Reader settings focus lifecycle fails

- Severity: P2
- Confidence: REPRODUCED
- Status: NEW
- Previous related issue: `A11Y-001` covered the separate More dialog
- User impact: keyboard and assistive-technology users can lose context or tab behind the settings sheet.
- Reproduction: open Reader settings at any required viewport, inspect initial focus, cycle Tab, close with Escape, and inspect restored focus.
- Expected: entry inside, containment, Escape close, and restoration.
- Actual: entry, early containment, and restoration fail in all five viewports; Escape works.
- Evidence: `evidence/browser-summary.json`.
- Affected components: Reader settings sheet and focus manager.
- Data or security risk: none; bounded accessibility failure.
- Smallest safe repair: use the same tested focus lifecycle as the More dialog.
- Regression plan: Playwright tests at 360, 390, 412, 1366, and 1440 widths.
- Validation commands: frontend unit tests, E2E, typecheck, build.
- Approval: no external approval for local code repair; deploy still requires approval.
- Workstream: `workstreams/03-reader-accessibility-mobile-and-requests.md`.

## UX-MOB-007: fixed navigation covers lower visible content

- Severity: P2
- Confidence: REPRODUCED
- Status: REOPENED
- Previous related issue: `UX-MOB-007`
- User impact: the lowest Jobs or Dashboard content can be obscured on short screens.
- Reproduction: open Jobs at 360x740 and inspect the lowest visible card against fixed navigation.
- Expected: content clears the navigation and safe area.
- Actual: lower content enters the navigation region.
- Evidence: `evidence/screenshots/mobile-360x740-jobs-redacted.png`.
- Affected components: mobile shell, Jobs layout, fixed bottom navigation.
- Data or security risk: none; bounded usability and accessibility impact.
- Smallest safe repair: centralize dynamic bottom padding for fixed navigation and safe-area inset.
- Regression plan: screenshot and geometry assertions at all three mobile heights.
- Validation commands: E2E touch and overflow tests, frontend build.
- Approval: local repair only; deployment needs approval.
- Workstream: `workstreams/03-reader-accessibility-mobile-and-requests.md`.

## PERF-READER-002: duplicate translation and noisy progress sync

- Severity: P2
- Confidence: REPRODUCED
- Status: PARTIALLY_FIXED
- Previous related issue: `PERF-002`
- User impact: unnecessary reads and writes increase latency and stale-write risk during navigation or keyboard traversal.
- Reproduction: navigate two chapters rapidly and count normalized request templates.
- Expected: two reads per current-chapter resource and bounded debounced progress writes.
- Actual: two source, two QA, three translation reads; progress sync ranged from 5 to 14 POSTs.
- Evidence: `evidence/browser-summary.json`.
- Affected components: Reader resource hooks, translation request owner, progress synchronization.
- Data or security risk: duplicate reads increase latency; noisy writes increase stale-progress race exposure without evidence of current corruption.
- Smallest safe repair: one translation request owner and coalesced location sync with monotonic revision checks.
- Regression plan: delayed stale response, abort, request count, and final-content identity tests.
- Validation commands: Reader unit tests, E2E, typecheck, build.
- Approval: local repair only; deployment needs approval.
- Workstream: `workstreams/03-reader-accessibility-mobile-and-requests.md`.

## TTS-UI-004: UI recommends forbidden CPU TTS

- Severity: P2
- Confidence: CODE_EVIDENCE
- Status: REGRESSION
- Previous related issue: `TTS-001`
- User impact: the operator may attempt an unsupported configuration even though the backend safely rejects CPU synthesis.
- Reproduction: inspect GPU-unavailable guidance in `web/src/components/reader/useReaderAudio.ts`.
- Expected: explain that a supported GPU is required and Reader remains usable.
- Actual: one message recommends setting `TTS_DEVICE=cpu`.
- Evidence: source file and `evidence/tts-gpu-only.json`.
- Affected components: Reader audio unavailable state and operator guidance.
- Data or security risk: no direct data risk; operator may attempt an unsupported and unsafe configuration.
- Smallest safe repair: replace CPU guidance with policy-compliant unavailable text.
- Regression plan: exact UI copy test plus all TTS no-fallback tests.
- Validation commands: frontend tests, focused TTS tests, E2E, build.
- Approval: local copy repair only; no GPU or paid call.
- Workstream: `workstreams/04-policy-observability-and-hardening.md`.

## OPS-PROV-005: version payload lacks image digest

- Severity: P2
- Confidence: REPRODUCED
- Status: PARTIALLY_FIXED
- Previous related issue: `OPS-003`
- User impact: application self-report is incomplete; operator must reconcile Docker state separately.
- Reproduction: request `/api/version` locally and publicly, then compare `image_digest` with Docker inspection.
- Expected: version payload includes immutable image digest.
- Actual: `image_digest=unknown`; Docker image IDs and source hashes are available externally.
- Evidence: `evidence/live-runtime-second-snapshot.json`.
- Affected components: version endpoint, deployment environment, release provenance.
- Data or security risk: incident responders can select the wrong artifact if they rely only on application self-report.
- Smallest safe repair: inject and validate immutable digest without exposing registry credentials.
- Regression plan: API and worker identity tests plus deploy-overlay consistency.
- Validation commands: runtime identity tests, Compose config render, local and public `/api/version` probes, source-to-image comparison, full verification.
- Approval: protected Compose or deployment environment edit requires approval.
- Workstream: `workstreams/02-release-and-rollback-trust.md`.

## OBS-ALERT-006: external alert delivery not demonstrated

- Severity: P2
- Confidence: NOT_TESTED
- Status: PARTIALLY_FIXED
- Previous related issue: `OBS-003`
- User impact: an unattended outage or stale backup may not reach the operator.
- Reproduction: inspect configured alert paths and preserved delivery receipts; no external receipt is present.
- Expected: one controlled alert reaches an approved operator channel and records a redacted receipt.
- Actual: alert rules pass tests, but no external delivery was demonstrated.
- Evidence: alert rules pass tests; no external delivery receipt exists.
- Affected components: operational alert dispatcher, public-health monitoring, operator notification.
- Data or security risk: delayed response to outage, worker failure, disk pressure, or stale recovery state.
- Smallest safe repair: configure one bounded external public-health and alert delivery path with redacted receipts.
- Regression plan: controlled test alert, delivery, retry, redaction, and recovery.
- Validation commands: alert rule tests, dry-run payload redaction, approved delivery test, receipt verification, public-health recovery probe.
- Approval: external post and service signup require explicit approval.
- Workstream: `workstreams/04-policy-observability-and-hardening.md`.

## UX-LOGIN-007: install prompt overlaps login controls

- Severity: P2
- Confidence: REPRODUCED
- Status: NEW
- Previous related issue: none
- User impact: reduced clarity and accidental interaction risk at short desktop height.
- Reproduction: open the public login page at 1280x577 and inspect the install prompt against login and forgotten-password controls.
- Expected: installation guidance remains visually separate from authentication actions.
- Actual: the prompt overlaps or crowds the authentication action area.
- Evidence: fresh public login screenshot observation.
- Affected components: public login page and PWA install prompt.
- Data or security risk: no direct data risk; bounded accidental-interaction risk.
- Smallest safe repair: reserve vertical space or move the prompt outside the authentication action stack.
- Regression plan: screenshot at 1280x577 plus mobile login widths.
- Validation commands: targeted login-layout E2E, screenshot geometry assertions, frontend tests, typecheck, build.
- Approval: local UI repair only; deployment needs approval.
- Workstream: `workstreams/03-reader-accessibility-mobile-and-requests.md`.

## SEC-FILE-008: token-like file permission needs review

- Severity: P3
- Confidence: SUSPECTED
- Status: NEW
- Previous related issue: none
- User impact: no current impact established.
- Reproduction: inspect file metadata inside the production API container and search current source for a consumer without reading the file value.
- Expected: every token-like file has a documented owner, least-privilege mode, and active consumer or a removal record.
- Actual: the file is mode `0644`, its parent is owner-private, and no current source consumer was found.
- Evidence: owner UID/GID 10001, mode `0644`, no current source reference found, parent data root mode `0750`.
- Affected components: production data filesystem and legacy extension integration.
- Data or security risk: defense-in-depth only unless a reader outside the intended UID can reach the file.
- Smallest safe repair: identify owner and format, then tighten or remove only with explicit evidence and rollback.
- Regression plan: metadata and consumer tests without logging the value; verify application startup and extension contract if still used.
- Validation commands: source search, container metadata probe, focused security tests, full verification.
- Approval: permission change or deletion requires explicit approval.
- Workstream: `workstreams/04-policy-observability-and-hardening.md`.
