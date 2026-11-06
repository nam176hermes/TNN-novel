# Novel-TNN Mobile-First Deep System Audit

Audit date: 2026-07-22

## 1. Executive summary

Novel-TNN is healthy enough for continued private local use, but it is not ready for a release-readiness certification. No P0 was reproduced. Eight P1 findings remain open across Reader correctness, offline behavior, browser network isolation, release verification, token handling, container hardening, readiness semantics, and keyboard accessibility. [Source: `14-issue-register.md`]

## 2. Scope

The audit covered mobile Reader first, then mobile workflows, data and artifacts, security, import and processing workflows, production health, performance, desktop parity, accessibility, and maintainability. Production data and configuration remained read-only. [Source: `01-methodology-safety-and-evidence.md`]

## 3. Evidence model

Findings use `REPRODUCED`, `CODE_EVIDENCE`, `SUSPECTED`, or `NOT_TESTED`. Historic reports were context only. A passing test proves its tested contract, not production behavior outside that contract. [Source: `01-methodology-safety-and-evidence.md`]

## 4. Baseline verification

The backend baseline finished with 1,110 passed and 3 failed. Frontend tests, typecheck, build, and dependency consistency passed. The verification wrapper process returned zero despite earlier failures, so its aggregate exit status is unsafe. [Source: `/tmp/novel-tnn-audit-baseline.log`; `02-environment-and-runtime-baseline.md`]

## 5. Overall readiness score

Provisional score: 62/100. The score is constrained by open P1 findings and weak operational certification, not by a current outage. [Source: `13-feature-matrix.md`; `14-issue-register.md`]

## 6. Top findings

1. Private top-level and subresource browser requests were continued instead of aborted in two regression tests.
2. `scripts/verify.sh` can mask failed checks with a later successful command.
3. Reader raw and split modes are disabled even when the source API returns Chinese content.
4. Offline Reader reload loses the article and gives no offline explanation.
5. Access and refresh tokens are stored in localStorage.
6. The public API container lacks the worker's capability, privilege, CPU, memory, and PID controls.
7. Public readiness does not check worker heartbeat or GPU/TTS availability.
8. The mobile More dialog does not receive focus or close with Escape.
9. Glossary and Reader TOC create very large DOM trees.
10. Runtime image and source provenance cannot be tied to a deployed commit.

[Source: `14-issue-register.md`]

## 7. P0 and P1 decision

No P0 was reproduced. Open P1 IDs are `SEC-001`, `OPS-001`, `READ-001`, `READ-002`, `SEC-002`, `OPS-002`, `OPS-004`, and `A11Y-001`. No repair was made during this mission. [Source: `14-issue-register.md`]

## 8. Mobile blockers

Mobile navigation opens the audited screens without horizontal overflow at 360x740, 390x844, and 412x915. Certification is blocked by offline Reader failure, raw-state mismatch, dialog keyboard behavior, dense Sources controls, and undersized controls. [Source: `03-mobile-reader-audit.md`; `04-mobile-workflows-audit.md`]

## 9. Reader risks

Translation and QA rendering worked in staging. Raw, compact-raw, and split modes were disabled while the source response contained 3,701 characters and 2,783 CJK characters. Chapter changes generated duplicate translation and related requests. Offline reload rendered no article. [Source: `03-mobile-reader-audit.md`; browser evidence JSON]

## 10. Data safety

Production SQLite integrity was `ok`, foreign-key check returned zero rows, and referenced artifact checks found no missing or zero-byte active artifacts. A fresh encrypted restore drill validated 1,774 artifact paths, six books, 760 chapters, and an authenticated Reader smoke. Data safety is GO with limitations. [Source: `05-data-integrity-and-artifacts.md`; `07-core-workflow-evidence.md`]

## 11. Security readiness

Focused security tests passed 115/115, but browser private-network guards failed in the full baseline. Public responses lacked the audited security headers. Tokens are stored in localStorage, and the session table contains 7,147 rows with 2,964 active sessions. Security certification is NO-GO. [Source: `06-authentication-and-security.md`]

## 12. Workflow readiness

A focused import, translation, QA, export, and backup run passed 271 tests. TTS-focused tests passed 42 tests and production correctly reported `tts_unavailable` without CUDA. Paid providers and CPU synthesis were not invoked. Workflow readiness is GO with limitations because live provider actions were intentionally not tested. [Source: `07-core-workflow-evidence.md`]

## 13. Public and local health

Local and public root/readiness probes returned HTTP 200. Both production containers were running and healthy with zero restarts. This proves current reachability, not complete dependency readiness. [Source: `08-production-operations-and-observability.md`]

## 14. Hardening gaps

The API container runs as `novel` with a read-only root filesystem, but it has no observed capability drop, no-new-privileges flag, memory limit, CPU limit, or PID limit. The worker has these controls. [Source: Docker inspect evidence in `08-production-operations-and-observability.md`]

## 15. Performance and ownership

The Glossary screen created 16,813 DOM nodes and 3,510 interactive elements. Reader TOC created 5,342 nodes and 707 interactive controls. Rapid chapter navigation produced 23 API requests for four transitions, including seven translation requests. [Source: `09-performance-and-request-ownership.md`]

## 16. Desktop parity

Desktop routes opened at 1366x768 and 1440x1000 without horizontal overflow. Desktop was not treated as evidence that mobile was correct. Desktop parity is GO with limitations because full mutation flows and assistive-technology review were not run. [Source: `10-desktop-parity.md`]

## 17. Accessibility

Automated structural scans found no unlabeled interactive elements in the sampled screens. The mobile More dialog failed focus entry and Escape dismissal. Touch targets below 44 CSS pixels are common. WCAG conformance was not certified. [Source: `11-accessibility.md`]

## 18. Tests and confidence limits

Backend baseline: 1,110 passed, 3 failed. Frontend: 740 passed. Focused security: 115 passed. Focused workflows: 271 passed. Focused TTS: 42 passed. Browser coverage used an isolated copied database and read-only production artifacts. Live CAPTCHA, paid translation, GPU TTS synthesis, and destructive restore were not tested. [Source: `01-methodology-safety-and-evidence.md`]

## 19. Repair workstreams

1. Reader correctness and offline behavior.
2. Browser network isolation and token security.
3. Verification, readiness, provenance, and container hardening.
4. Mobile accessibility and touch targets.
5. Request deduplication and list virtualization.
6. Session retention and dependency hygiene.
7. Module decomposition only after behavior fixes are protected by tests.

[Source: `14-issue-register.md`]

## 20. Required approvals

Product repairs, production restart, deployment, migration, public ingress change, protected browser behavior change, and any paid-provider or GPU synthesis action require separate operator approval. [Source: `01-methodology-safety-and-evidence.md`]

## 21. Readiness verdicts

| Dimension | Verdict |
|---|---|
| Local health | GO with limitations |
| Public health | GO with limitations |
| Mobile readiness | NO-GO |
| Desktop readiness | GO with limitations |
| Data safety | GO with limitations |
| Security readiness | NO-GO |
| Backup and recovery | GO with limitations |
| TTS policy | GO with limitations |
| Observability | NO-GO |
| Accessibility | NO-GO |
| Release provenance | NO-GO |

[Source: `13-feature-matrix.md`]

## 22. Exact next Hermes Goal

Implement only approved workstreams in PR-sized changes. Start with `SEC-001` and `OPS-001`, then `READ-001` and `READ-002`. Preserve protected browser/challenge behavior, add focused regression tests before each repair, and rerun the complete verification gate after every approved batch.
