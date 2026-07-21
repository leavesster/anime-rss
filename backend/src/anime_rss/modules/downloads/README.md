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
Subscription save paths override the instance default; otherwise a new task
captures the configured default path, category, and tags when it is planned.
Tasks have one explicit immutable origin: `selection_decision` tasks reference a
Decision and Subscription, while `manual_release` tasks reference neither. Manual
release submission reuses an existing task for the same Release, records its
intent before any network call, and then uses the same worker and info-hash
reconciliation path as automatic downloads.
`DownloadService.retained_release_ids` also protects Release payloads referenced
by task history from unmatched-entry retention.

## Compatibility

- The adapter accepts qBittorrent `>=4.6.0,<6.0.0` with Web API major version 2.
- Connection tests query and return both application and Web API versions.
- `make acceptance-qbittorrent` runs the production adapter against fixed real
  `4.6.7 / 2.9.3` and `5.0.4 / 2.11.2` containers and exercises add, lookup,
  and incomplete cancellation.

## Reconciliation invariants

- One successful empty lookup marks an observed task as unconfirmed and stale;
  only a second consecutive successful empty lookup makes it
  `externally_removed`. A failed lookup or a present task resets the count.
- A replacement submission remains planned until its predecessor has persisted
  cancellation or completion and `superseded_at` is set.
- Cancellation always uses `deleteFiles=false`.
