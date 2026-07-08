# Deployment Smoke Checklist

Use this checklist before relying on a Cloudflare or public-domain deployment.

## Preconditions

- `PUBLIC_DEPLOY=1` is set for public access.
- Strong `MOBILE_API_SECRET`, `MOBILE_API_ADMIN_USERNAME`, and `MOBILE_API_ADMIN_PASSWORD` are set.
- `MOBILE_API_CORS_ORIGINS` is an exact HTTPS origin for the public domain.
- The API and web UI are running from the intended release.
- A fresh backup exists under `backups/` or an off-machine location.
- The public web server or tunnel does not expose `data/` directly.

## Automated Public Smoke

Run the non-mutating public smoke before the manual checklist:

```bash
.venv/bin/python scripts/ops.py smoke-public \
  --base-url https://YOUR_DOMAIN \
  --username "$MOBILE_API_ADMIN_USERNAME" \
  --password "$MOBILE_API_ADMIN_PASSWORD" \
  --data-probe-path data/pipeline.db
```

The command validates `/api/ready`, disabled API docs, exact-origin CORS, protected asset routes, private/no-store cache headers, login, authenticated `/api/system/status`, and the optional data-path probe. It does not import books, start translation jobs, or mutate library data.

Failure guidance:

- `/docs`, `/openapi.json`, or `/redoc` returns `200`: restart with `PUBLIC_DEPLOY=1` and confirm the proxy is reaching the current app.
- `/api/ready` leaks paths or internal diagnostics: the app is not running the hardened public readiness behavior, or the proxy is serving an older process.
- CORS preflight does not return the exact public origin: set `MOBILE_API_CORS_ORIGINS=https://YOUR_DOMAIN` and remove wildcard/local HTTP origins in public mode.
- `/covers/...` or `/book-assets/...` returns `200` without auth: asset routes are exposed and must be fixed before public use.
- `/covers/...` or `/book-assets/...` lacks `Cache-Control: private, no-store`: remove Cloudflare/proxy cache rules for private app paths and confirm the current backend is running.
- login fails: verify the supplied credentials match the server environment.
- `data/pipeline.db` returns `200`: remove any static `data/` exposure from the proxy/tunnel config.

## Checklist

- [ ] HTTPS works on the public domain.
- [ ] `/docs` is disabled when `PUBLIC_DEPLOY=1`.
- [ ] `/openapi.json` is disabled when `PUBLIC_DEPLOY=1`.
- [ ] `/redoc` is disabled when `PUBLIC_DEPLOY=1`.
- [ ] `/api/ready` does not expose local paths, DB paths, provider key names, stack traces, or internal machine details.
- [ ] CORS allows only the exact public HTTPS origin.
- [ ] `/covers/...` without authentication returns `401` or `403`.
- [ ] `/book-assets/...` without authentication returns `401` or `403`.
- [ ] `/covers/...` and `/book-assets/...` responses include `Cache-Control: private, no-store`.
- [ ] Cloudflare caching is disabled for `/api/*`, `/covers/*`, and `/book-assets/*`.
- [ ] Uploading a file larger than the configured limit returns `413`.
- [ ] Login works with the intended admin credentials.
- [ ] Importing a small ebook works.
- [ ] A translation job starts.
- [ ] The Trạng thái page loads and shows API readiness.
- [ ] The backup command works: `scripts/backup-local.sh`.
- [ ] `data/` is not directly exposed by the public web server or tunnel.
- [ ] The API ready endpoint works: `curl -fsS https://YOUR_DOMAIN/api/ready`.
- [ ] Reader works on mobile viewport.
- [ ] Reader works on desktop viewport.

## Audit Check

After the smoke and one normal operator login, open the authenticated Trạng thái page or call `/api/system/status` and confirm recent operational events show sanitized login/job/import/provider activity without secrets or private book text.

## Local Commands

Run these from the project root when validating the local instance behind the tunnel:

```bash
scripts/status-local.sh
scripts/smoke-local.sh
scripts/smoke_reader_page.py
```

For public checks, use a private browser window or a request without cookies for the unauthenticated asset checks.
