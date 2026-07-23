FROM node:22-bookworm-slim AS web-build

ARG NOVEL_FRONTEND_VERSION=0.1.0
ARG NOVEL_RELEASE_ID=development
ENV VITE_APP_VERSION=${NOVEL_FRONTEND_VERSION} \
    VITE_RELEASE_ID=${NOVEL_RELEASE_ID}

WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime-base

ARG NOVEL_APP_VERSION=0.1.0
ARG NOVEL_FRONTEND_VERSION=0.1.0
ARG NOVEL_GIT_SHA=unknown
ARG NOVEL_BUILD_TIMESTAMP=unknown
ARG NOVEL_RELEASE_ID=development
ARG NOVEL_IMAGE_TAG=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    HOME=/tmp/novel \
    MOBILE_API_HOST=0.0.0.0 \
    MOBILE_API_PORT=7860 \
    NOVEL_APP_VERSION=${NOVEL_APP_VERSION} \
    NOVEL_FRONTEND_VERSION=${NOVEL_FRONTEND_VERSION} \
    NOVEL_GIT_SHA=${NOVEL_GIT_SHA} \
    NOVEL_BUILD_TIMESTAMP=${NOVEL_BUILD_TIMESTAMP} \
    NOVEL_RELEASE_ID=${NOVEL_RELEASE_ID} \
    NOVEL_IMAGE_TAG=${NOVEL_IMAGE_TAG}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 novel \
    && useradd --uid 10001 --gid novel --create-home --shell /usr/sbin/nologin novel

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=novel:novel app ./app
COPY --chown=novel:novel scripts ./scripts
COPY --from=web-build --chown=novel:novel /app/web/dist ./web/dist

RUN mkdir -p /data /tmp/novel \
    && chown -R novel:novel /data /tmp/novel

VOLUME ["/data"]

FROM runtime-base AS import-worker

# Chromium belongs only to the worker image. The API target remains smaller and
# cannot launch a browser even when a source adapter is misconfigured.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && chown -R novel:novel /ms-playwright

USER novel
CMD ["sh", "-c", "umask 007 && exec python -m app.import_worker"]

FROM runtime-base AS api

# Chromium installed here too so preview/fetch can do stealth browser fallback
# without delegating to the import-worker.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    MOBILE_API_SERVE_WEB=1 \
    WEB_DIST_DIR=/app/web/dist

RUN playwright install --with-deps chromium \
    && chown -R novel:novel /ms-playwright

USER novel
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${MOBILE_API_PORT}/api/ready" >/dev/null || exit 1

CMD ["sh", "-c", "umask 007 && exec python -m app.mobile_api"]
