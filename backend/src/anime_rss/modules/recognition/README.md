# Recognition Module

Owns deterministic parsing attempts and episode candidate projections. It
consumes `ReleaseIdentified.v1` and reads release observations only through the
`releases.api` public contract.

## Public surface

- `RecognitionService.handle_release_identified`
- `RecognitionService.list_episode_groups`
- `RecognitionService.list_unmatched`
- `RecognitionService.confirm_candidate`
- `RecognitionService.remap_release`
- `RecognitionService.permanent_release_ids`
- `parse_release_title`

## Invariants

- Parser output is determined by title plus `PARSER_VERSION`.
- Episode numbers use canonical decimal strings, never floating point.
- A release has one active candidate; remapping supersedes rather than rewrites
  the previous candidate.
- Series grouping uses an exact normalized key; fuzzy matching is forbidden.
- Every source observation produces an immutable parse attempt.
- Manual confirmation and release mapping append action records; they never
  rewrite the parser attempt that required intervention.
- Superseded candidates remain addressable for historical decisions but are
  excluded from current grouping and automatic selection queries.
- A manually confirmed or corrected release fingerprint is permanently protected
  from unmatched-release retention.

## Does not own

- Anime metadata or aliases
- Subscription rules
- Candidate ranking or download decisions
- qBittorrent state
