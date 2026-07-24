# Post-repair release certification — executive summary

Date: 2026-07-23 (America/Toronto)

Certified source commit: `13e2b05d2142c6b5ae94d6dcbc718930cb8b8565`

Production release: `ws6-production-20260723-r1`

## Decision

**GO_WITH_LIMITATIONS** for the existing private, single-operator production
deployment.

No reproduced P0 or P1 finding remains open. The mandatory verification gate,
mobile Reader contracts, session migration, runtime hardening, data integrity,
fresh encrypted-backup restore drill, release provenance, and rollback contract
all passed. This decision does not certify Novel-TNN as a public SaaS or as a
fully WCAG-conformant product.

## Verdict by dimension

| Dimension | Verdict | Evidence summary |
|---|---|---|
| Local health | GO | `/api/health`, `/api/ready`, and `/api/version` returned HTTP 200. |
| Public health | GO | Browser-like HTTPS probes returned HTTP 200 with the expected headers. |
| Mobile | GO | Three required viewports passed; Reader raw/split, offline, focus, and touch contracts passed. |
| Desktop | GO | Eleven surfaces at both required desktop viewports had no horizontal overflow. |
| Data | GO | SQLite integrity passed; zero FK violations, duplicate chapter keys, or active artifact errors. |
| Security | GO_WITH_LIMITATIONS | Previous security findings are closed; dependency advisories remain scheduled P2 work. |
| Backup/recovery | GO | Fresh encrypted backup restored and passed DB, artifact, API, and Reader checks in isolation. |
| TTS | GO_WITH_LIMITATIONS | GPU-unavailable behavior and no-CPU-fallback invariant passed; real GPU synthesis was not run. |
| Observability | GO_WITH_LIMITATIONS | Authenticated metrics and alerts exist; external backup/drill freshness is not yet ingested. |
| Accessibility | GO_WITH_LIMITATIONS | Focus and touch regressions passed; no claim of complete WCAG or screen-reader certification. |
| Provenance | GO | API/worker share a release ID and exact Git SHA; production image IDs are recorded. |
| Rollback | GO_WITH_LIMITATIONS | Pinned rollback overlay and commands are valid; a live production rollback was not executed. |

## Mandatory evidence

- `scripts/verify.sh --self-test-failure` returned exit 97 and named the failed gate.
- Normal `scripts/verify.sh` returned zero only after 1,181 backend tests,
  768 frontend tests, typecheck, environment checks, dependency consistency,
  and production build passed.
- Chromium Playwright: 11/11 scenarios passed.
- Focused security suite: 149 passed.
- Focused workflow/recovery suite: 176 passed.
- Fresh API and worker images built from the certified commit; isolated API
  smoke and the runtime contract passed.
- Production API and worker are healthy, hardened, at restart count zero, and
  report the same release identity.
- Fresh isolated restore drill: `integrity_check=ok`, zero foreign-key
  violations, 1,774 artifact paths, 6 books, and 760 chapters.

## Remaining accepted limitations

1. `DEP-001` (P2): `pip-audit` reported advisories in `ecdsa`, `pytest`, and
   `setuptools`. Current runtime auth uses HS256 rather than the affected ECDSA
   path; two findings affect test/build tooling. Upgrade and retest are
   scheduled rather than silently changing dependencies during certification.
2. `OBS-002` (P2): metrics correctly authenticate and produce low-cardinality
   state, but the container cannot currently observe the operator-owned
   external encrypted-backup directory or the pre-WS4 restore status file.
3. External alert delivery, long-duration low-end Android memory behavior,
   live third-party challenge behavior, paid-provider translation, and real
   GPU TTS synthesis were not exercised.

## Release recommendation

Continue operating the current private deployment. Do not add users or claim
public SaaS readiness. Schedule `DEP-001` and `OBS-002`, then rerun their
targeted gates. No deployment was performed as part of this certification.
