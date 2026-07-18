# Novel-TNN security review — durable closeout

## Scope and evidence status

This closeout records the security conclusions that are durable in the Git
checkout. The original discovery/validation working bundle was held under the
system temporary directory and was pruned before its generated final report
could be sealed. The missing temporary receipts must not be represented as
available evidence.

The conclusions below remain supported by the reviewed source revisions,
isolated fix commits, regression tests, and the fresh repository-wide test
gate. The detailed candidate notes used during the run are summarized in the
issue register and technical-debt register.

## Resolved P1 findings

| Finding | Source remediation | Evidence |
| --- | --- | --- |
| Unsafe external API defaults | `28ad489` | Non-loopback binds now require `PUBLIC_DEPLOY=1`; public mode rejects development secret, default username/password, insecure CORS and auth-bypass configurations. |
| Externally bindable unauthenticated legacy dashboard | `7723ae7` | The standalone dashboard rejects any non-loopback host before starting Uvicorn. |
| Request-controlled translation destination with configured credential fallback | `5188adb` | A request cannot supply `host` without selecting a registered provider; registered provider configuration owns the destination and credential. |

The parser-candidate RFC 6598 address gap was also corrected in `c0854d7` by
rejecting all non-global addresses. `00f69c3` makes public/local request
classification depend on the client peer rather than a forged `Host` header.

## Remaining security work

- **P2 — DNS rebinding:** direct import and source-health checks validate DNS
  before a later hostname-based `requests` transport resolves again. A shared,
  peer-bound HTTP transport is required; URL preflight alone is not a complete
  SSRF control.
- **P2 — browser fallback:** Chromium fallback navigation remains hostname
  based after validation. A browser-specific egress and redirect model needs
  design and isolated validation before implementation.
- **P3 — bounded resource use:** EPUB CSS traversal/reparse, StarDict decode,
  Reader regex search, and dictionary record parsing need explicit work,
  aggregate-byte, cache, timeout, or record-count budgets.

No P0 was identified in the completed code review. The temporary-artifact
loss reduces the retained granularity of the discovery evidence; it does not
change the source/test evidence for the remediations above. A future formal
security scan should write its working bundle to a durable operator-selected
location before finalization.

## Current-checkout verification

- `NOVEL_PIPELINE_IGNORE_DOTENV=1 NOVEL_PIPELINE_PRODUCTION_ENV_FILE=<external-production-env> scripts/verify.sh` — pass: 1,112 backend tests, 733 frontend tests, production build.
- `npm --prefix web run typecheck` — pass.
- `npm --prefix web run test:e2e` — pass: 8/8.
- `GET /api/health` and `GET /api/ready` — `status: ok` locally and through the public hostname.

## Deployment boundary

These commits are verified in the checkout but have not been built into or
deployed to the live API/import-worker containers. The endpoint probes confirm
the currently deployed service, not release of the remediations. Building an
image, recreating a container, or changing ingress requires a separate
production approval.
