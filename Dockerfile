FROM node:24-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS web-builder

WORKDIR /source/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS runtime

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
