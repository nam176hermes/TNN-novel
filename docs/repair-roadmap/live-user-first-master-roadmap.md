# Novel-TNN Live User-First Repair Roadmap

Audit source: `docs/audits/hermes-live-user-first-audit/`

## Decision

Do not start broad refactoring. Fix the P1 Reader offline lifecycle first, then close release-gate and operational evidence gaps.

## Sequence

| Order | Workstream | Priority | Depends on | Exit criterion |
|---:|---|---|---|---|
| 1 | First-session offline readiness | P1 | none | Fresh context offline works without preparatory reload. |
| 2 | Mandatory browser E2E gate | P2 | workstream 1 test | CI and supported full verify fail closed. |
| 3 | Recovery freshness observability | P2 | receipt schema approval | Runtime shows fresh, stale, missing, and invalid recovery state. |
| 4 | Python advisory remediation | P2 | dependency compatibility | Fixed advisories removed; ECDSA reachability documented. |
| 5 | TTS log privacy | P2 | none | Adversarial log tests prove no content leakage. |
| 6 | One bounded maintainability extraction | P2 | workstreams 1 through 5 | One hotspot reduced with compatibility preserved. |

## Approval gates

Operator approval is required before editing protected CI, package, TypeScript, build, Docker, or deployment configuration; before merge, release, deployment, service restart, paid-provider call, or production mutation.

## Expected score movement

- Offline fix: Reader 7.4 to at least 8.5; mobile 7.5 to at least 8.3.
- E2E gate: release trust 8.1 to at least 9.0.
- Recovery receipts and alerts: observability 6.8 to at least 8.0.
- Dependency and TTS privacy closure: security 8.1 to at least 8.8.
- Bounded extraction: maintainability 6.3 to at least 6.8 without changing product behavior.

## Global verification

Every workstream must report files changed, caller impact, tests run, exit statuses, rollback, unresolved risk, and fresh Git status. No completion claim is valid without current command output.
