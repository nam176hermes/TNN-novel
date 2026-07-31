# Security certification

## Verdict

**GO_WITH_LIMITATIONS** for private single-operator production.

All four audit security findings were revalidated as fixed. No P0/P1 security
finding was reproduced. Dependency advisories remain a P2 follow-up.

## Validation rubric

Each candidate was assessed against at most five criteria:

- [x] Identify attacker-controlled entrypoint, protected sink/control, and
  required preconditions.
- [x] Prefer a focused dynamic test or realistic HTTP/browser reproduction.
- [x] Confirm the production configuration reaches the intended control.
- [x] Check counterevidence, failure mode, and regression boundary.
- [x] Confirm that evidence and reports contain no token, cookie value,
  credential, private content, or secret path value.

## Candidate receipts

### SEC-001 — browser private-network isolation

- Root control: `app/utils/stealth_browser.py:281`.
- Claimed input: browser navigation/subresource/redirect target.
- Sink: browser network continuation into loopback, private, link-local, or
  DNS-resolved non-global address space.
- Preconditions: an import/browser session attempts the target.
- Method: focused unit/integration tests for top-level, subresource, redirect,
  IPv4/IPv6, DNS resolution, abort, typed failure, and job-state behavior.
- Evidence: security suite passed; blocked requests abort rather than continue;
  retries remain idempotent.
- Counterevidence checked: approved challenge/session contract tests remain
  green; no proxy, solver, fingerprint, or challenge behavior changed.
- Disposition: **suppressed (fixed)**; confidence high.

### SEC-002 — persistent browser-readable refresh token

- Root controls: `app/mobile_api/session_cookies.py:15` and
  `web/src/state/session.ts:6`.
- Claimed input: successful login/refresh response.
- Sink: persistent browser-readable storage.
- Preconditions: authenticated browser session.
- Method: auth tests plus isolated Chromium inspection.
- Evidence: localStorage contains Reader preferences/cache metadata only;
  sessionStorage contains the short-lived access token; refresh session is a
  Secure, HttpOnly, SameSite=Lax cookie. CSRF cookie is intentionally readable
  and contains no refresh credential.
- Rotation/reuse/logout/logout-all/concurrent-refresh tests passed.
- Disposition: **suppressed (fixed)**; confidence high.

### SEC-003 — missing browser response headers

- Root control: `app/mobile_api/browser_headers.py:44`.
- Claimed input: normal public or local HTTP response.
- Control: application-owned CSP, nosniff, frame denial, referrer and
  permissions policy; HSTS on public HTTPS.
- Method: direct local and public response-header probes.
- Evidence: local and public responses include CSP, `nosniff`, `DENY`, strict
  origin referrer policy, and restrictive permissions policy. Public HTTPS also
  includes one-year HSTS with subdomains.
- Disposition: **suppressed (fixed)**; confidence high.

### SEC-004 — unbounded auth-session retention

- Root controls: `app/database/auth_repository.py:246` and
  `app/database/auth_repository.py:372`.
- Claimed input: repeated login/refresh creating session rows.
- Sink: unbounded SQLite growth or deletion of valid sessions.
- Method: retention tests and read-only production retention report.
- Evidence: total 5,412; active 412; inactive retained 5,000; age-eligible 0;
  row-cap-eligible 0; would-remove 0. The cap applies to inactive rows while
  preserving valid active sessions. Cleanup is bounded and transactional.
- Disposition: **suppressed (fixed)**; confidence high.

### DEP-001 — dependency audit advisories

- Seed anchors: `requirements.txt:11`, `pyproject.toml:2`, and
  `pyproject.toml:33`.
- Source: fresh `pip-audit` against the certification virtual environment.
- Evidence: advisories in `ecdsa 0.19.2`, `pytest 8.3.3`, and
  `setuptools 79.0.1`; advisory references were PYSEC-2026-1325,
  PYSEC-2026-1845, and PYSEC-2026-3447. `npm audit --omit=dev
  --audit-level=high` reported zero.
- Reachability: runtime JWT configuration uses HS256, not the ECDSA path;
  pytest and setuptools are test/build tooling. No exploit was attempted.
- Proof gap: transitive-package removal/upgrade compatibility was not tested in
  this certification-only workstream.
- Disposition: **reportable P2**, scheduled; confidence medium.

## Validation closure table

| Ledger row | Instance | Root control | Entry/source | Sink/control | Disposition | Counterevidence/proof gap | Survives |
|---|---|---|---|---|---|---|---|
| SEC-001 | browser-network-policy | `app/utils/stealth_browser.py:281` | browser URL/request | canonical abort policy | suppressed | dynamic policy and challenge-contract tests pass | no |
| SEC-002 | refresh-storage | `app/mobile_api/session_cookies.py:15` | auth response | persistent Web Storage | suppressed | runtime storage/cookie inspection passes | no |
| SEC-003 | response-headers | `app/mobile_api/browser_headers.py:44` | HTTP response | browser policy headers | suppressed | local/public header probes pass | no |
| SEC-004 | session-retention | `app/database/auth_repository.py:246` | login/refresh rows | retention repository | suppressed | bounded report, no valid-session deletion | no |
| DEP-001 | Python dependencies | `requirements.txt:11` | installed package versions | vulnerable package paths | reportable | reachability limited; upgrades not tested | yes |

This table is also the validation receipt ledger for this certification; no
separate Codex-security candidate ledger existed for the Hermes issue IDs.
The visible validation artifact is this file; supporting commands are listed in
`09-release-and-rollback-record.md`.

## Additional gates

- Focused security tests: 149 passed.
- CSRF rejects mismatched/missing tokens without rotating a session.
- Protected downloads/assets require authorization.
- SSRF, redirect, ebook parser, archive traversal, filename, and containment
  tests passed.
- Unauthenticated operational metrics returned HTTP 401.
- No refresh token appeared in localStorage, sessionStorage, IndexedDB, Cache
  Storage, URL, logs, or report output.
- Public health responses exposed no stack trace, absolute artifact path, or
  secret.

## Protected challenge boundary

The existing challenge integration was not live-tested against a third party.
Local fixtures and contract tests passed. The integration was not removed,
expanded, renamed, relocated, or otherwise changed during certification.

## Limitations

- No live third-party CAPTCHA/challenge exercise was authorized.
- No formal penetration test or exhaustive dependency exploitability analysis
  was performed.
- `DEP-001` must be handled in a dedicated dependency-upgrade task with the
  complete verification gate.
