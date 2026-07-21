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
  -> durable download task + immutable idempotency key
  -> query qBittorrent by info hash
  -> submit magnet / torrent payload
  -> reconcile external task state
```

The application now completes the selected-release path through qBittorrent and
keeps the local task projection synchronized with external runtime state. It is
packaged as a first-run authenticated, recoverable Compose service.

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
- One durable scheduler loop for feed refresh, event dispatch, selection
  deadlines, and download reconciliation.
- Persisted scheduler heartbeats, leases, attempts, execution history, and
  expired-run recovery.

### Recognition

- Pure deterministic parser identified by `title-rules.v1`.
- Release group, localized series title, season marker, decimal/range episode,
  revision, resolution, video codec, subtitle language, and content kind.
- Immutable parse attempts for every release source observation.
- One canonical recognition candidate per Release.
- Episode groups exposed as a read projection and a separate unmatched queue.
- Startup replay for undelivered `ReleaseIdentified.v1` events, allowing an
  existing installation to gain recognition data after upgrade.
- Explicit confirmation for medium-confidence candidates and structured mapping
  for previously unmatched releases, both with append-only action history.

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
- Durable scheduled deadline processing plus startup recovery of expired waits.
- Historical backfill preview and explicit multi-episode confirmation.
- Same-group, same-episode higher revisions create append-only upgrade
  decisions.
- Every committed decision emits `DecisionCommitted.v1` and
  `DownloadRequested.v1`.

### Downloads

- Encrypted qBittorrent Web API endpoint, username, and password configuration.
- Connectivity validation and version reporting without exposing credentials.
- DB-first task planning, submission attempts, and immutable idempotency keys.
- Query-by-info-hash before every add or retry, including timeout-after-success
  recovery without duplicate submission.
- Magnet and uploaded `.torrent` submission with subscription save path plus
  configured category and tags.
- Durable periodic reconciliation and an explicit manual sync command.
- qBittorrent-derived progress, pause, completion, path, category, and tag
  state; connection failures preserve the last observation and mark it stale.
- Confirmed external deletion becomes terminal until an administrator
  explicitly retries the task.
- Interrupted submissions recover at startup and query by hash before another
  add.
- Revision replacement cancels only incomplete old tasks with
  `deleteFiles=false`; completed old files remain untouched.

### Product hardening and delivery

- First-run administrator setup, salted scrypt password storage, opaque sessions,
  password-reset CLI, and explicit logout.
- HTTP-only session cookie plus readable CSRF cookie; every authenticated mutation
  must echo the CSRF value in `X-CSRF-Token`.
- In-app notifications derived from durable integration events without changing
  any selection, feed, or download outcome.
- Optional encrypted generic JSON Webhook configuration, idempotency key, delivery
  attempts, bounded retry, and stale-attempt recovery.
- Portable `.backup` archives containing a consistent SQLite snapshot, manifest,
  and the matching encryption master key.
- Manual and daily scheduled backup creation, count-based retention, restore
  validation, restart-safe staging, and automatic pre-restore backup.
- React setup/login gate plus system view for notifications, Webhook settings,
  backup download, restore upload, and logout.
- Multi-stage Docker build, non-root Python runtime, one Uvicorn worker, readiness
  health check, and a named Compose data volume.

### Interface

- Responsive dashboard and feed management.
- Feed test, refresh, history, and normalized entry views.
- Raw Release identity library.
- Episode candidate groups showing every subtitle-group version and its parsed
  attributes.
- Anime creation/import, subscription creation and lifecycle controls, backfill
  preview, waiting-state summary, and immutable decision history.
- In-page selection flow showing hard filters, comparison order, wait behavior,
  revision upgrades, and the explicit boundary of current manual operations.
- qBittorrent configuration, connectivity status, download progress, external
  state, manual reconciliation, and explicit retry controls.
- Generated TypeScript API types from the checked OpenAPI contract.
- Operations view for dependency state, durable jobs, execution runs, failed
  work, and audit history.
- Dashboard failed-work summary plus candidate confirmation and release-mapping
  controls.

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

### UI-001: The interface documents the live policy boundary

**Choice:** The interface presents the automatic selection stages in execution
order. It exposes backfill confirmation, candidate confirmation, and unmatched
release mapping while continuing to mark per-episode override and decision
replacement as unavailable.

**Reason:** Operators must be able to predict automatic behavior without
mistaking a visible confirmation state for an available manual command.

### DL-001: qBittorrent configuration is module-owned and encrypted

**Choice:** `downloads` stores one qBittorrent Web API configuration. Endpoint,
username, and password are encrypted with field-specific authenticated
encryption purposes; only a redacted endpoint and username return through the
API.

**Reason:** Downloader credentials must not leak into settings files, logs,
task rows, or browser responses while still remaining editable at runtime.

### DL-002: Every external effect starts with a durable local task

**Choice:** Consuming `DownloadRequested.v1` creates one task per decision with
`download-request:{decision_id}:{release_id}:1` as its immutable idempotency key.
The network call happens only after that transaction commits.

**Reason:** A crash can lose a response, but it cannot lose the reason for the
operation or create another local request for the same decision.

### DL-003: Every add and retry queries by info hash first

**Choice:** The adapter authenticates and queries qBittorrent before every add.
If the torrent already exists, the local task links to that observation without
submitting again.

**Reason:** This closes the timeout-after-success window that a database-only
idempotency key cannot close across an external API boundary.

### DL-004: qBittorrent owns runtime state

**Choice:** Reconciliation mirrors progress, pause, completion, save path,
category, and tags. A network or authentication failure retains the last known
state and marks it stale rather than interpreting an empty observation.

**Reason:** Selection history belongs to this application, while actual torrent
execution belongs to qBittorrent and may be changed there deliberately.

### DL-005: External deletion is terminal by default

**Choice:** A previously observed torrent that disappears becomes
`externally_removed` and leaves the automatic work queue. Only the explicit
retry command clears that boundary.

**Reason:** Re-adding a torrent deleted by the administrator would fight the
source of truth and could create an endless add/delete loop.

### DL-006: Transient failures retry; interrupted effects reconcile first

**Choice:** Submission failures classified as transient use bounded backoff.
Tasks left in `submitting` or `canceling` recover after a stale interval; startup
forces recovery immediately, then queries by hash before making an external
change.

**Reason:** Restarts and temporary qBittorrent downtime must be recoverable
without treating an uncertain response as proof of failure.

### DL-007: Revision replacement never deletes completed files

**Choice:** An upgrade decision emits an explicit cancellation request for the
previous decision. The new submission waits until that step resolves. An
incomplete old torrent is removed with `deleteFiles=false`; a completed old
torrent is only marked superseded.

**Reason:** Replacement is a visible, retryable saga, and downloaded media is
never removed as a side effect of choosing V2 or V3.

### OPS-001: One durable scheduler replaces module-local polling loops

**Choice:** `feed.refresh`, `events.dispatch`, `selection.process_due`, and
`downloads.process_cycle` run through one generic scheduler with database
leases. The composition layer maps job kinds to public module commands.

**Reason:** Restart and retry behavior is observable in one place, while each
business module remains independently readable and owns its own state.

### OPS-002: Business deadlines remain authoritative

**Choice:** Feed `next_fetch_at` may replace the queued job due time during
synchronization. Generic periodic jobs retain the next due time written by the
worker. Selection fallback deadlines remain in selection tables and are queried
by the scheduled command.

**Reason:** Rebuilding the scheduler queue cannot lose or invent a business
deadline, and manual feed refresh cannot trigger an immediate duplicate fetch.

### OPS-003: Claims and executions are separate records

**Choice:** The current job row stores the next intent and lease. Every claim
creates an append-only run row with worker, attempt, outcome, error class, and
timing. Expired running rows become `recovered` before the job is reclaimed.

**Reason:** A mutable queue row is sufficient for execution but insufficient for
diagnosis or proof of restart recovery.

### OPS-004: Optional dependencies do not gate readiness

**Choice:** Readiness continues to verify the local database. RSS aggregate
health, Bangumi on-demand state, qBittorrent observations, and scheduler
heartbeats are returned as administrator diagnostics.

**Reason:** A metadata or downloader outage should be visible without causing
the local application process to fail readiness and restart repeatedly.

### OPS-005: Failed-work summaries use public module queries

**Choice:** The composition-level diagnostics adapter aggregates feed failures,
unmatched releases, download failures, and scheduler errors through public API
DTOs. `operations` does not query another module's tables.

**Reason:** The dashboard needs one actionable queue, but that read requirement
must not erode table ownership or create hidden cross-module write logic.

### REC-004: Manual recognition actions preserve parser evidence

**Choice:** Confirming a medium-confidence candidate promotes that candidate for
re-evaluation. Mapping a low-confidence release requires structured series and
episode fields and is allowed only while no candidate exists. Both actions are
stored separately and emit a new candidate-evaluation event.

**Reason:** Administrators can unblock real releases without silently rewriting
what parser v1 originally observed or invalidating existing decisions.

### SEC-001: Setup is a database compare-and-create operation

**Choice:** A clean database exposes only setup, login, status, and health. The
first valid setup request creates the fixed administrator account and an
authenticated session; later setup requests conflict.

**Reason:** A container image does not need a baked-in password or environment
secret, and setup state remains part of the restored application state.

### SEC-002: Sessions are opaque and revocable

**Choice:** Passwords use salted scrypt. Session and CSRF tokens use independent
random values, and only SHA-256 hashes are stored. Password reset revokes every
session.

**Reason:** Database disclosure does not reveal reusable browser tokens, while a
single-user operator retains a direct recovery command.

### SEC-003: Mutations use double-submit CSRF validation

**Choice:** The session cookie is HTTP-only and SameSite=Lax. A separate readable
SameSite cookie must match `X-CSRF-Token` and the session-bound stored hash for
every authenticated non-safe method.

**Reason:** Browser forms cannot create authenticated mutations, and the frontend
does not need access to the session credential.

### NOTIFY-001: Notifications are downstream facts only

**Choice:** `notifications` consumes versioned integration events after the
originating transaction. A notification or Webhook failure never changes feed
retry, recognition, selection, or download state.

**Reason:** Operator visibility must not become a second business-decision path.

### NOTIFY-002: Webhook delivery has its own durable retry state

**Choice:** One channel attempt is created per notification when Webhook delivery
is enabled. The notification ID is the external idempotency key; transient network,
429, and 5xx failures retry with bounded exponential delay for at most eight
attempts. Interrupted deliveries become retryable after five minutes.

**Reason:** External delivery is recoverable across restarts without replaying the
originating action or issuing an unbounded request stream.

### NOTIFY-003: The external contract is generic JSON

**Choice:** The first adapter sends a stable JSON envelope with kind, level,
message, entity, time, and optional encrypted bearer token. Provider-specific
Slack, Feishu, or Telegram formatting is not embedded in the core module.

**Reason:** A neutral contract works with automation relays now and leaves each
provider adapter independently extractable later.

### BACKUP-001: A backup includes encrypted data and its key

**Choice:** Each versioned ZIP archive contains an SQLite online-backup snapshot,
manifest, and the exact 32-byte master key. Archives are not encrypted by the app
and are documented as credentials.

**Reason:** Copying only SQLite would restore ciphertext that a clean container
cannot decrypt. Operator-controlled storage is a clearer boundary than inventing
a second key-management password in the first release.

### BACKUP-002: Live restore stages; startup applies

**Choice:** Upload validates the archive, SQLite integrity, application schema,
and master key, then stages files under the data volume. The next startup creates
a pre-restore archive, atomically replaces database and key, and runs migrations.

**Reason:** Replacing a database while services and scheduler sessions are live is
not a safe recovery primitive. A required restart makes the cutover explicit and
keeps every module on one database generation.

### BACKUP-003: Retention is count-based and scheduler-owned

**Choice:** The generic scheduler creates one backup every 24 hours by default and
keeps the newest 14 archives. Manual and pre-restore archives participate in the
same configurable count.

**Reason:** Count retention is predictable on small NAS volumes and does not add a
second timer loop or a hidden file owner.

### UI-002: Security and recovery live behind one application gate

**Choice:** The React root resolves authentication before mounting any product
route. One system view owns Webhook configuration, messages, backups, restore,
and logout; the shared API client attaches CSRF headers to all mutations. A
successful logout clears the in-memory query cache and reloads the document.

**Reason:** Feature pages remain unaware of session mechanics, and operator tasks
have one discoverable surface on desktop and mobile. Reloading at the logout
boundary removes protected projections and prevents stale credential form state
from surviving the authenticated application.

### PKG-001: Production is one non-root process and one data volume

**Choice:** A multi-stage image builds React assets and runs Python as an
unprivileged user with one Uvicorn worker. Compose mounts `/data`, publishes one
port, and probes database readiness.

**Reason:** This matches SQLite's single-writer workload, keeps install state in
one portable volume, and avoids process-manager behavior that could duplicate the
embedded scheduler.

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
- Provisional recognition grouping remains visible before a catalog identity is
  linked through a subscription alias snapshot.
- Manual mapping is limited to releases without a candidate; parser re-run and
  reassignment of already-decided candidates are not implemented.
- Rules are currently stored per subscription; named reusable global preference
  profiles are not implemented.
- Per-episode manual candidate selection and replacement of an existing decision
  are not implemented.
- Only qBittorrent Web API v2 is implemented; there is no alternate downloader
  adapter or app-side pause/resume command.
- qBittorrent category and tags are defaults captured when the task is planned;
  later external edits are reflected rather than overwritten.
- The service does not terminate TLS; secure-cookie mode requires an HTTPS reverse
  proxy with one consistent browser origin.
- Backup archives are portable but unencrypted and contain the master key.
- Restore requires an explicit service restart after upload.
- The Webhook adapter emits generic JSON; provider-specific message formats are
  not implemented.

## 6. Next Planned Slice

The next coherent delivery unit is `release acceptance + remaining product views`:

1. Add an airing calendar and per-anime episode history without allowing schedule
   metadata to trigger downloads.
2. Add explicit per-episode candidate selection and controlled replacement of an
   existing decision.
3. Run disposable Compose acceptance for first setup, backup into a clean volume,
   restore, upgrade, and rollback.
4. Add multi-architecture image CI and published image provenance.
5. Start and record the seven-day real-feed soak required by `DESIGN.md`; this is
   elapsed-time validation and is not claimed by the current automated suite.
