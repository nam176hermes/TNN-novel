# Novel Pipeline Deployment Hardening

This app is built for personal use. Treat every imported book, cover, image, audio file, glossary, and provider setting as private data.

Book export and system backup are different workflows:

- `Book export`: EPUB/TXT/DOCX/M4B/glossary/annotation files for reading or review.
- `System backup`: recovery archive for database and private app data.

## Required Public Deployment Settings

Set these in the server environment before exposing the app outside localhost:

```bash
PUBLIC_DEPLOY=1
MOBILE_API_SECRET=<long-random-secret>
MOBILE_API_ADMIN_USERNAME=<private-admin-name>
MOBILE_API_ADMIN_PASSWORD=<strong-password>
MOBILE_API_CORS_ORIGINS=https://YOUR_DOMAIN
MOBILE_API_UPLOAD_MAX_BYTES=104857600
MOBILE_API_SERVE_WEB=1
WEB_DIST_DIR="$REPO_ROOT/web/dist"
DATA_DIR="$DATA_DIR"
```

Generate strong local values instead of reusing examples:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Provider keys are read from environment variables such as:

```bash
GEMINI_API_KEY=<secret>
DEEPSEEK_API_KEY=<secret>
OPENROUTER_API_KEY=<secret>
```

Do not commit `.env`. Keep it mode `0600` on the server.

## PUBLIC_DEPLOY Safety Gate

When `PUBLIC_DEPLOY=1`, the API refuses to start if public-facing configuration is unsafe. The gate rejects:

- default or short `MOBILE_API_SECRET`
- missing or default `MOBILE_API_ADMIN_USERNAME`
- missing, default, or short `MOBILE_API_ADMIN_PASSWORD`
- wildcard, `http://`, `null`, or non-HTTPS `MOBILE_API_CORS_ORIGINS`

This is intentional. A public deploy should fail loudly instead of serving the app with weak credentials. Local personal development still works without these values when `PUBLIC_DEPLOY` is unset.

Use exact HTTPS origins for public CORS:

```bash
MOBILE_API_CORS_ORIGINS=https://novel.example.com
```

Do not use:

```bash
MOBILE_API_CORS_ORIGINS=*
MOBILE_API_CORS_ORIGINS=http://localhost
MOBILE_API_CORS_ORIGINS=https://novel.example.com,http://localhost
```

## HTTPS Requirement

Use HTTPS for any remote access. The app sets secure cookies for private book assets when `PUBLIC_DEPLOY=1`; those cookies require HTTPS in real browsers.

Good options for personal use:

- Cloudflare Tunnel terminating HTTPS at `https://novel-tnn.tradingcompanydirect.com`
- nginx/Caddy reverse proxy with a valid TLS certificate

Do not expose the FastAPI port directly to the public internet unless it is behind a trusted tunnel or reverse proxy.

## Do Not Expose `data/` Directly

Never configure nginx, Apache, Cloudflare Pages, or any static file server to serve:

```text
$DATA_DIR/
$DATA_DIR/covers/
$DATA_DIR/book_assets/
```

Covers and rich ebook assets must go through FastAPI routes:

```text
/covers/...
/book-assets/...
```

Those routes are authenticated. Direct static hosting would bypass authentication and expose personal book media.

## Upload and Body Size Limits

The app rejects oversized uploads with `MOBILE_API_UPLOAD_MAX_BYTES`, default `100 MB`.

Still add an edge/proxy limit so huge requests are rejected before they reach Python.

Recommended rule:

```text
edge/proxy max body size <= MOBILE_API_UPLOAD_MAX_BYTES
```

### Cloudflare

Cloudflare has account/plan-specific request body limits. Keep `MOBILE_API_UPLOAD_MAX_BYTES` at or below the Cloudflare limit for the zone. If using Cloudflare Rules or WAF body-size controls, set the same or smaller value there.

If an ebook import fails before reaching the app, check Cloudflare logs first. If it reaches the app and is too large, the UI should show a `413` upload-size message.

### nginx Example

```nginx
server {
    listen 443 ssl http2;
    server_name novel-tnn.tradingcompanydirect.com;

    client_max_body_size 100m;

    ssl_certificate /etc/letsencrypt/live/novel-tnn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/novel-tnn/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
```

Do not add a `location /data/` block.

### Cloudflare Tunnel Example

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: $HOME/.cloudflared/<UUID>.json

ingress:
  - hostname: novel-tnn.tradingcompanydirect.com
    service: http://127.0.0.1:7860
  - service: http_status:404
