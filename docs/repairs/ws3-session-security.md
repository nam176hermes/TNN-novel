# Workstream 3 — Session Security, Browser Headers, and Retention

## Outcome

Workstream 3 is implemented and verified on branch `repair/ws3-session-security`.
No production deployment, restart, environment edit, session cleanup, database
migration, proxy change, or Cloudflare change was performed.

| Finding | Result | Evidence |
| --- | --- | --- |
| SEC-002 | Fixed in the staged branch | Refresh tokens are response-cookie only; browser code stores only the short-lived access token in `sessionStorage`. |
| SEC-003 | Fixed in the staged branch | Application-owned security headers cover normal, guarded, local, and public-HTTPS responses. |
| SEC-004 | Fixed and made observable | Existing bounded retention remains transactional; a read-only classification/dry-run estimate now reports active, expired, revoked, and eligible rows. |

Baseline:

- base branch: `upgrade-b/00-baseline-and-agent-guidance`
- base commit: `c7a6e7dcf700f9e01890193346ec1de41f097506`
- implementation branch: `repair/ws3-session-security`
- Python: 3.11.15
- Node: 22.23.0
- npm: 10.9.8
- Docker: 29.1.3
- Docker Compose: 2.40.3
- all mutable tests used pytest temporary databases/data directories with
  `NOVEL_PIPELINE_IGNORE_DOTENV=1`

## Reproduction and root causes

### SEC-002

Before the repair, login and refresh responses returned both JWTs. The React
client wrote `novel-operator-token` and `novel-operator-refresh-token` to
`localStorage`. Any script executing in the origin could therefore read the
14-day refresh credential. Refresh requests also sent the credential in JSON.

Root cause: the original mobile API contract treated a browser like a native
token client and had no browser-specific refresh-cookie boundary.

### SEC-003

Local and public response probes lacked CSP, HSTS, frame protection,
`nosniff`, Referrer Policy, and Permissions Policy.

Root cause: response-header ownership was not assigned to the application or
the public proxy. Some private responses set cache headers, but there was no
global browser-security middleware.

### SEC-004

The audit observed a large `auth_sessions` table and could not see session
lifecycle classifications. Subsequent repository inspection found that
transactional, bounded retention had already been implemented by an earlier
phase. It did not need a second cleanup system, but its status exposed only a
single total row count.

Root cause of the remaining gap: retention was operationally present but did
not report what “active” meant or offer a read-only estimate of session rows
eligible for cleanup.

## Current and target contracts

### Previous browser contract

```text
login
  -> JSON(access JWT, refresh JWT)
  -> localStorage(access JWT, refresh JWT)

refresh
  -> JSON body(refresh JWT)
  -> server rotates token hash
  -> JSON(new access JWT, new refresh JWT)
```

### Staged browser contract

```text
login
  -> JSON(short-lived access JWT)
  -> Set-Cookie(refresh JWT; HttpOnly; SameSite=Lax; host-only)
  -> Set-Cookie(CSRF nonce; SameSite=Lax; host-only)
  -> sessionStorage(access JWT)

reload/new tab
  -> POST /api/auth/refresh with credentials and X-CSRF-Token
  -> server reads HttpOnly refresh cookie
  -> atomic server-side rotation/reuse detection
  -> new HttpOnly refresh cookie + new CSRF nonce
  -> JSON(short-lived access JWT)

logout
  -> bearer-authenticated server-side revoke
  -> clear refresh, CSRF, and asset cookies
  -> clear access token and private Reader state locally
```

The database stores only a SHA-256 refresh-token hash. No raw refresh token is
returned in JSON or written to localStorage, sessionStorage, IndexedDB,
service-worker cache, URL, audit event, or error payload.

## Cookie and CSRF matrix

| Item | Local HTTP | Public HTTPS |
| --- | --- | --- |
| Refresh cookie | host-only, `HttpOnly`, `SameSite=Lax`, path `/api/auth`, no `Secure` | host-only, `HttpOnly`, `Secure`, `SameSite=Lax`, path `/api/auth` |
| CSRF cookie | readable nonce, `SameSite=Lax`, path `/`, no `Secure` | readable nonce, `Secure`, `SameSite=Lax`, path `/` |
| Asset cookie | existing HttpOnly access-cookie contract preserved | existing `Secure` HttpOnly access-cookie contract preserved |
| Access token | current tab `sessionStorage`; legacy localStorage keys are removed | same |
| Refresh request | cookie plus matching `X-CSRF-Token` | cookie plus matching `X-CSRF-Token` |
| Missing refresh cookie | typed 401 `refresh_required` | same |
| Missing/mismatched CSRF | typed 403 `csrf_rejected`; session is not rotated/revoked | same |

Logout and logout-all remain bearer-authenticated mutations, so a cross-site
page cannot invoke them with ambient refresh-cookie authority. When they
succeed, all session cookies are cleared. Login/refresh CORS requests continue
to use explicit credentials. In-tab refreshes are deduplicated, and the Web
Locks API serializes refresh rotation across tabs where supported.

## Security-header ownership

The application is the canonical owner. This makes local, container, and
public behavior deterministic without requiring a Cloudflare change.

| Header | Policy |
| --- | --- |
| Content-Security-Policy | self by default; no objects; no framing; bounded image/media/worker/data/blob allowances; configured HTTP(S) CORS origins in `connect-src` |
| Strict-Transport-Security | only emitted for a public HTTPS request (direct HTTPS or trusted forwarded scheme); one year plus subdomains |
| X-Content-Type-Options | `nosniff` |
| X-Frame-Options | `DENY` |
| Referrer-Policy | `strict-origin-when-cross-origin` |
| Permissions-Policy | camera, geolocation, and microphone disabled |

