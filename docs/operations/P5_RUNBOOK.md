# P5 Operations Runbook

Personal runbook for running the Novel Pipeline FastAPI backend and P4 operator dashboard.

## Initial setup

From the project checkout:

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm --prefix web ci
python scripts/ops.py doctor
```

Create a local `.env` for secrets and runtime overrides. Do not commit it.

Minimum personal-use values:

```bash
MOBILE_API_SECRET=replace-with-a-long-random-secret
MOBILE_API_ADMIN_USERNAME=admin
MOBILE_API_ADMIN_PASSWORD=replace-this-password
DATA_DIR="$REPO_ROOT/data"
```

Build the dashboard when serving everything from the backend:

```bash
npm --prefix web run build
MOBILE_API_SERVE_WEB=1 WEB_DIST_DIR="$REPO_ROOT/web/dist" python -m app.mobile_api
```

`python -m app.mobile_api` loads `.env` from the project root before reading
mobile API settings.

## Local dev workflow

The local scripts run the API and Vite dev server separately.

```bash
scripts/start-local.sh
scripts/status-local.sh
scripts/smoke-local.sh
scripts/stop-local.sh
```

Defaults:

- API: `http://127.0.0.1:7860`
- Web: `http://127.0.0.1:5174`
- Logs and PID files: `${DATA_DIR:-data}/logs/runtime/`

Useful overrides:

```bash
MOBILE_API_PORT=7861 WEB_PORT=5175 scripts/start-local.sh
API_BASE_URL=http://127.0.0.1:7861 WEB_URL=http://127.0.0.1:5175 scripts/smoke-local.sh
```

## Single-service build

Use this when the backend should serve the compiled dashboard.

```bash
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
python -m compileall -q app scripts tests
python -m pytest -q -s
MOBILE_API_SERVE_WEB=1 WEB_DIST_DIR="$REPO_ROOT/web/dist" python -m app.mobile_api
```

Open `http://127.0.0.1:7860/`.

## Docker compose

Build and start the single container:

```bash
cp .env.example .env
# edit .env and set at least MOBILE_API_SECRET and MOBILE_API_ADMIN_PASSWORD
docker compose up --build -d
docker compose ps
curl -fsS http://127.0.0.1:7860/api/health
curl -fsS http://127.0.0.1:7860/api/ready
```

The compose service mounts `./data` to `/data` and sets:

- `DATA_DIR=/data`
- `MOBILE_API_SERVE_WEB=1`
- `WEB_DIST_DIR=/app/web/dist`

Stop or inspect logs:

```bash
docker compose logs -f novel-pipeline
docker compose down
```

Compose reads variable interpolation from the shell or a local `.env`, including provider keys and admin credentials.
It binds to `127.0.0.1` by default. Set `MOBILE_API_BIND=0.0.0.0` only when
you also have strong credentials, `REMOTE_API_KEY`, or a trusted reverse proxy.

## Cloudflare Tunnel

This checkout already has a Cloudflare tunnel route documented for:

```bash
https://novel-tnn.tradingcompanydirect.com
```

Start the app in Cloudflare single-service mode:

```bash
scripts/start-cloudflare.sh
```

Optional override:

```bash
CLOUDFLARE_HOSTNAME=novel-tnn.tradingcompanydirect.com scripts/start-cloudflare.sh
```

The script builds `web/dist` with `VITE_API_BASE_URL=https://$CLOUDFLARE_HOSTNAME`,
stops local dev services, starts FastAPI on `127.0.0.1:7860`, and verifies both
`/api/ready` and the dashboard through Cloudflare.

## systemd install

Build the dashboard first:

```bash
cd "$REPO_ROOT"
npm --prefix web ci
npm --prefix web run build
```

Create `/etc/novel-pipeline/novel-pipeline.env`:

