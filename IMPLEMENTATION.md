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
```

The application currently stops at candidate grouping. It does not yet create
subscriptions, rank candidates, commit download decisions, or contact
qBittorrent.

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

### Interface

- Responsive dashboard and feed management.
- Feed test, refresh, history, and normalized entry views.
- Raw Release identity library.
- Episode candidate groups showing every subtitle-group version and its parsed
  attributes.
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
- Series grouping is provisional until catalog metadata and aliases exist.
- No user correction or reparse command exists yet.
- No global or per-anime preference profile exists yet.
- No candidate winner, waiting window, backfill decision, or revision upgrade
  decision exists yet.
- No qBittorrent adapter or content download exists yet.
- Authentication is not implemented; bind only to localhost or a trusted private
  network.

## 6. Next Planned Slice

The next coherent delivery unit is `catalog + subscriptions + selection`:

1. Bangumi-backed and local anime identities with aliases.
2. Explicit subscription activation boundaries.
3. Configurable hard filters and ordered preferences.
4. Candidate comparison explanations and preferred/fallback waiting windows.
5. Manual correction, confirmation, and backfill preview.

Only after a durable decision exists should the qBittorrent adapter be added.
