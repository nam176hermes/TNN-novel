# Authentication and security


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Browser storage and cookies

Isolated browser storage contained no localStorage keys. sessionStorage held only the short-lived operator access-token key. JavaScript could read the CSRF cookie but not the refresh session. The refresh session cookie was HttpOnly, SameSite Lax, and scoped to `/api/auth` in staging. Production HTTPS header and cookie behavior is covered by configuration tests. [Source: evidence/browser-summary.json] [Source: evidence/staging-auth-lifecycle.json]

## Session lifecycle

- Login returned an access token but no refresh token in JSON.
- Missing and mismatched CSRF returned HTTP 403.
- Refresh rotated access, refresh-session, and CSRF values.
- Reuse of an old refresh session returned HTTP 401 and invalidated the family.
- Logout cleared cookies and blocked refresh.
- Logout-all invalidated both tested sessions.

[Source: evidence/staging-auth-lifecycle.json]

## Browser and request security

Focused tests cover loopback, link-local, RFC1918 IPv4, private IPv6, private DNS resolution, top-level navigation, iframe, subresource, redirect, teardown, archive/parser boundaries, upload limits, filename safety, and protected failure states. All focused tests passed. Challenge bypass was not live-tested. [Source: evidence/test-summary.json]

## Headers and CORS

Public responses include CSP, HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, referrer policy, and permissions policy. The approved production origin passes CORS preflight; an unrelated hostile origin receives HTTP 400 without an allow-origin response. [Source: evidence/http-security-probes.json]

## Dependencies and logs

npm and Python audits reported zero current advisories. A bounded production log scan found no Authorization headers, cookie headers, JWT-like values, prompt markers, secret assignments, or chapter-content markers in 377,886 bytes across 22 files. [Source: evidence/dependency-audits.json] [Source: evidence/production-data-integrity.json]

## Residual concern

`/data/extension_token.hex` is owner UID/GID 10001 but mode `0644`. No current source reference was found and the data root itself is mode `0750`, so exposure is not established. Confirm purpose and reachability before any permission change or deletion. [Source: evidence/live-runtime-second-snapshot.json]

## Verdict

**GO_WITH_LIMITATIONS** for private single-operator use. No authentication bypass or major exposure was reproduced.
