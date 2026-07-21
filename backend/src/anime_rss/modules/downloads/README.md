# Downloads module

Owns encrypted qBittorrent configuration, durable download tasks, submission
attempts, idempotency keys, cancellation requests, and observed downloader state.

Public surface:

- `DownloadService`: public configuration, intent-planning, retry, and query facade.
- `DownloadWorker`: internal submission, cancellation, recovery, and reconciliation loop.
- `Downloader` and query ports: dependency boundaries for external effects and source DTOs.
- `QbittorrentClient`: adapter implementing the product-level `Downloader` port.
- `/api/v1/downloads`: configuration, connectivity, task, retry, and sync APIs.

It consumes release payload and subscription path DTOs through public module
APIs. It never decides which candidate wins and never mutates selection history.