```

## Runtime Status Page

The authenticated UI has a `Trạng thái` page. Use it to confirm:

- `PUBLIC_DEPLOY` mode
- API readiness
- active provider
- upload max size
- asset protection
- running jobs
- last failed job
- database path in local/private mode
- backup recommendation
- retention table counts and the last count-only retention summary

It intentionally does not show API keys or secrets.

## Operational Metadata Retention

The FastAPI lifespan owns one metadata-retention task. It runs once after runtime initialization and then every six hours by default; API requests never trigger deletion. Each repository call uses a bounded transaction, and the task uses an initial row-count budget, yields, and checks shutdown between batches so concurrent producers cannot extend one run forever. Shutdown drains the current bounded SQLite worker before task ownership is cleared.

Approved defaults:

```bash
AUTH_SESSION_RETENTION_DAYS=30
AUTH_SESSION_RETENTION_MAX_ROWS=5000
AUTH_LOGIN_FAILURE_RETENTION_DAYS=30
AUTH_LOGIN_FAILURE_RETENTION_MAX_ROWS=5000
OPERATIONAL_EVENT_RETENTION_DAYS=90
OPERATIONAL_EVENT_RETENTION_MAX_ROWS=50000
OPERATIONAL_RETENTION_BATCH_SIZE=500
OPERATIONAL_RETENTION_INTERVAL_SECONDS=21600
```

All values must be positive integers. Invalid or non-positive configuration fails validation instead of silently disabling or clamping retention. Active, unexpired sessions are never eligible; revoked or expired sessions, login failures, and operational events are bounded by both age and row count.

SQLite lock contention safely skips the current run and retries at the next interval. If earlier batches already committed, their exact counts remain pending in memory and the next run finalizes the count-only audit exactly once. Event pruning reserves one row for this audit so the insert cannot leave the table above its configured cap, including a cap of one. Zero-delete runs create no event. Authenticated system status exposes only table labels, row counts, last-run time, deleted counts, and the result—never SQL, database paths, row values, exception text, or secrets.

## Public Readiness Output

`/api/ready` is intentionally public so a tunnel, reverse proxy, or uptime checker can verify that the app is alive. In local/private mode it includes useful diagnostic details such as local data and database paths.

When `PUBLIC_DEPLOY=1`, readiness output is sanitized. It reports only high-level checks:

- API status
- database reachable
- storage reachable
- job subsystem reachable
- disk-space status
- public deploy mode enabled

Public readiness must not expose local filesystem paths, database paths, backup paths, provider key names, stack traces, or internal machine details. Use the authenticated `/api/system/status` page for richer operator diagnostics.

## Private Content Cache Headers

Private book content and authenticated data responses are marked as non-cacheable:

```text
Cache-Control: private, no-store
Pragma: no-cache
X-Content-Type-Options: nosniff
```

This applies to authenticated API responses and private asset routes such as `/covers/...` and `/book-assets/...`. It also covers source text, translations, audio, exports, dictionaries, glossary/TM downloads, and other private content served through protected API routes.

Cloudflare, nginx, Caddy, or any other proxy must respect these headers. Do not add Cloudflare Cache Rules that cache `/api/*`, `/covers/*`, or `/book-assets/*`.

Protected export and backup routes must also remain non-cacheable. Do not cache:

- `/api/books/*/exports/*`
- `/api/books/*/chapters/*/audio*`
- `/api/system/backups*`
- `/api/tts/jobs/*/download`

For deployed audio/export validation, use the bounded smoke command rather than blind browser checks:

```bash
.venv/bin/python scripts/smoke_tts_audio.py \
  --base-url https://YOUR_DOMAIN \
  --username YOUR_ADMIN \
  --password-file /secure/path/novel-tnn-smoke-password \
  --book-id 12 \
  --chapter-id 340 \
  --check-m4b-route
