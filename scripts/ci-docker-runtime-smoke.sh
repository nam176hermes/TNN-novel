#!/usr/bin/env bash
set -euo pipefail

SMOKE_ID="${CI_DOCKER_SMOKE_ID:-novel-pipeline-ci}"
RELEASE_ID="${CI_DOCKER_RELEASE_ID:-ci}"
GIT_SHA="${CI_DOCKER_GIT_SHA:-unknown}"
IMAGE_DIGEST="${CI_DOCKER_IMAGE_DIGEST:-sha256:ci}"
API_IMAGE="${CI_API_IMAGE:-novel-pipeline-api:ci}"
WORKER_IMAGE="${CI_WORKER_IMAGE:-novel-pipeline-import-worker:ci}"
API_CONTAINER="${SMOKE_ID}-api"
WORKER_CONTAINER="${SMOKE_ID}-worker"
DATA_VOLUME="${SMOKE_ID}-data"

if [[ ! "$SMOKE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]]; then
  echo "invalid CI_DOCKER_SMOKE_ID" >&2
  exit 2
fi

cleanup() {
  local exit_status=$?
  set +e
  docker logs "$API_CONTAINER" >/dev/null 2>&1 || true
  docker logs "$WORKER_CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "$WORKER_CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$DATA_VOLUME" >/dev/null 2>&1 || true
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

docker volume create "$DATA_VOLUME" >/dev/null

docker run -d \
  --name "$WORKER_CONTAINER" \
  --mount "type=volume,src=${DATA_VOLUME},dst=/data" \
  -e DATA_DIR=/data \
  -e "NOVEL_RELEASE_ID=${RELEASE_ID}" \
  -e "NOVEL_GIT_SHA=${GIT_SHA}" \
  -e "NOVEL_IMAGE_DIGEST=${IMAGE_DIGEST}" \
  "$WORKER_IMAGE" >/dev/null

worker_ready=0
for _ in $(seq 1 30); do
  if docker exec "$WORKER_CONTAINER" python -m app.import_worker --healthcheck; then
    worker_ready=1
    break
  fi
  sleep 1
done
if [[ "$worker_ready" != "1" ]]; then
  echo "import worker did not become healthy" >&2
  exit 1
fi

docker run -d \
  --name "$API_CONTAINER" \
  --mount "type=volume,src=${DATA_VOLUME},dst=/data" \
  -p 127.0.0.1:7860:7860 \
  -e DATA_DIR=/data \
  -e PUBLIC_DEPLOY=1 \
  -e MOBILE_API_SECRET=ci-only-not-a-real-secret-000000000000 \
  -e MOBILE_API_ADMIN_USERNAME=ci-operator \
  -e MOBILE_API_ADMIN_PASSWORD=ci-only-not-a-real-password \
  -e MOBILE_API_CORS_ORIGINS=https://ci.example.test \
  -e "NOVEL_RELEASE_ID=${RELEASE_ID}" \
  -e "NOVEL_GIT_SHA=${GIT_SHA}" \
  -e "NOVEL_IMAGE_DIGEST=${IMAGE_DIGEST}" \
  "$API_IMAGE" >/dev/null

api_ready=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:7860/api/ready >/dev/null; then
    api_ready=1
    break
  fi
  sleep 1
done
if [[ "$api_ready" != "1" ]]; then
  echo "API did not become ready" >&2
  exit 1
fi

curl -fsS http://127.0.0.1:7860/api/ready >/dev/null
curl -fsS http://127.0.0.1:7860/ | grep -q '<div id="root"></div>'