```bash
sudo install -d -m 750 /etc/novel-pipeline
sudoedit /etc/novel-pipeline/novel-pipeline.env
sudo chmod 600 /etc/novel-pipeline/novel-pipeline.env
```

Example env file:

```bash
MOBILE_API_SECRET=replace-with-a-long-random-secret
MOBILE_API_ADMIN_USERNAME=admin
MOBILE_API_ADMIN_PASSWORD=replace-this-password
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
OPENROUTER_API_KEY=
OPENAI_API_KEY=
```

Install and start:

```bash
sudo cp deploy/systemd/novel-pipeline.service.example /etc/systemd/system/novel-pipeline.service
sudo systemctl daemon-reload
sudo systemctl enable --now novel-pipeline
systemctl status novel-pipeline
```

## Provider keys

Supported provider key environment variables:

- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`
- `REMOTE_API_KEY` for the API key header used by some remote deployments

For Docker compose, put them in `.env` or export them before `docker compose up`. For systemd, put them in `/etc/novel-pipeline/novel-pipeline.env` and run:

```bash
sudo systemctl restart novel-pipeline
```

## Health and smoke checks

Unauthenticated:

```bash
curl -fsS http://127.0.0.1:7860/api/health
curl -fsS http://127.0.0.1:7860/api/ready
curl -fsS http://127.0.0.1:7860/api/version
```

Authenticated smoke:

```bash
python scripts/ops.py smoke \
  --base-url http://127.0.0.1:7860 \
  --username "$MOBILE_API_ADMIN_USERNAME" \
  --password "$MOBILE_API_ADMIN_PASSWORD" \
  --web-url http://127.0.0.1:7860
```

System status is at `/api/system/status` after login.

Reader browser smoke:

```bash
cd "$REPO_ROOT"
.venv/bin/python scripts/smoke_reader_page.py
```

This starts the local app when needed, seeds a temporary translated smoke
chapter, verifies the reader workflow in Chromium, and writes mobile/desktop
screenshots to `output/playwright/`.

## Logs

Local scripts:

```bash
tail -f "${DATA_DIR:-data}/logs/runtime/mobile-api.log"
tail -f "${DATA_DIR:-data}/logs/runtime/web-vite.log"
```

Docker compose:

```bash
docker compose logs -f novel-pipeline
```

systemd:

```bash
journalctl -u novel-pipeline -f
journalctl -u novel-pipeline --since "1 hour ago"
```

## Backup and restore

Create a backup:

```bash
python scripts/ops.py backup --out-dir backups --label before-change
```

Include `.env` only for a private encrypted/offline backup:

```bash
BACKUP_PASSPHRASE='use-a-long-passphrase' ENCRYPT_BACKUP=1 INCLUDE_ENV=1 scripts/backup-local.sh
```

Restore into a staging directory first:

```bash
python scripts/ops.py restore backups/novel-pipeline-backup-YYYYMMDD-HHMMSS-before-change.tar.gz --target-dir data_restored
```

To replace active data:

```bash
scripts/stop-local.sh
mv data "data.broken.$(date +%Y%m%d-%H%M%S)"
mv data_restored data
scripts/start-local.sh
scripts/smoke-local.sh
```

For Docker or systemd, stop that service before moving data and start it again after restore.
Full restore and encryption steps are in `docs/backup-restore.md`.

## Rollback and recovery

Code rollback from a checkout:

```bash
git fetch
git switch main
git pull --ff-only
npm --prefix web ci
npm --prefix web run build
python -m pytest -q -s
sudo systemctl restart novel-pipeline
```

Docker rollback:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose logs -f novel-pipeline
```

Data recovery:

1. Stop the active service.
2. Restore the most recent known-good backup into `data_restored`.
3. Move the current `data` aside.
4. Move `data_restored` to `data`.
5. Start the service and run the smoke check.

If startup fails, check `DATA_DIR`, `WEB_DIST_DIR`, provider keys, and whether port `7860` is already in use.