```

This validates authenticated chapter audio, protected download behavior, optional M4B export download, and unauthenticated denial without exposing raw backend paths.
The password file must be a regular file with `0600` permissions; do not pass passwords on the command line.

## Audit and Operational Events

The app records sanitized operational events for high-risk single-operator actions:

- login success/failure/logout
- session create/refresh/reuse rejection/revoke/logout-all
- login lockout
- provider key updates and provider test failures
- import start/complete/failure
- export creation/download
- book/chapter/translation/dictionary/glossary/TM deletes
- job start/retry/cancel/failure
- reader AI, QA, and TTS-related job activity/failures where applicable
- backup queue and dedicated terminal outcomes
- direct operator/CLI backup success

Events intentionally do not store provider keys, submitted passwords, raw prompts, raw book text, translations, stack traces, or full local filesystem paths in public mode. Recent sanitized events are visible through authenticated `/api/system/status`; server logs remain the place for detailed debugging.

Job-backed backup submission records `backup_job_queued`. After the coordinator
persists a completed, failed, or cancelled job state, it attempts exactly once
to record one dedicated `backup_job_terminal` event. The event has source
`backup_job_coordinator`, the constant message `Backup job reached a terminal
state`, the job id, and severity `info`, `error`, or `warning` respectively.
Safe details are `result`, `encrypted`, `secrets_included`, a non-negative
bounded integer `duration_ms`, and, only for completion, an optional
basename-only `backup_filename`. Completed booleans come from the published
backup result; failed and cancelled outcomes use request intent because they
have no completed artifact metadata. Raw exceptions, passphrases, directories,
and private content are excluded. A terminal-event writer failure is logged
without raw exception text and is not retried or allowed to undo the durable
terminal job state.

This dedicated event is separate from generic tracker `job_failure`. The
job-backed archive path also suppresses the legacy `backup_success` event;
`backup_success` remains the default only for direct operator/CLI creation.

## Backup Handling

System backup routes are authenticated only:

- `GET /api/system/backups`
- `POST /api/system/backups`
- `GET /api/system/backups/{filename}/download`

Backup creation is job-backed. The POST returns `202 Accepted` with a safe job
id and does not build an archive inside the request. The Status UI polls the
existing authenticated job endpoint, offers cooperative cancel while the job
is active, and reloads the sidecar-only list after completion.

The encryption passphrase is process-local, take-once, and never persisted in
job parameters or logs. Restarting the API deliberately loses it. An
interrupted encrypted/secrets backup must be queued again with a newly entered
passphrase; never attempt to recover it from SQLite or server logs. Plain retry
also creates a new backup job and cannot overwrite an existing archive.

Normal backup listing is metadata-only. It may read safe filename/stat data and a bounded adjacent sidecar, but must not open, decompress, decrypt, checksum, or walk an archive. Missing or invalid sidecars are entry-specific warnings and cannot block the core Status page or other backup entries. Only `READY` entries receive a protected download action.

Rules:

- backup filenames are sanitized
- path traversal is blocked
- `.env` and provider secrets are excluded by default
- secrets backup requires encryption passphrase
- secrets-included API backups keep plaintext below private mode-`0700`
  staging and publish only the encrypted READY artifact pair
- cleanup failure for process-owned hidden staging does not overturn READY
  success or mask a primary encryption/publication failure
- protected download requires a supported final filename, regular non-symlink
  artifact, and valid matching sidecar
- restore stays a documented CLI workflow, not a one-click public UI action
- final archive names appear only after staged validation/publication; partial
  and staging names remain unlistable and undownloadable

Run restore drills regularly and keep backups outside any public static root.

Legacy sidecar repair is never triggered by the browser. Rehearse and invoke the dry-run-first operator command documented in [`docs/backup-metadata-sidecars.md`](backup-metadata-sidecars.md). Do not supply passphrases on the command line, do not overwrite valid sidecars without explicit review, and verify archive hashes before and after repair.

P2C rollback uses the commit boundaries in
[`docs/backup-restore.md`](backup-restore.md#p2c-rollback-boundaries). Stop the
app, take a verified rollback backup, revert only the newest affected seam, and
rerun its focused tests before restart. P2C did not change the backup/restore
format or database schema, so rollback must not delete archives or run downgrade
SQL.

## Sessions, Refresh Tokens, and Password Changes

Login creates a SQLite-backed server-side session. Access tokens include a session id and protected APIs reject tokens whose session is unknown, expired, or revoked. Refresh tokens are rotated on use and only a SHA-256 hash of the current refresh token is stored in SQLite.

The web UI stores the access token and refresh token in browser storage for a persistent single-operator session. On app startup or access-token expiry, the UI calls the refresh endpoint, rotates the refresh token, and continues without showing the login page when the server-side session is still valid.

This does not remove backend authentication. If the session is revoked, expired, unknown, or the refresh token is reused/rejected, the UI clears local tokens and asks the operator to log in again. `PUBLIC_DEPLOY=1` still requires strong non-default credentials.

## Temporary No-Login Review Mode

If the goal is only to let an external reviewer or GPT-like browser inspect the UI, prefer the frontend-only review route. It does not disable backend authentication and does not call private APIs:

```bash
NOVEL_PUBLIC_REVIEW_MODE=1 scripts/start-cloudflare.sh
```

Then open:

```text
https://YOUR_DOMAIN/review
```

This route renders sanitized sample screens only. It is intended for UI review, screenshots, and layout feedback. It cannot import books, view private book content, update providers, start jobs, download exports, or access private assets.

## Post-deploy smoke checklist

After each deploy, verify:

- login/session works
- protected exports require auth
- protected audio requires auth
- system backup create/download requires auth
- `/api/ready` stays sanitized in `PUBLIC_DEPLOY=1`
- `/docs`, `/openapi.json`, `/redoc` stay disabled
- covers and book assets stay protected
- `scripts/backup-local.sh` still produces a backup manifest
- restore drill still succeeds on the newest backup

For local review only, the app can bypass the login page:

```bash
MOBILE_API_DISABLE_AUTH=1 VITE_DISABLE_AUTH=1 PUBLIC_DEPLOY=0 scripts/start-local.sh
```

`scripts/start-local.sh` enables this local bypass by default through `NOVEL_LOCAL_DISABLE_AUTH=1`, so the local Vite app can be reviewed without signing in. Set `NOVEL_LOCAL_DISABLE_AUTH=0` to restore normal local login behavior.

For a public domain, no-login mode is intentionally blocked by the `PUBLIC_DEPLOY` safety gate unless the operator explicitly sets both:

```bash
MOBILE_API_DISABLE_AUTH=1
MOBILE_API_ALLOW_PUBLIC_AUTH_BYPASS=1
VITE_DISABLE_AUTH=1
```

That exposes imported books, private assets, provider controls, import/export, jobs, and TTS actions to anyone who can reach the app. Use it only as a short-lived review window, then remove those variables and restart.

Logout revokes the current session server-side. To revoke every active operator session, call:

```bash
curl -X POST https://YOUR_DOMAIN/api/auth/logout-all \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Password changes are intentionally not implemented as an API endpoint yet. The app still uses a single env-backed operator credential, so a DB-backed password-change endpoint would create two competing password sources and make recovery less predictable.

