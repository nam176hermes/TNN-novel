# Canonical Production Release Runbook

This is the canonical WSL production Compose contract. Secrets stay outside
the repository; image pins stay in a versioned repository overlay.

## Canonical inputs

Run from the WSL repository:

```bash
REPO=/home/thenam176/Novel-TNN
PROJECT_NAME=novel-tnn-wsl
PRODUCTION_ENV="${HOME}/.config/novel-tnn/production.env"
RELEASE_OVERLAY=deploy/production/compose.release.ws6-production-20260723-r1.yaml
ROLLBACK_OVERLAY=deploy/production/compose.rollback.pre-ws6-production-20260723-r1.yaml
PUBLIC_BASE_URL=https://novel-tnn.tradingcompanydirect.com
cd "$REPO"
```

`compose.yaml` is the tracked base. `$RELEASE_OVERLAY` is the current release
pin. Historical external Phase 4 and TTS overrides are evidence only; do not
add them to new commands because this versioned overlay replaces their final
image choices.

`$PRODUCTION_ENV` is operator-owned. Never commit it, copy its values into an
overlay, or run `docker compose config` without `--quiet` or `--images`.
Require a regular mode-`0600` file before release:

```bash
test -f "$PRODUCTION_ENV"
test "$(stat -c '%a' "$PRODUCTION_ENV")" = 600
```

It must contain production-safe `MOBILE_API_SECRET`,
`MOBILE_API_ADMIN_USERNAME`, `MOBILE_API_ADMIN_PASSWORD`, `PUBLIC_DEPLOY=1`,
and HTTPS-only `MOBILE_API_CORS_ORIGINS`. Provider keys stay in this file.

For a full checkout verification on the WSL host, opt into the production-aware
environment check. It validates the external file's mode and required safe
configuration shape without sourcing or displaying secret values; container
health, volume permissions, and SQLite checks remain part of the release
verification below.

```bash
NOVEL_PIPELINE_PRODUCTION_ENV_FILE="$PRODUCTION_ENV" scripts/verify.sh
```

## Render and deploy

Render syntax without displaying secrets, then render only image references:

```bash
docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$RELEASE_OVERLAY" \
  config --quiet

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$RELEASE_OVERLAY" \
  config --images
```

For `ws6-production-20260723-r1`, expected images are:

```text
novel-pipeline-api:ws6-production-20260723-r1
novel-pipeline-import-worker:ws6-production-20260723-r1
```

The overlay comments record image IDs. Confirm them before deployment:

```bash
docker image inspect \
  novel-pipeline-api:ws6-production-20260723-r1 \
  novel-pipeline-import-worker:ws6-production-20260723-r1 \
  --format '{{index .RepoTags 0}} {{.Id}}'
```

Confirm no durable job has `queued` or `running` status. Recreate the worker
first, verify its health, then recreate API with the same exact file chain.
Worker-first cutover avoids making the new API fail its release-match readiness
check while an old worker is still reporting a different release ID:

```bash
docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$RELEASE_OVERLAY" \
  up --detach --no-build --force-recreate import-worker

docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}} {{.State.Health.Status}}' \
  novel-tnn-wsl-import-worker-1

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$RELEASE_OVERLAY" \
  up --detach --no-build --force-recreate api

curl --fail --silent --show-error http://127.0.0.1:7860/api/health
curl --fail --silent --show-error http://127.0.0.1:7860/api/ready
```

`--no-build` is required for an image-pinned release. It prevents an accidental
build from a checkout containing runtime data, backups, or unrelated changes.

## Verify and roll back

After deployment, verify both image references and local/public readiness:

```bash
docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}} {{.State.Health.Status}}' \
  novel-tnn-wsl-api-1 \
  novel-tnn-wsl-import-worker-1

curl --fail --silent --show-error http://127.0.0.1:7860/api/health
curl --fail --silent --show-error http://127.0.0.1:7860/api/ready
curl --fail --silent --show-error "$PUBLIC_BASE_URL/api/health"
curl --fail --silent --show-error "$PUBLIC_BASE_URL/api/ready"
```

For runtime hardening, inspect the application process rather than
`docker-init` PID 1. It must have `Umask: 0007`; database, WAL, and SHM must
be `0660`. Do not delete healthy production sidecars to test recreation.

To roll back, render the tracked rollback overlay first and then recreate the
worker followed by API with the same project and environment file. This keeps
the readiness/release-match ordering consistent with forward deployment:

```bash
docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$ROLLBACK_OVERLAY" \
  config --images

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$ROLLBACK_OVERLAY" \
  up --detach --no-build --force-recreate import-worker

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml \
  -f "$ROLLBACK_OVERLAY" \
  up --detach --no-build --force-recreate api
```

Keep release and rollback tags until an explicitly approved retention cleanup.
