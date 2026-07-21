# Selection module

Owns deterministic candidate evaluations, fixed fallback deadlines, serialized
episode slots, immutable decisions, backfill previews, and revision upgrades.

It consumes recognition and subscription DTOs through their public `api.py`
surfaces. It never reparses titles and never calls a downloader. A committed
decision emits `DownloadRequested.v1`; the future downloads module will own the
external side effect.