To change the operator password safely:

1. Log in with the current password.
2. Call `POST /api/auth/logout-all` to revoke active sessions.
3. Stop the app.
4. Update `MOBILE_API_ADMIN_PASSWORD` in the server environment.
5. Restart the app.
6. Log in with the new password.

If the old password or token-signing secret is suspected to be compromised and you cannot trust the current session, rotate `MOBILE_API_SECRET` as well. Rotating the secret invalidates all existing access and refresh tokens because they can no longer be verified.

## User Identity Metadata

The SQLite database has a minimal `users` table for future owner/actor metadata. On initialization, the app seeds one env-backed operator user from `MOBILE_API_ADMIN_USERNAME`.

New auth sessions store the seeded operator `user_id` when available. Operational events also have optional `actor_user_id` and `owner_user_id` columns. Core resource tables such as `books`, `mobile_jobs`, `ebook_import_runs`, `provider_usage`, and `job_attempts` also carry `owner_user_id` metadata. For the current single-operator app, `owner_user_id` usually means the seeded env-backed operator; it is ownership metadata only.

This is metadata groundwork only:

- the app remains single-operator
- `MOBILE_API_ADMIN_PASSWORD` remains the source of truth for login
- no password is stored in `users`
- older sessions with an empty `user_id` remain valid if the session itself is valid
- existing core resource rows are backfilled only when `owner_user_id` is empty
- no tenant authorization or multi-user access control is enforced yet
- list/read/import/job/export routes do not filter by owner yet
- no users UI, roles, invites, or provider-key isolation exists yet

Seeding is idempotent. If `MOBILE_API_ADMIN_USERNAME` changes for an existing database, the env-backed operator row is renamed and keeps its existing stable id. P3-C3-D is expected to add explicit authorization helpers and deny-by-default tests before any route begins enforcing owner checks.

## Restart and Job Recovery

Jobs are persisted in SQLite, but execution is still in-process. New jobs are stored as `queued`, then atomically claimed with a short SQLite lease before the background coroutine runs. While running, the worker refreshes a heartbeat. A second worker/process cannot claim the same queued job after the first claim succeeds.

If the server restarts while a job is queued/running, or a running lease becomes stale, the app marks the job `interrupted` with:

```text
Job interrupted before completion
```

This prevents jobs from staying permanently `running`. Failed or interrupted translation jobs can be retried from the Trạng thái page or by calling `POST /api/jobs/{job_id}/retry`. The retry creates a new attempt from the saved job targets/config and skips chapters that already have a completed readable translation.

