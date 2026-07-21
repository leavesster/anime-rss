# Anime RSS Service Implementation Record

Status: Living implementation and decision record

Updated: 2026-07-21

This document records what the repository actually implements and the choices
made while turning `DESIGN.md` and `ARCHITECTURE.md` into code. It is intended
to make implementation review possible without reconstructing decisions from
commits or conversations.

## 1. Implemented Pipeline

```text
Configured RSS / Atom feed
  -> bounded conditional HTTP fetch
  -> normalized feed entries
  -> feed-local GUID deduplication
  -> magnet / torrent identity resolution
  -> global info-hash release deduplication
  -> deterministic title recognition
  -> exact series + episode candidate grouping
  -> catalog alias + subscription activation matching
  -> hard-filter and ordered-preference evaluation
  -> preferred decision or durable fallback wait
  -> immutable decision + DownloadRequested intent
```

The application currently stops after committing a durable download intent. It
does not yet contact qBittorrent.

## 2. Delivered Capabilities

### Runtime and ingestion

- FastAPI, SQLAlchemy, Alembic, and SQLite WAL runtime.
- Encrypted feed URLs, headers, magnet links, and torrent payloads.
- RSS/Atom normalization, ETag/Last-Modified, bounded responses, and safe
  redirect behavior.
- Feed health, persisted retry state, fetch history, and audit events.
- Feed-local entry deduplication by `(feed_id, guid_hash)`.
- Exact BitTorrent v1/v2 identity and cross-feed release deduplication.
- Durable integration events with per-consumer delivery records.

### Recognition

- Pure deterministic parser identified by `title-rules.v1`.
- Release group, localized series title, season marker, decimal/range episode,
  revision, resolution, video codec, subtitle language, and content kind.
- Immutable parse attempts for every release source observation.
- One canonical recognition candidate per Release.
- Episode groups exposed as a read projection and a separate unmatched queue.
- Startup replay for undelivered `ReleaseIdentified.v1` events, allowing an
  existing installation to gain recognition data after upgrade.

### Catalog and subscriptions

- Local anime identities and user aliases that remain usable without an
  external metadata provider.
- Bangumi anime search/import with a six-hour SQLite cache and stale-cache
  fallback during provider outages.
- One subscription per anime with following, paused, completed, and archived
  lifecycle states.
- Activation epochs, title-key snapshots, save-path intent, and versioned
  optimistic updates.
- Explicit hard filters, ordered preferences, and a configurable fallback wait.

### Selection

- Pure deterministic hard-filter and lexicographic ranking policy.
- Candidate evaluations containing filter results, stable rank tuples, and the
  exact effective rule snapshot.
- Serialized episode slots for preferred, waiting, confirmation, and decided
  states.
- Preferred candidates commit immediately; fallback deadlines never extend when
  later candidates arrive.
- Background deadline polling plus startup recovery of expired waits.
- Historical backfill preview and explicit multi-episode confirmation.
- Same-group, same-episode higher revisions create append-only upgrade
  decisions.
- Every committed decision emits `DecisionCommitted.v1` and
  `DownloadRequested.v1`; no downloader consumes the latter yet.

### Interface

- Responsive dashboard and feed management.
- Feed test, refresh, history, and normalized entry views.
- Raw Release identity library.
- Episode candidate groups showing every subtitle-group version and its parsed
  attributes.
- Anime creation/import, subscription creation and lifecycle controls, backfill
  preview, waiting-state summary, and immutable decision history.
- Generated TypeScript API types from the checked OpenAPI contract.

## 3. Decision Log

### REC-001: Release deduplication and episode grouping are separate

**Choice:** Preserve every distinct info hash as a Release. Group Releases only
in the recognition read model when they resolve to the same series and episode.

**Reason:** Different subtitle groups, sources, codecs, and revisions are real
alternatives. Physically merging them would destroy the evidence needed for
later selection and explanations.

### REC-002: Exact normalized series keys before metadata matching

**Choice:** The provisional series key is the first localized title segment
before the episode marker, normalized with Unicode NFKC, case folding, and
removal of punctuation and whitespace. No fuzzy string matching is performed.

**Reason:** False grouping is more damaging than leaving a release unmatched.
Bangumi aliases and user corrections will later replace this provisional key
with a stable catalog identity.

### REC-003: Season is parsed but not part of the provisional group key

**Choice:** Candidate groups use `(series_key, episode_key)`. A season marker is
stored and returned, but a missing `S01` and an explicit `S01` do not split the
same episode into two groups.

**Tradeoff:** Two releases with the exact same displayed series title and
episode but conflicting seasons could temporarily group together. Catalog
matching must make season identity explicit before automatic selection.

### REC-004: Episode numbers are canonical decimal strings

**Choice:** `01`, `7.50`, and `01-02` become `1`, `7.5`, and `1-2`. Floating
point values are never used.

**Reason:** Decimal episodes and ranges must remain exact and stable in database
keys and API responses.

### REC-005: Recognition confidence is structural

**Choice:** A title with release group, series, and episode is high confidence;
series and episode without a group is medium; missing series or episode is low.

**Reason:** This version measures parser evidence only. It does not claim that
the parsed series has been matched to authoritative anime metadata.

### REC-006: Recognition does not rank or reject preferences

**Choice:** Recognition records resolution, codec, subtitles, RAW, batch,
movie, and special markers but does not apply hard filters or choose a winner.
`recognition_eligible` means only that torrent identity and structural parsing
are reliable enough to enter selection.

**Reason:** 4K, subtitle, codec, and subtitle-group preferences belong to a
subscription rule snapshot owned by `selection`, not to the parser.

