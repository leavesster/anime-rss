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
- `RecognitionService.rerun_release`
- `RecognitionService.permanent_release_ids`
- `parse_release_title`

## Invariants

- Parser output is determined by title plus `PARSER_VERSION`.
- The versioned fixture contract expands to at least 300 complete golden cases;
  deterministic Unicode property cases enforce normalization, output bounds,
  and repeatability without network data.
- Episode numbers use canonical decimal strings, never floating point.
- Series keys are bounded to their 300-character persistence contract after
  case folding, and revisions are limited to three digits.
- A release has one active candidate; remapping supersedes rather than rewrites
  the previous candidate.
- Series grouping uses an exact normalized key; fuzzy matching is forbidden.
- Every source observation produces one immutable initial parse attempt; explicit
  parser re-runs append separately identified attempts, including same-version runs.
- A re-run with unchanged output retains the active candidate. A changed,
  structurally valid medium/high-confidence output supersedes it; low-confidence
  output never removes a valid active candidate.
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
