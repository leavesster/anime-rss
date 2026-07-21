# Selection module

Owns deterministic candidate evaluations, fixed fallback deadlines, serialized
episode slots, immutable decisions, backfill previews, revision upgrades, and
append-only manual episode actions.

It consumes recognition and subscription DTOs through their public `api.py`
surfaces. It never reparses titles and never calls a downloader. A committed
decision emits `DownloadRequested.v1`; replacement also emits
`DownloadCancellationRequested.v1`, leaving external effects to downloads.
