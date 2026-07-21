# Releases module

Owns canonical BitTorrent publication identity and the links from feed entries
to that identity. It consumes `FeedEntryObserved.v1` through an idempotent
handler.

## Public surface

- `ReleaseService.observe_feed_entry`
- `ReleaseService.list_releases`
- `ReleaseService.has_release`
- `ReleaseService.get_download_source`
- `ReleaseService.prune_unmatched`
- `parse_magnet_identity`
- `parse_torrent_identity`

## Invariants

- A BitTorrent v1 info hash is the preferred global identity.
- The SHA-1/SHA-256 is calculated from the exact raw bencoded `info` byte slice;
  decoded dictionaries are never re-encoded for hashing.
- Pure BitTorrent v2 releases are collected but are not automation eligible.
- `(identity_kind, identity_value)` and `(release_id, feed_entry_id)` are unique.
- Stored magnet and torrent payloads are encrypted.
- Old releases are removable only when selection and recognition public queries
  do not protect their identities.

## Does not own

- Feed configuration or retry health
- Anime title parsing
- Candidate or download selection
