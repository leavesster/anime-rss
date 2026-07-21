# Anime RSS Service

Single-user, self-hosted anime RSS ingestion and download automation. Product
requirements live in `DESIGN.md`; module boundaries and dependency rules live
in `ARCHITECTURE.md`; implemented behavior and concrete choices are tracked in
`IMPLEMENTATION.md`; first-release proof is tracked in `ACCEPTANCE.md`.

## Current implementation status

The feed-to-qBittorrent product path and self-hosted delivery layer are implemented:

- FastAPI application and SQLite/Alembic runtime
- encrypted feed URLs, headers, magnet links, and torrent payloads
- bounded RSS/Atom fetching with safe redirect handling and cache validators
- persisted feed health, retry state, fetch history, and normalized entries
- exact raw bencoded `info` hashing for v1, hybrid, and pure v2 torrents
- cross-feed release deduplication through durable integration events
- durable scheduler leases, execution history, recovery, and automatic feed refresh
- responsive React dashboard, feed management, fetch history, and release library
- generated TypeScript API types and production static asset serving
- deterministic title recognition and same-episode candidate grouping
- local/Bangumi anime catalog and lifecycle-aware subscriptions
- deterministic hard filters, ordered preferences, fallback waits, and backfill decisions
- encrypted qBittorrent configuration and connectivity validation
- idempotent magnet/torrent submission, task reconciliation, and explicit retry
- V2/V3 cancellation without deleting completed files
- dependency health, failed-work aggregation, and append-only audit history
- manual candidate confirmation and unmatched-release mapping
- first-run administrator setup, session cookies, and CSRF-protected mutations
- in-application notifications and encrypted Webhook delivery with durable retry
- portable SQLite and master-key backups, retention, and restart-safe restore staging
- production image, Compose data volume, readiness health check, and non-root runtime
- versioned implementation decision record for handoff and review
- advisory airing calendar, per-anime episode history, and one-time missing warnings

The application is designed for one administrator and one process. Put it behind
HTTPS before exposing it outside a trusted network and set
`ANIME_RSS_AUTH_COOKIE_SECURE=true` when TLS terminates at the service origin.

## Docker Compose

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:8080` and complete the administrator setup. Compose stores
the database, encryption key, seven rolling backup archives, and 14 days of JSONL
application logs in the `anime-rss-data` volume. Do not delete or recreate that
volume during an image upgrade.

To run a published image instead of building locally, set `ANIME_RSS_IMAGE`:

```bash
ANIME_RSS_IMAGE=ghcr.io/OWNER/anime-rss-service:VERSION docker compose up -d
```

Create an operator backup before upgrades either in the system page or with:

```bash
docker compose exec anime-rss anime-rss backup --data-dir /data
docker compose build --pull
docker compose up -d
docker compose ps
```

Migrations run before HTTP and scheduled work starts. To roll back application
data, upload a `.backup` archive in the system page and restart the container:

```bash
docker compose restart anime-rss
```

Restore archives contain the master encryption key and must be protected like
credentials. Applying a staged restore creates a `pre-restore` archive first.

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

Run `make acceptance-compose` before changing image packaging, migrations, or
backup behavior. It builds a historical baseline and the current image, then
verifies clean setup, backup, in-place upgrade, clean-volume restore, and
backup-based rollback with disposable Compose projects.

For real-feed release acceptance, run `make acceptance-soak-preflight`. After it
reports two healthy feeds, two following Bangumi anime, a verified qBittorrent
connection, and a healthy scheduler, run `make acceptance-soak-start` once.
`make acceptance-soak-status` and `make acceptance-soak-report` inspect the
immutable seven-day window without exposing feed URLs or downloader credentials.

## Implemented API

```text
GET    /api/v1/health/live
GET    /api/v1/health/ready
GET    /api/v1/auth/status
POST   /api/v1/auth/setup
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
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
POST   /api/v1/recognition/candidates/{candidate_id}/confirm
POST   /api/v1/recognition/releases/{release_id}/remap
POST   /api/v1/recognition/releases/{release_id}/rerun
GET    /api/v1/catalog/anime
POST   /api/v1/catalog/anime
GET    /api/v1/catalog/bangumi/search
POST   /api/v1/catalog/bangumi/{bangumi_id}/import
PUT    /api/v1/catalog/anime/{anime_id}/schedule
GET    /api/v1/subscriptions
POST   /api/v1/subscriptions
PATCH  /api/v1/subscriptions/{subscription_id}
GET    /api/v1/subscriptions/preferences/global
PUT    /api/v1/subscriptions/preferences/global
GET    /api/v1/selection/episodes
GET    /api/v1/selection/decisions
POST   /api/v1/selection/process-due
GET    /api/v1/selection/subscriptions/{subscription_id}/backfill-preview
POST   /api/v1/selection/subscriptions/{subscription_id}/backfill-commit
POST   /api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/select
POST   /api/v1/selection/subscriptions/{subscription_id}/candidates/{candidate_id}/reject
POST   /api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/reset
POST   /api/v1/selection/subscriptions/{subscription_id}/episodes/{episode_key}/acquired-elsewhere
GET    /api/v1/selection/manual-actions
GET    /api/v1/downloads/config
PUT    /api/v1/downloads/config
POST   /api/v1/downloads/config/test
GET    /api/v1/downloads/tasks
POST   /api/v1/downloads/tasks/{task_id}/retry
POST   /api/v1/downloads/process
GET    /api/v1/schedule/calendar
GET    /api/v1/schedule/missing
GET    /api/v1/schedule/anime/{anime_id}/episodes
POST   /api/v1/schedule/sync
GET    /api/v1/operations/overview
GET    /api/v1/operations/jobs
GET    /api/v1/operations/runs
POST   /api/v1/operations/run-now
GET    /api/v1/notifications
POST   /api/v1/notifications/{notification_id}/read
GET    /api/v1/notifications/config
PUT    /api/v1/notifications/config
POST   /api/v1/notifications/config/test
GET    /api/v1/system/backups
POST   /api/v1/system/backups
GET    /api/v1/system/backups/{filename}
POST   /api/v1/system/backups/restore/stage
GET    /api/v1/system/settings
PUT    /api/v1/system/settings
GET    /api/v1/audit/events
```
