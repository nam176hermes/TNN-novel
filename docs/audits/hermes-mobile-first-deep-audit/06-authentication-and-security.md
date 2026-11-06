# Authentication and Security Audit

## Passing contracts

A focused security run passed 115 tests covering authentication, authorization, public-deploy safety, CORS, URL policy, fetch limits, ebook boundaries, dashboard protection, and auth repository behavior. [Source: fresh focused pytest output]

## SEC-001: browser private-network guard

Two baseline tests failed because top-level and subresource requests to a private target were continued instead of aborted. [Source: `/tmp/novel-tnn-audit-baseline.log`]

Classification: P1, REPRODUCED.

Protected challenge handling was not live-tested or modified.

## SEC-002: browser-readable refresh tokens

The frontend stores access and refresh tokens in localStorage through `web/src/state/session.ts`. Login also sets a secure HttpOnly asset cookie, but that cookie does not protect the localStorage refresh token. [Source: `web/src/state/session.ts:1-53`; isolated login response headers]

Classification: P1, CODE_EVIDENCE.

Risk: any successful same-origin script injection can read a long-lived refresh token.

## SEC-003: missing response headers

Local and public response probes did not observe CSP, HSTS, frame protection, nosniff, Referrer Policy, or Permissions Policy headers. [Source: fresh curl header probes]

Classification: P2, REPRODUCED.

## SEC-004: session retention

Production aggregates showed 7,147 auth-session rows, including 4,176 expired and 2,964 active. No explicit deletion path for expired rows was found in the searched application code. [Source: read-only aggregate query and source search]

Classification: P2, CODE_EVIDENCE.

## Dependency audit

- Frontend production audit: zero vulnerabilities.
- Python audit: findings in `ecdsa`, `pytest`, and `setuptools`.
- Application JWT uses HS256, so the ECDSA P-256 signing path was not observed.
- `pytest` and `setuptools` findings are test/build paths.

[Source: `npm audit --omit=dev`; `/tmp/novel-tnn-pip-audit.json`; `app/mobile_api/config.py:34`]

Verdict: security readiness NO-GO until P1 findings are resolved and reverified.
