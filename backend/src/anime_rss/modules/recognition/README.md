# Recognition Module

Owns deterministic parsing attempts and episode candidate projections. It
consumes `ReleaseIdentified.v1` and reads release observations only through the
`releases.api` public contract.

## Public surface

- `RecognitionService.handle_release_identified`
- `RecognitionService.list_episode_groups`
- `RecognitionService.list_unmatched`
- `parse_release_title`

## Invariants

- Parser output is determined by title plus `PARSER_VERSION`.
- Episode numbers use canonical decimal strings, never floating point.
- A release has at most one canonical candidate.
- Series grouping uses an exact normalized key; fuzzy matching is forbidden.
- Every source observation produces an immutable parse attempt.

## Does not own

- Anime metadata or aliases
- Subscription rules
- Candidate ranking or download decisions
- qBittorrent state