Known limitation: this is a SQLite lease around the existing in-process job runner, not a full durable queue. It improves duplicate protection and stale-job recovery for single-operator use, but it does not resume a partially executed coroutine after process death. A real worker queue is still required for production-grade multi-user reliability.

The same limitation applies to system backups and scheduled metadata retention:
both run in the API process. Retention retries SQLite busy/locked work at the
next interval, and its pending count-only audit recovery is process-local; a
hard process loss can therefore lose that pending audit summary even though
already committed deletions remain committed.

## Operational Status

The authenticated Trạng thái page and `/api/system/status` report:

- active, running, queued, retrying, interrupted, and failed job counts
- last failed/interrupted job
- recent sanitized operational errors
- active provider and public deploy mode
- upload limit, asset protection, database/cache size, and backup recommendation

Operational events intentionally avoid raw provider keys, stack traces, and private book text. Check server logs for full debugging detail.

## Backup

Run a backup before upgrades, migrations, large imports, or public deployment changes:

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
scripts/backup-local.sh
```

Keep only the newest local backups:

```bash
BACKUP_KEEP=14 scripts/backup-local.sh
```

This creates a tarball under `$REPO_ROOT/backups/` unless `BACKUP_DIR` is set. It contains:

- a consistent SQLite backup of `data/pipeline.db`
- imported raw/cleaned/translated text
- covers
- rich ebook assets
- audio
- exports
- dictionaries
- glossary/style/provider settings stored in SQLite

By default the script does not include `.env`, because `.env` contains secrets. Optional encrypted backups are supported with local `openssl`:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 scripts/backup-local.sh
```

Encrypted backup retention uses the same `BACKUP_KEEP` value:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 BACKUP_KEEP=14 scripts/backup-local.sh
```

To include `.env`, opt in only for a private encrypted backup:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 INCLUDE_ENV=1 scripts/backup-local.sh
```

Store backups somewhere outside the project machine if the data matters. Full restore steps are in [`docs/backup-restore.md`](backup-restore.md).

Run a restore drill without touching live data:

```bash
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz
```

For encrypted backups:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' \
.venv/bin/python scripts/ops.py restore-drill backups/novel-pipeline-backup-YYYYMMDD-HHMMSS.tar.gz.enc
```

## Restore Checklist

1. Stop the app with `scripts/stop-local.sh`, `sudo systemctl stop novel-pipeline`, or `docker compose stop`.
2. Restore the archive into `data_restored` with `.venv/bin/python scripts/ops.py restore ...`.
3. Move current `data/` aside, then move `data_restored` to `data/`.
4. Restore `.env` manually if it was not included.
5. Start the app.
6. Run the verification commands in [`docs/backup-restore.md`](backup-restore.md).

## Deployment Smoke

Use [`docs/deployment-smoke-checklist.md`](deployment-smoke-checklist.md) before relying on a Cloudflare or public-domain deployment.

The non-mutating public smoke command validates the most important public boundaries:

```bash
.venv/bin/python scripts/ops.py smoke-public \
  --base-url https://YOUR_DOMAIN \
  --username "$MOBILE_API_ADMIN_USERNAME" \
  --password "$MOBILE_API_ADMIN_PASSWORD" \
  --data-probe-path data/pipeline.db
```

It checks `/api/ready`, verifies `/docs`, `/openapi.json`, and `/redoc` are not public, probes unauthenticated asset routes, logs in with the supplied operator credentials, checks authenticated `/api/system/status`, and optionally verifies a known data path does not return `200`.

It also verifies that public readiness is sanitized, CORS allows exactly the supplied HTTPS origin, and private asset probe responses are not publicly cacheable.

Common failure meanings:

- `/docs must be disabled`: `PUBLIC_DEPLOY=1` is missing, the old app is still running, or a proxy is serving docs directly.
- asset probe returned `200`: `/covers` or `/book-assets` is exposed without auth.
- login failed: credentials do not match the server environment, or the app restarted with a different config.
- data probe returned `200`: a proxy/static server is exposing `data/`; remove that static route immediately.
- readiness leaks internal diagnostics: restart the current release with `PUBLIC_DEPLOY=1` and confirm the proxy is not serving an older app.
- CORS preflight mismatch: set `MOBILE_API_CORS_ORIGINS` to the exact public `https://` origin only.
- private asset probe is cacheable: remove public cache rules for `/covers/*`, `/book-assets/*`, and `/api/*`.

## Production Readiness Warning

This setup is acceptable for personal remote use. It is not a public SaaS deployment. Remaining production blockers include multi-user identity, tenant data isolation, abuse/cost controls, alerting, edge rate limits, and repeated restore drills from off-machine backups.
