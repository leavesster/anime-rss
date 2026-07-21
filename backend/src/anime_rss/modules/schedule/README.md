# Schedule module

Owns durable expected-episode rows, versioned episode-level schedule overrides,
calendar projections, and one-time missing-episode notification markers.

The module reads anime metadata, subscriptions, selection slots, and instance
settings only through their public `api.py` DTOs. Schedule metadata is advisory:
this module may emit `EpisodeMissing.v1`, but it must never emit a candidate,
selection, or download event.

## Projection rules

Synchronization first generates the anime's numeric seven-day baseline from
catalog metadata, then merges overrides by `(anime_id, episode_key)`:

- a replacement timestamp moves an existing episode;
- multiple keys may share one timestamp for double-episode broadcasts;
- a key such as `SP1` or `OVA1` adds an episode outside the numeric baseline;
- `cancelled=true` removes the key from the active projection;
- a timestamp outside the subscription activation-to-sync horizon removes the
  key from the active projection until it enters that horizon.

Rows that leave the active projection become `inactive`; they are not deleted.
Deleting an override lets the next synchronization restore the baseline row.
Changing or reactivating a schedule clears its prior missing-notification claim,
so the corrected broadcast time receives its own one-time evaluation.

## Mutation contract

`PUT` is idempotent for an unchanged payload. Existing rows accept `If-Match`
for optimistic version checks, and create, update, and delete operations are
audited. Non-cancelled overrides require a timezone-aware timestamp. Episode
keys are limited to 52 ASCII letters, numbers, dots, underscores, and hyphens;
`source` records `manual` or a future provider identifier without giving the
provider ownership of expected-episode or selection state.