### REC-007: Parse attempts are immutable and candidates are idempotent

**Choice:** Every feed-entry observation has one versioned attempt. A Release
has at most one canonical candidate. Integration-event delivery is idempotent.

**Reason:** Failed and historical parser evidence must survive rule changes,
while retries and duplicate events must not create duplicate candidates.

### REC-008: Event dispatch queries pending work per consumer

**Choice:** The dispatcher selects events lacking a delivery record for the
specific consumer and drains event chains until idle with a bounded limit.

**Reason:** Reading the oldest global events and skipping delivered rows would
starve newer consumers after the event table grew beyond the batch size.

### CAT-001: Bangumi is advisory and local identity is permanent

**Choice:** Imported and locally created anime receive the same permanent local
ID. Bangumi search is cached for six hours; a stale cache may serve an outage.

**Reason:** Metadata availability must not block RSS recognition, subscription
rules, or historical review.

### SUB-001: Subscription matching uses an explicit title-key snapshot

**Choice:** Creating or editing a subscription snapshots normalized catalog
titles and supplied aliases into `match_keys`.

**Tradeoff:** Adding a catalog alias later does not silently change an existing
subscription. The subscription must be edited so the new matching boundary is
visible and reviewable.

### SUB-002: Activation time uses global Release first-seen time

**Choice:** Automatic selection accepts only candidates whose Release was first
seen at or after the current following epoch began. Pause/resume starts a new
epoch; historical items require backfill.

**Reason:** Adding another feed or resuming a subscription must not turn old
releases into unexpected automatic downloads.

### SEL-001: Unknown safety attributes fail hard filters

**Choice:** Default automatic rules require an episode content kind, recognized
Chinese subtitles, an allowed resolution, and an allowed codec. An unknown
value is not promoted into a preference rank.

**Reason:** Missing evidence is not evidence that a release satisfies a safety
requirement. The administrator can deliberately widen an allow-list.

### SEL-002: Preferences are compared lexicographically

**Choice:** Candidates compare release group, subtitle, resolution, codec,
revision descending, first-seen time, and Release identity in that order. Every
backfill loser records the first field that differed from the winner.

**Reason:** The result is deterministic, explainable, and stable across process
restarts without a weighted score whose tradeoffs are difficult to inspect.

### SEL-003: Immediate preferred means every configured first choice matches

**Choice:** A candidate is immediate only when each non-empty preference
dimension equals its first configured value. Otherwise an acceptable candidate
is a fallback.

**Reason:** This gives "preferred" a precise contract instead of treating a
single strong attribute as enough to bypass the waiting window.

### SEL-004: The first fallback fixes the deadline

**Choice:** The first acceptable fallback stores `now + fallback_wait_minutes`.
Later better fallbacks replace the current best but never extend that deadline.

**Reason:** Repeated releases cannot postpone an episode forever. The deadline
is durable, processed at startup, and polled every 30 seconds while running.

### SEL-005: Decisions and rule snapshots are append-only

**Choice:** A committed decision stores the candidate snapshot, canonical rank,
trigger, and complete rule schema v1. It then emits a durable download request
event in the same transaction.

**Reason:** Later rule edits or downloader behavior cannot rewrite why a
candidate won.

### SEL-006: Historical releases require preview and confirmation

**Choice:** Backfill ignores the activation cutoff only for preview. It applies
the current hard filters and ranking without a wait, then commits only the
episode keys explicitly confirmed by the administrator.

**Reason:** Subscription creation remains safe while historical acquisition is
still efficient and reviewable.

### SEL-007: Automatic upgrades require the same group and higher revision

**Choice:** After a slot is decided, only a candidate for the same episode and
release group with a higher revision can create an automatic upgrade decision.

**Reason:** A later release from a different group is an alternative, not a V2
replacement.

## 4. Parser v1 Contract

Supported episode shapes:

- `S01E02`
- `S01E07.5`
- `- 02`
- `- 01-02`
- bracketed episode numbers such as `[02]`
- suffix revisions such as `V2`

Recognized media attributes:

- Resolution: 2160p, 1080p, 720p, 480p and common pixel dimensions.
- Codec: HEVC/H.265/x265, AVC/H.264/x264, and AV1.
- Subtitles: simplified Chinese, traditional Chinese, combined simplified and
  traditional Chinese, RAW, or unknown.
- Content kinds: episode, batch, movie, and special/OVA/OAD.

Parser changes require a new parser version and fixture coverage. Existing
attempts are not silently rewritten.

## 5. Known Boundaries

- Identical RSS URLs can still be configured twice.
- Periodic feed scheduling has durable primitives but no running scheduler loop;
  refresh is currently manual.
- Provisional recognition grouping remains visible before a catalog identity is
  linked through a subscription alias snapshot.
- No release remap or parser re-run command exists yet.
- Rules are currently stored per subscription; named reusable global preference
  profiles are not implemented.
- Medium-confidence confirmation is represented in state but has no manual
  correction/approval command yet.
- No qBittorrent adapter or content download exists yet.
- `DownloadRequested.v1` events are durable intents with no consumer until the
  download slice is installed.
- Authentication is not implemented; bind only to localhost or a trusted private
  network.

## 6. Next Planned Slice

The next coherent delivery unit is the `downloads` slice:

1. qBittorrent Web API adapter and connectivity validation.
2. DB-first submission attempts with immutable idempotency keys.
3. Query-by-info-hash before every add or retry.
4. Task reconciliation, stale observations, external pause, and external
   deletion behavior.
5. Revision replacement cancellation saga without deleting completed files.

The selection decision and its emitted download intent are already durable, so
the next slice can add external effects without moving rule logic into the
adapter.
