# Executive summary


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Decision

**NO_GO for release certification.**

Novel-TNN remained online and usable during the audit. Local and public health and readiness returned HTTP 200, the API and worker stayed healthy, database integrity passed, full verification passed, and no production data mutation was observed. Certification is blocked by two open P1 operational defects: the scheduled backup and restore receipt workflow is reproduced as incompatible with its current identity and filesystem contract, while source evidence shows that the canonical release runbook still points to the previous release overlays. [Source: evidence/live-runtime-second-snapshot.json] [Source: evidence/backup-config-validation.log] [Source: `docs/production-release-runbook.md`]

This is not an outage declaration. It is a refusal to certify recovery and rollback controls that are not currently executable as documented.

## Comparison with the previous audit

The previous live-user audit scored 8.0 and had one P1 first-session offline defect. That PWA defect is now verified fixed in deterministic E2E and isolated black-box staging. A final isolated adversarial rerun also completed with exit 0, zero harness errors, and all seven explicit lifecycle assertions true. The current release improves session security, dependency hygiene, TTS privacy, readiness, and source-to-image matching. Recovery continuity and rollback documentation regressed after the new receipt and release requirements were introduced. The readiness score is therefore capped at 6.8 despite a 7.46 arithmetic mean across the other scored categories. [Source: evidence/test-summary.json] [Source: evidence/browser-summary.json] [Source: evidence/pwa-adversarial.json] [Source: `docs/audits/hermes-live-user-first-audit/17-feature-matrix-and-scorecard.md`]

## Finalization revision

Revision 2 closed the audit continuation. The shadow audit container was stopped and removed. Fresh local and public health, readiness, and version probes returned HTTP 200. Both production containers remained healthy, SQLite integrity returned `ok`, foreign-key violations remained zero, and the shadow container was absent. [Source: evidence/continuation-final-health.json]

## Previous issues verified fixed

- Verification child failures propagate non-zero.
- Browser private-network requests are aborted in focused contract tests.
- Source adapters use one registry contract and reject duplicate IDs and domains.
- Reader raw and split ownership is covered by current-chapter E2E.
- First-session and warmed offline Reader paths pass.
- The Reader More dialog passes focus entry, containment, Escape, and restoration.
- Visible touch targets pass the release gate.
- Refresh sessions use an HttpOnly cookie; rotation, reuse rejection, CSRF, logout, and logout-all pass in isolated staging.
- API and worker hardening, worker-aware readiness, GPU-only TTS, dependency audits, and TTS log redaction pass. [Source: evidence/test-summary.json] [Source: evidence/staging-auth-lifecycle.json] [Source: evidence/tts-gpu-only.json]

## Reopened, partial, and new findings

- `OPS-RECOVERY-001`, P1: backup and restore receipt integration is not executable under the current host and container permission contract.
- `OPS-RUNBOOK-002`, P1: the canonical release runbook selects stale release and rollback overlays.
- `A11Y-SETTINGS-003`, P2: Reader settings focus entry, containment, and restoration fail in all five isolated browser viewports.
- `UX-MOB-007`, P2: fixed mobile navigation can cover the lowest visible content.
- `PERF-READER-002`, P2: rapid two-chapter navigation issues three translation reads; Reader sync writes remain noisy.
- `TTS-UI-004`, P2: frontend guidance recommends CPU TTS despite the GPU-only policy.
- `OPS-PROV-005`, P2: `/api/version` reports `image_digest=unknown`; Docker inspection still supplies immutable image IDs.
- `OBS-ALERT-006`, P2: no external alert delivery receipt was demonstrated.
- `UX-LOGIN-007`, P2: the install prompt overlaps the login area at a short desktop viewport.
- `SEC-FILE-008`, P3: an unused token-like file is mode `0644` inside an owner-private data root; reachability is unproven. [Source: evidence/browser-summary.json] [Source: evidence/live-runtime-second-snapshot.json]

## Domain verdicts

