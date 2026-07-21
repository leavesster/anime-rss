# Schedule module

Owns durable expected-episode rows, calendar projections, and one-time missing
episode notification markers.

The module reads anime metadata, subscriptions, selection slots, and instance
settings only through their public `api.py` DTOs. Schedule metadata is advisory:
this module may emit `EpisodeMissing.v1`, but it must never emit a candidate,
selection, or download event.
