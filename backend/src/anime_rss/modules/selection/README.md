# Selection module

Owns deterministic candidate evaluations, fixed fallback deadlines, serialized
episode slots, immutable decisions, backfill previews, revision upgrades, and
append-only manual episode actions.

It consumes recognition and subscription DTOs through their public `api.py`
surfaces. It never reparses titles and never calls a downloader. A committed
decision emits `DownloadRequested.v1`; replacement also emits
`DownloadCancellationRequested.v1`, leaving external effects to downloads.

Recognition remaps append selection correction actions. Undecided slots using
the old candidate reopen; decided slots retain their immutable decision snapshot
while the replacement candidate is evaluated through the normal path.

Parser-driven Candidate supersession follows the same reassignment boundary and
is consumed before replacement evaluation, so an undecided slot cannot retain a
superseded candidate.

`SelectionService.retained_release_ids` exposes the releases referenced by
evaluations, decisions, or manual actions so operations can apply retention
without querying selection-owned tables.