| Domain | Verdict | Reason |
|---|---|---|
| Mobile | GO_WITH_LIMITATIONS | Required widths work without horizontal overflow; bottom safe-area and settings focus debt remain. |
| Reader and PWA | GO_WITH_LIMITATIONS | First-session, warmed, corrupted-entry, shell-only, logout cleanup, and cache-revision checks pass; public fresh-profile mutation and the complete live mode matrix remain excluded. |
| Desktop | GO_WITH_LIMITATIONS | Core routes and Reader open correctly; no complete desktop mutation journey was run. |
| Data safety | GO | SQLite, foreign keys, active artifacts, paths, and before/after fingerprints pass. |
| Security | GO_WITH_LIMITATIONS | Session and browser controls pass; one token-like file needs ownership review. |
| Backup and recovery | NO_GO | Existing archive is valid, but future backup and receipt publication are not trustworthy. |
| Runtime and readiness | GO | Hardened containers, worker heartbeat, release match, and honest optional TTS degradation pass. |
| Observability | GO_WITH_LIMITATIONS | Metrics and alerts exist; external delivery and recovery receipts are missing. |
| Accessibility | GO_WITH_LIMITATIONS | More dialog and touch targets pass; settings dialog focus fails. |
| Release trust | NO_GO | Verification passes, but worktree is dirty and the canonical rollback runbook is stale. |
| Maintainability | GO_WITH_LIMITATIONS | Bounded extraction preserved behavior; major ownership hotspots remain. |

## Highest-ROI next actions

1. Repair and certify the recovery receipt filesystem and identity contract.
2. Update the canonical runbook to the current release and rollback overlays, then verify copy-safe commands.
3. Repair Reader settings focus and mobile bottom safe-area padding.
4. Remove CPU fallback guidance from the UI while preserving backend GPU enforcement.
5. Configure one external alert delivery path and preserve its redacted receipt.

## Required operator approvals

- Editing `production.env`, `backup.env`, Compose files, or protected configuration.
- Any `chmod`, `chown`, service restart, production backup invocation, restore, deploy, release, merge, or external alert post.
- Any live GPU synthesis or paid provider request.

## Remaining unknowns

- Public-production fresh-profile offline was not mutated; the isolated production image, deterministic E2E paths, and adversarial lifecycle matrix passed instead.
- Protected challenge bypass was preserved and locally regression-tested but not live-tested.
- No real paid translation or GPU TTS call was made.
- No production rollback or graceful-shutdown fault injection was performed.
- No full screen-reader or long-duration low-end Android soak was completed.

## Exact next Hermes Goal

Execute `workstreams/01-recovery-continuity-and-receipts.md` after explicit operator approval. Stop before production restart or backup creation. Require an isolated restore drill exit 0, fresh receipt ingestion, and an independently verified diff before considering a new certification run.

## Final certification record

1. Honest overall assessment: the application is healthy for attended private use but recovery and rollback controls are not certifiable.
2. Previous-audit comparison: first-session offline and most repair contracts improved; recovery continuity and canonical rollback documentation regressed.
3. Current overall score: 6.8/10, with a 7.46 arithmetic mean before the P1 certification cap.
4. Score change: down 1.2 from the previous 8.0; category changes are listed in `15-scorecard.md`.
5. Previous issues verified fixed: all eight mobile-first P1 findings, including the later first-session PWA formulation.
6. Previous issues reopened or partial: recovery freshness reopened; provenance, observability, request deduplication, and bounded extraction remain partial.
7. New regressions: recovery integration, stale canonical rollback instructions, and CPU TTS guidance.
8. New P0 findings: none.
9. New P1 findings: two open, `OPS-RECOVERY-001` and `OPS-RUNBOOK-002`.
10. Remaining P2/P3 debt: seven P2 and one P3 finding in `17-issue-register.md`.
11. Mobile verdict: GO_WITH_LIMITATIONS.
12. Reader/PWA verdict: GO_WITH_LIMITATIONS; both offline paths pass.
13. Desktop verdict: GO_WITH_LIMITATIONS.
14. Data-safety verdict: GO at the audit timestamp.
15. Security verdict: GO_WITH_LIMITATIONS; no bypass or major exposure reproduced.
16. Backup/recovery verdict: NO_GO.
17. Runtime/readiness verdict: GO.
18. Observability verdict: GO_WITH_LIMITATIONS.
19. Accessibility verdict: GO_WITH_LIMITATIONS.
20. Release-trust verdict: NO_GO.
21. Maintainability verdict: GO_WITH_LIMITATIONS.
22. Highest-ROI improvements: recovery receipts, current rollback instructions, Reader focus and safe area, TTS guidance, and alert delivery.
23. Required approvals: protected configuration, permissions, external delivery, production backup, restore, restart, merge, release, and deploy.
24. Remaining unknowns: authorized public fresh-profile offline, live challenge behavior, GPU synthesis, paid translation, full screen-reader pass, and graceful shutdown.
25. Final decision: NO_GO for certification, not an outage declaration.
26. Exact next goal: execute workstream 1 in isolation after approval, stop at HANDOFF, then rerun certification if all P1 evidence passes.
