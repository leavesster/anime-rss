# Anime RSS Service

Single-user, self-hosted anime RSS ingestion and download automation. Product
requirements live in `DESIGN.md`; module boundaries and dependency rules live
in `ARCHITECTURE.md`.

## Current implementation status

The first backend slice is implemented:

- FastAPI application and SQLite/Alembic runtime
- encrypted feed URLs, headers, magnet links, and torrent payloads
- bounded RSS/Atom fetching with safe redirect handling and cache validators
- persisted feed health, retry state, fetch history, and normalized entries
- exact raw bencoded `info` hashing for v1, hybrid, and pure v2 torrents
- cross-feed release deduplication through durable integration events
- durable scheduler job leases

Authentication, anime metadata, title recognition, subscription decisions,
qBittorrent submission, and the React interface are later slices. The current
API is therefore a development build and must not be exposed publicly.

## Development

Python 3.13 is required.

```bash
python3 -m venv .venv
make bootstrap
make verify
make migrate
make run
```

The development API listens on `http://127.0.0.1:8080`; OpenAPI is available at
`/docs`. Runtime data defaults to `./data` and is ignored by Git.

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
```