The CSP permits existing static assets, PWA workers, blob audio/media, data
images/fonts, and authenticated same-origin APIs. The production frontend build
and focused PWA/Reader browser test pass. Public CSP/HSTS behavior must still be
validated after an approved staging deployment.

## Session retention behavior

Definitions used by the report:

- `active`: not revoked and `expires_at` is later than the comparison time;
- `expired`: not revoked and expiration has passed;
- `revoked`: `revoked_at` is populated, regardless of the original expiry;
- `age_eligible`: inactive and older than the configured retention age;
- `row_cap_eligible`: inactive overflow remaining after age-eligible rows;
- `would_remove`: eventual age plus row-cap candidates; the report is read-only.

Deletion remains:

- limited to expired or revoked sessions;
- age-first and deterministically ordered;
- bounded by `OPERATIONAL_RETENTION_BATCH_SIZE`;
- wrapped in `BEGIN IMMEDIATE` with rollback on failure;
- scheduled by the existing retention lifespan loop;
- audited with aggregate deleted counts only.

Tests prove that valid active sessions survive both age and row-cap retention.
No production retention run was triggered during this workstream.

## Compatibility, migration, and rollback

This API/web contract must be deployed atomically.

1. Build API and web from the same Workstream 3 commit.
2. Deploy to staging without changing cookie names/domains.
3. Verify login, refresh, reload, two concurrent tabs, logout, logout-all,
   protected downloads, Reader assets, offline shell, CSP, and HSTS.
4. Existing browsers will have no HttpOnly refresh cookie. The new client
   removes legacy persistent token keys and requires one fresh login.
5. Existing database session rows remain untouched. Normal retention removes
   only expired/revoked rows according to policy.
6. After the operator approves the staging evidence, deploy API and web
   together and restart through the normal production procedure.

Rollback must also restore API and web together. No schema migration is part
of WS3, so rollback does not require database restoration. Clear the new
host-only cookies if rolling back to the old JSON-token contract. Do not deploy
an old frontend against the new API or the new frontend against the old API.

## Files changed

- `app/mobile_api/session_cookies.py`
- `app/mobile_api/routers/auth.py`
- `app/mobile_api/config.py`
- `app/mobile_api/schemas/__init__.py`
- `app/mobile_api/browser_headers.py`
- `app/mobile_api/main.py`
- `app/database/auth_repository.py`
- `app/mobile_api/services/retention_service.py`
- `web/src/state/session.ts`
- `web/src/state/useSession.ts`
- `web/src/api/client.ts`
- related backend, frontend, and Playwright contract tests

## Commits

- `348c781` — `refactor(auth): define cookie refresh session contract`
- `3cd1bed` — `fix(auth): move refresh token to httponly cookie`
- `88361f1` — `fix(security): enforce csrf contract`
- `2515dd3` — `fix(security): add browser response headers`
- `1e11ba6` — `fix(auth): prune expired sessions safely`
- `480449e` — `test(auth): cover cookie logout and refresh coordination`
- `5fd9a0a` — `test(auth): keep refresh rotation fixture lint-clean`

## Verification evidence

Targeted evidence:

- auth/security/audit/endpoints: 37 passed before CSRF enforcement;
- refreshed auth/security suite: 30 passed;
- auth/retention/system status: 74 passed;
- retention-only matrix: 35 passed;
- focused frontend auth/App suite: 62 passed;
- Playwright login/protected-shell flow: 1 passed;
- Playwright mobile offline Reader flow: 1 passed.

Mandatory gates:

```text
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m compileall -q app scripts tests
scripts/lint.sh
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s
  -> 1165 passed, 2 warnings
npm --prefix web test
  -> 85 files, 758 tests passed
npm --prefix web run typecheck
  -> passed
npm --prefix web run build
  -> passed
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
NOVEL_PIPELINE_PRODUCTION_ENV_FILE=/home/thenam176/.config/novel-tnn/production.env \
scripts/verify.sh
  -> all mandatory gates passed; 1165 backend and 758 frontend tests
git diff --check
  -> passed
```

The first plain worktree `scripts/verify.sh` run stopped at the environment
gate because the isolated worktree intentionally has no `.env` or runtime
`data/`. The production-metadata mode then passed without sourcing or printing
the external env file. This confirms both fail-closed verification and a green
approved verification path.

No Dockerfile/Compose/runtime configuration changed, so no image was built or
production container restarted. No paid provider or GPU synthesis ran.

## Remaining limitations and approval gate

- Production and public probes still describe the old deployed build until an
  operator-approved deployment occurs.
- A staging/public browser pass is still required to confirm CSP against the
  actual reverse proxy and any production-only asset URL.
- Browser refresh serialization uses Web Locks when available and an in-tab
  promise everywhere; very old browsers without Web Locks do not receive the
  cross-tab serialization guarantee.
- Existing active session rows are not destructively revoked by this workstream.
  The one-time re-login migration is intentional.
- Cookie name/domain changes, proxy header changes, production restart, and
  production session migration remain explicit approval boundaries.

## Recommendation

**GO for operator review and staging of Workstream 3. NO-GO for production
deployment without explicit approval.**

After approved staging proves the cookie/CSRF/header matrix, Workstream 4 may
start from the reviewed merged WS3 commit. Workstream 4 must not be mixed into
this branch before that review.
