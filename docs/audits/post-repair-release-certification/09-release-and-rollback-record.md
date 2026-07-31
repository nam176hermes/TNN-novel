# Release and rollback record

## Certification result

Certified source: `13e2b05d2142c6b5ae94d6dcbc718930cb8b8565`

Current production release: `ws6-production-20260723-r1`

Decision: **GO_WITH_LIMITATIONS**

Certification did not deploy, restart, migrate, or change production. The live
release already points to the certified source commit.

## Verification commands

```bash
scripts/verify.sh --self-test-failure

NOVEL_PIPELINE_IGNORE_DOTENV=1 \
NOVEL_PIPELINE_PRODUCTION_ENV_FILE=/home/thenam176/.config/novel-tnn/production.env \
scripts/verify.sh

npm --prefix web run test:e2e -- --project=chromium
npm --prefix web audit --omit=dev --audit-level=high
uvx pip-audit --path .venv/lib/python3.11/site-packages
.venv/bin/python scripts/check-runtime-contract.py \
  novel-tnn-wsl-api-1 novel-tnn-wsl-import-worker-1
git diff --check
git status --short
```

Fresh Docker builds used explicit certification tags and the exact Git SHA.
An isolated smoke used alternate loopback ports/data and was destroyed after
evidence capture.

## Release pins

- Current overlay:
  `deploy/production/compose.release.ws6-production-20260723-r1.yaml`
- Rollback overlay:
  `deploy/production/compose.rollback.pre-ws6-production-20260723-r1.yaml`
- Canonical procedure: `docs/production-release-runbook.md`

## Rollback trigger

Use rollback if health/readiness fails, API and worker release IDs differ,
worker claim capability is false, protected downloads fail, or repeated
startup/database errors appear.

## Executable rollback sequence

The following is recorded, not executed during certification:

```bash
REPO=/home/thenam176/Novel-TNN
PROJECT_NAME=novel-tnn-wsl
PRODUCTION_ENV=/home/thenam176/.config/novel-tnn/production.env
ROLLBACK_OVERLAY=deploy/production/compose.rollback.pre-ws6-production-20260723-r1.yaml
cd "$REPO"

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml -f "$ROLLBACK_OVERLAY" config --images

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml -f "$ROLLBACK_OVERLAY" \
  up --detach --no-build --force-recreate import-worker

docker compose -p "$PROJECT_NAME" \
  --env-file "$PRODUCTION_ENV" \
  -f compose.yaml -f "$ROLLBACK_OVERLAY" \
  up --detach --no-build --force-recreate api

curl --fail --silent --show-error http://127.0.0.1:7860/api/health
curl --fail --silent --show-error http://127.0.0.1:7860/api/ready
```

After rollback, verify public health/readiness with a browser-like user agent,
release match, worker heartbeat, protected downloads, and logs. Do not restore
data unless a separately approved data rollback is required. Preserve current
and rollback images until an approved retention cleanup.

## Recovery evidence

- Encrypted backup current and non-zero.
- Fresh isolated restore drill passed DB, artifact, API, and Reader checks.
- Rollback changes application images only; this release introduced no schema
  migration requiring data rollback.

## Approval record

No production cutover approval was requested because no deployment was needed
or performed. Any future dependency, observability, ingress, session, or image
change requires its own reviewed task and approval gate.
