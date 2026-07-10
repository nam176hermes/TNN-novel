FROM node:22-bookworm-slim AS web-build

WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    MOBILE_API_HOST=0.0.0.0 \
    MOBILE_API_PORT=7860 \
    MOBILE_API_SERVE_WEB=1 \
    WEB_DIST_DIR=/app/web/dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY --from=web-build /app/web/dist ./web/dist

RUN mkdir -p /data

EXPOSE 7860
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${MOBILE_API_PORT}/api/ready" >/dev/null || exit 1

CMD ["python", "-m", "app.mobile_api"]
