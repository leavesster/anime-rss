# Anime RSS Service

Single-user, self-hosted anime RSS ingestion and download automation. Product
requirements live in `DESIGN.md`; module boundaries and dependency rules live
in `ARCHITECTURE.md`; implemented behavior and concrete choices are tracked in
`IMPLEMENTATION.md`.

## Current implementation status

The ingestion slice and its first management interface are implemented:

- FastAPI application and SQLite/Alembic runtime
- encrypted feed URLs, headers, magnet links, and torrent payloads
- bounded RSS/Atom fetching with safe redirect handling and cache validators
- persisted feed health, retry state, fetch history, and normalized entries
- exact raw bencoded `info` hashing for v1, hybrid, and pure v2 torrents
- cross-feed release deduplication through durable integration events
- durable scheduler job leases
- responsive React dashboard, feed management, fetch history, and release library
- generated TypeScript API types and production static asset serving
- deterministic title recognition and same-episode candidate grouping
- local/Bangumi anime catalog and lifecycle-aware subscriptions
- deterministic hard filters, ordered preferences, fallback waits, and backfill decisions
- versioned implementation decision record for handoff and review

Authentication and qBittorrent submission are later slices. The current
application is therefore a development build and must not be exposed publicly.

## Development

Python 3.13 is required.
Node.js 22 is required for frontend development.

```bash
python3 -m venv .venv
make bootstrap
make bootstrap-web
make verify
make migrate
make run
```

Build the web application with `make build-web`. The backend then serves both
the interface and API at `http://127.0.0.1:8080`; OpenAPI remains available at
`/docs`. During frontend development, run `make run-web` in a second terminal
and open `http://127.0.0.1:5173`; Vite proxies API calls to the backend. Runtime
data defaults to `./data` and is ignored by Git.

## Implemented API

```text
GET    /api/v1/health/live
GET    /api/v1/health/ready
POST   /api/v1/feeds
GET    /api/v1/feeds
PATCH  /api/v1/feeds/{feed_id}
DELETE /api/v1/feeds/{feed_id}
POST   /api/v1/feeds/test
POST   /api/v1/feeds/{feed_id}/refresh
GET    /api/v1/feeds/{feed_id}/entries
GET    /api/v1/feeds/{feed_id}/fetches
GET    /api/v1/releases
GET    /api/v1/recognition/episode-groups
GET    /api/v1/recognition/unmatched
GET    /api/v1/catalog/anime
POST   /api/v1/catalog/anime
GET    /api/v1/catalog/bangumi/search
POST   /api/v1/catalog/bangumi/{bangumi_id}/import
GET    /api/v1/subscriptions
POST   /api/v1/subscriptions
PATCH  /api/v1/subscriptions/{subscription_id}
GET    /api/v1/selection/episodes
GET    /api/v1/selection/decisions
POST   /api/v1/selection/process-due
GET    /api/v1/selection/subscriptions/{subscription_id}/backfill-preview
POST   /api/v1/selection/subscriptions/{subscription_id}/backfill-commit
```
