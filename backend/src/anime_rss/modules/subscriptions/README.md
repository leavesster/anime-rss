# Subscriptions module

Owns subscription lifecycle, activation cutoffs, title-key snapshots, and
preference rules. It exposes an immutable selection-facing DTO from `api.py`.

It does not parse titles, rank candidates, or contact a downloader. Resuming a
subscription starts a new activation epoch; releases first seen while paused
remain historical and require backfill.
