FROM node:26-bookworm-slim@sha256:2d49d876e96237d76de412761cf05dbfe5aee325cc4406a4d41d5824c5bb8beb AS web-builder

WORKDIR /source/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANIME_RSS_DATA_DIR=/data \
    ANIME_RSS_WEB_DIST_DIR=/app/web/dist \
    ANIME_RSS_RUNTIME_ROOT=/app

WORKDIR /app
COPY pyproject.toml DESIGN.md README.md alembic.ini ./
COPY backend/ ./backend/
COPY migrations/ ./migrations/
RUN pip install --no-cache-dir . \
    && groupadd --system anime-rss \
    && useradd --system --gid anime-rss --home-dir /app anime-rss \
    && mkdir -p /data /app/web/dist \
    && chown -R anime-rss:anime-rss /data /app
COPY --from=web-builder --chown=anime-rss:anime-rss /source/web/dist/ /app/web/dist/

USER anime-rss
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health/ready', timeout=3)"

CMD ["anime-rss", "serve", "--host", "0.0.0.0", "--port", "8080"]
