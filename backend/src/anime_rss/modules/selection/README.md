# Selection module

Owns deterministic candidate evaluations, fixed fallback deadlines, serialized
episode slots, immutable decisions, backfill previews, revision upgrades, and
append-only manual episode actions. It also owns scaled episode-span coverage:
range decisions append one coverage fact per atomic episode, fully covered later
releases are skipped, and partial overlaps require an explicit manual selection.

Coverage is acquisition history, not mutable slot state. Resetting a decision
does not erase coverage or make a normal backfill eligible again. A deliberate
manual candidate selection may cross that boundary and creates another immutable
Decision plus its own coverage facts.

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
