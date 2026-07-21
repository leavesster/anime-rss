# Feeds module

Owns configured feed endpoints, fetch history, normalized feed entries, retry
state, and feed health. It emits `FeedEntryObserved.v1` after a new entry is
stored.

## Public surface

- `FeedService`: create, update, delete, list, test, refresh, and prune feed history
- `FeedEntryQueries`: read a normalized entry and decrypt its torrent reference
- `FeedEntryObserved.v1`: payload contains only `feed_entry_id`

## Invariants

- Endpoint URLs, custom headers, and torrent references are encrypted at rest.
- A key-derived blind index prevents duplicate endpoint URLs without storing a
  plaintext or directly guessable URL digest.
- API responses and audit events contain only redacted URLs.
- `(feed_id, guid_hash)` is unique even if concurrent refreshes overlap.
- HTTP 401/403 enters `auth_failed` without automatic retry.
- Successful 304 responses reset transient failures.
- Failed fetch diagnostics expire after seven days; other fetch history and
  unresolved entries expire after 90 days by default.

## Does not own

- BitTorrent identity or cross-feed deduplication
- Anime title parsing or matching
- Download selection
