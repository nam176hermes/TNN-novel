# Authentication and Security

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Live controls

- Protected books endpoint returns `401` without authentication and `private, no-store`.
- Hostile CORS preflight returns `400` with no allowed origin.
- Refresh uses HttpOnly, Secure-on-public-deployment, SameSite Lax cookies.
- CSRF uses double-submit validation.
- CSP blocks inline and third-party script execution outside the allowlist.
- HSTS, frame denial, MIME sniffing protection, and restricted device permissions are present.

[Source] fresh external header probes; `app/mobile_api/main.py`; `app/mobile_api/session_cookies.py`; `web/src/state/session.ts`

## Source controls

URL policy rejects unsafe schemes, credentials, private-network destinations, and unsafe redirect targets. Archive and artifact paths are validated against approved roots. [Source] `app/security/url_policy.py`; import and artifact-path tests

## Dependency audit

Frontend production audit: 0 vulnerabilities. Python audit: four advisory rows representing three unique package and advisory pairs: `ecdsa/PYSEC-2026-1325`, `pytest/PYSEC-2026-1845`, and `setuptools/PYSEC-2026-3447`. The ECDSA advisory has no published fix in the audit output. [Source] `/tmp/novel-tnn-live-audit/controller/npm-audit.json`; `/tmp/novel-tnn-live-audit/controller/pip-audit.json`

## Residual risks

- Confirm that production JWT paths never invoke vulnerable ECDSA signing operations.
- Upgrade pytest and setuptools in a compatibility-tested dependency PR.
- Redact or classify F5 upstream debug output before logging.

## Verdict

Security: **GO_WITH_LIMITATIONS**. No evidence supports a current authentication bypass, SSRF bypass, secret leak, or unsafe runtime privilege.
