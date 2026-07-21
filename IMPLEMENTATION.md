# Anime RSS Service Implementation Record

Status: Living implementation and decision record

Updated: 2026-07-22

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
- Hourly `schedule.sync` projection refresh with durable expected-episode rows.

### Recognition

- Pure deterministic parser identified by `title-rules.v2`.
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
- One versioned global preference profile with explicit per-subscription overrides.
- Imported or manually editable weekly airing date, time, timezone, and episode
  count metadata.

### Schedule and missing episodes

- One independently readable `schedule` module that consumes catalog,
  subscription, selection, and instance-setting public query DTOs only.
- Durable expected episodes generated from the first air date at seven-day
  intervals, bounded by the known episode count and current subscription epoch.
- Versioned per-episode overrides for postponements, double episodes, specials,
  cancellations, split-cour dates, and future provider episode data.
- UTC schedule storage with calendar rendering in the administrator-selected
  IANA timezone.
- Today plus seven-day calendar and per-anime expected-episode history.
- `scheduled`, `acquired`, and `missing` states derived from selection facts;
  an acceptable fallback prevents a missing classification.
- One-time `EpisodeMissing.v1` emission after the configurable grace period.
- Schedule synchronization cannot emit `DownloadRequested.v1` or create a
  synthetic candidate.

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
- Scaled integer episode spans with at most three decimal places, append-only
  per-decision coverage, full-coverage suppression, and a partial-overlap manual gate.
- Same-group, same-episode higher revisions create append-only upgrade
  decisions.
- Per-episode manual selection, replacement, rejection, reset, and acquired-elsewhere
  actions with append-only action history.
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

- First-run administrator setup, Argon2id password storage with login-time legacy
  scrypt migration, opaque sessions,
  password-reset CLI, and explicit logout.
- HTTP-only session cookie plus readable CSRF cookie; every authenticated mutation
  must echo the CSRF value in `X-CSRF-Token`.
- Trusted Host, same-origin browser-write, Fetch Metadata, and bounded sensitive
  endpoint rate-limit enforcement.
- One structured API error envelope with machine code, message, details, and the
  request correlation ID.
- Durable 24-hour mutation idempotency, mandatory optimistic preconditions for
  versioned resources, and opaque cursor pagination for growing list endpoints.
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
- Versioned instance settings for timezone, interface language, missing-episode
  grace, and guided-setup progress.
- Multi-stage Docker build, non-root Python runtime, one Uvicorn worker, readiness
  health check, and a named Compose data volume.

### Interface

- Responsive dashboard and feed management.
- Feed test, refresh, history, and normalized entry views.
- Raw Release identity library with explicit manual BTIH download submission and
  existing-task status.
- Episode candidate groups showing every subtitle-group version and its parsed
  attributes.
- Anime creation/import, subscription creation and lifecycle controls, backfill
  preview, waiting-state summary, and immutable decision history.
- Legal completed/archive lifecycle menus plus separate current and archived views.
- In-page selection flow showing hard filters, comparison order, wait behavior,
  revision upgrades, and the explicit boundary of current manual operations.
- qBittorrent configuration, connectivity status, download progress, external
  state, manual reconciliation, and explicit retry controls.
- Generated TypeScript API types from the checked OpenAPI contract.
- Operations view for dependency state, durable jobs, execution runs, failed
  work, and audit history.
- Dashboard failed-work summary plus candidate confirmation and release-mapping
  controls.
- Eight-day airing calendar, missing-episode warning list, editable airing
  metadata and episode overrides, per-anime episode history, and instance locale
  settings.

## 3. Decision Log

### ING-001: Feed URL uniqueness uses a key-derived blind index

**Choice:** Exact configured endpoint bytes are indexed with purpose-bound HMAC
under the instance master key. The index is unique and API create/update map a
collision to HTTP 409. During upgrade, the first copy of an existing URL claims
the index; already duplicated rows remain intact but cannot be multiplied.

**Reason:** Private token URLs need deterministic duplicate prevention without
storing plaintext endpoints or an unkeyed digest that can be guessed offline.

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

### SUB-003: Global preferences are live; overrides are explicit

**Choice:** A single versioned default profile is resolved when a subscription is
read for selection. New subscriptions inherit it unless they explicitly store an
override. Existing subscriptions created before migration remain overrides so an
upgrade cannot silently change their behavior.

**Reason:** One editable default makes new subscriptions cheap while the explicit
inheritance flag preserves reviewable ownership and lets each decision snapshot
the exact effective rules.

### SUB-004: Lifecycle commands expose only legal state transitions

**Choice:** The subscription row uses an action menu derived from the backend
state machine. Following and paused subscriptions can complete or archive;
completed subscriptions can resume or archive; archived subscriptions restore to
paused before they can follow again. Archived rows live in a separate view.

**Reason:** A binary pause toggle cannot represent completed and archived
semantics and previously attempted the illegal `archived -> following` transition.
The explicit menu keeps operator intent aligned with selection behavior: completed
allows same-span same-group upgrades only, while archived stops all automation.

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

### SEL-008: Manual episode commands append; they do not rewrite

**Choice:** Selection, replacement, rejection, reset, and acquired-elsewhere are
stored as immutable manual actions. Replacement creates a new decision and emits
the same cancellation intent used by revision upgrades. Reset reopens the local
slot but never deletes or pauses an existing downloader task.

**Reason:** The operator can correct an episode without losing the previous
rationale. Download idempotency and qBittorrent reconciliation remain responsible
for preventing duplicate external submissions.

### SEL-009: Range releases are atomic decisions with per-episode coverage

**Choice:** Episode values use thousandths in coverage comparisons. A range such
as `1-2` remains one Candidate, one Decision, and one DownloadTask, while the
Decision appends coverage facts for `1` and `2`. A later single episode whose
coverage is complete is ignored automatically. A range that only partly overlaps
acquired episodes enters `needs_confirmation`; backfill cannot select it, while an
explicit manual candidate selection may proceed. Coverage from Decisions and
`acquired_elsewhere` actions is historical and survives a slot reset. Migration
`0015` backfills both sources.

**Reason:** Similar titles are not duplicate release identity, but already acquired
episode content is a separate selection invariant. Keeping the range atomic avoids
inventing multiple downloader tasks, while the coverage join prevents ordinary
single releases from downloading the same content again. Partial overlap is a real
tradeoff and therefore cannot be guessed by automation.

### UI-001: The interface documents the live policy boundary

**Choice:** The interface presents the automatic selection stages in execution
order. It exposes backfill confirmation, candidate confirmation, unmatched
release mapping, global preferences, and per-episode manual controls.

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

The supported application contract is qBittorrent `>=4.6.0,<6.0.0` with Web API
major version 2. Connection tests return both versions and reject malformed,
older, or unknown-major responses. The real adapter acceptance runs fixed 4.6.7
and 5.0.4 containers through authenticate, add, hash lookup, and incomplete
delete-without-files operations.

### DL-005: External deletion is terminal by default

**Choice:** A previously observed torrent becomes `externally_removed` only after
two consecutive successful hash lookups return empty. The first miss remains in
its prior state with `external_removal_unconfirmed`; a lookup failure or present
torrent resets the persisted counter. Confirmed removal leaves the automatic work
queue, and only the explicit retry command clears that boundary.

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
torrent is only marked superseded. The replacement readiness check requires the
predecessor's persisted `superseded_at`; integration evidence asserts that the
old hash delete call occurs before the replacement hash add call.

**Reason:** Replacement is a visible, retryable saga, and downloaded media is
never removed as a side effect of choosing V2 or V3.

### DL-008: Download defaults are captured when a task is planned

**Choice:** qBittorrent configuration owns an optional default save path,
category, and tags. A subscription save path overrides the instance default;
otherwise the planned task records the instance defaults as an intent snapshot.

**Reason:** Setup needs one useful default without forcing every subscription to
repeat paths, while persisted tasks must not drift when configuration changes.

### DL-009: Manual Release downloads are a second explicit task origin

**Choice:** Migration `0016` gives every DownloadTask an immutable
`origin_kind`. Automatic tasks remain `selection_decision` and require both a
Decision and Subscription; a `manual_release` task requires both references to
be absent. The database enforces this distinction. `POST
/api/v1/downloads/releases/{release_id}/submit` reuses any task already linked to
the Release or inserts one `manual-release:{release_id}:1` intent before the
worker performs network I/O.

**Reason:** Unsupported title/content recognition may have no Candidate,
Subscription, or episode identity, so manufacturing a Decision would corrupt
selection history. A direct qBittorrent call would instead bypass durable retry
and audit behavior. The explicit second origin preserves both boundaries while
sharing submission and reconciliation. Pure BTMH releases remain unavailable
until the downloader can reconcile v2 identities reliably; manual intent does
not weaken that safety boundary. DownloadTask references also join the retention
protection set so an old manually submitted Release cannot be pruned underneath
its execution history.

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

### REC-009: Manual recognition actions preserve parser and decision evidence

**Choice:** Confirming a medium-confidence candidate promotes that candidate for
re-evaluation. Mapping any release requires structured series and episode fields.
If an active candidate exists, a new candidate supersedes it and both remain in
history. Undecided selection slots reopen; decided slots keep their decision and
candidate snapshot while a correction action is appended. The new candidate is
then evaluated normally.

**Reason:** Administrators can unblock real releases without silently rewriting
what parser v1 originally observed, destroying prior candidate evidence, or
mutating an existing selection decision after external work may have occurred.

### REC-010: Parser re-runs append evidence and adopt only safe changes

**Choice:** `POST /api/v1/recognition/releases/{release_id}/rerun` resolves the
source observation behind the active candidate and always appends a new immutable
attempt marked `explicit_rerun`. Initial event-driven recognition remains
concurrency-safe through a partial unique index for `trigger = 'initial'`, while
same-version explicit runs are allowed. An unchanged result retains the active
candidate. A changed, structurally complete medium/high-confidence result creates
a new Candidate that supersedes the previous one and is evaluated normally. A
low-confidence or incomplete result is recorded but cannot remove a valid active
Candidate. Existing Decisions are never rewritten.

**Reason:** Parser upgrades and operator diagnostics need replayable evidence,
but re-running deterministic code must not duplicate candidates or let a parser
regression destroy a known-good mapping. Keeping attempt, Candidate, and Decision
lifecycles separate preserves both retry safety and historical explanation.

### REC-011: Parser fixtures are a versioned executable contract

**Choice:** `parser-fixtures/title-rules.v2.json` defines a reviewable matrix that
expands to 320 complete output snapshots plus focused malformed cases. A separate
deterministic Unicode gate exercises 512 arbitrary strings and NFKC-equivalent
forms. Rule v2 bounds post-casefold series keys to 300 characters and accepts
revision suffixes only from `V1` through `V999`.

**Reason:** A list of hand-picked happy paths does not protect parser behavior
across subtitle groups, localized titles, episode syntaxes, and media tags.
Casefold can expand Unicode text, and an unbounded numeric revision can exceed
database integer limits. Versioned data makes behavior changes reviewable while
property invariants protect termination, determinism, and persistence bounds.

### SEC-001: Setup is a database compare-and-create operation

**Choice:** A clean database exposes only setup, login, status, and health. The
first valid setup request creates the fixed administrator account and an
authenticated session; later setup requests conflict.

**Reason:** A container image does not need a baked-in password or environment
secret, and setup state remains part of the restored application state.

### SEC-002: Sessions are opaque and revocable

**Choice:** New and reset passwords use Argon2id with 64 MiB memory, time cost 3,
parallelism 1, a 32-byte hash, and a 16-byte salt. The prior fixed-parameter
`scrypt-v1` format remains verification-only: a successful login replaces it in
the same transaction, preserves `password_changed_at`, and records
`system.password_hash_upgraded`. Unknown, malformed, or altered legacy parameter
sets fail as invalid credentials. Session and CSRF tokens use independent random
values, and only SHA-256 hashes are stored. Password reset revokes every session.

**Reason:** Database disclosure does not reveal reusable browser tokens, while a
single-user operator retains a direct recovery command.

### SEC-003: Mutations use double-submit CSRF validation

**Choice:** The session cookie is HTTP-only and SameSite=Lax. A separate readable
SameSite cookie must match `X-CSRF-Token` and the session-bound stored hash for
every authenticated non-safe method.

**Reason:** Browser forms cannot create authenticated mutations, and the frontend
does not need access to the session credential.

### SEC-004: Browser authority is explicit and rate limits are local

**Choice:** Every request validates `Host`. IP literals, `localhost`, and configured
exact or wildcard hostnames are accepted. Unsafe browser requests with `Origin`
must match either the request authority or an explicitly configured exact HTTP(S)
origin; `Sec-Fetch-Site: cross-site` is rejected. This supports an HTTPS reverse
proxy without trusting `X-Forwarded-*` headers or silently accepting arbitrary DNS
names.

Setup and login use a sliding window of five attempts per five minutes,
isolated by path and direct client address. Feed, qBittorrent, and Webhook connection
tests each allow ten attempts per minute. Limits are configurable, process-local,
thread-safe, and bounded to 10,000 client/path buckets. `Retry-After` accompanies
429 responses. Forwarded client addresses are deliberately ignored, so a reverse
proxy shares one conservative bucket.

**Reason:** Double-submit CSRF alone does not prevent DNS rebinding, hostile browser
origins, password guessing, or expensive connection-test amplification. The V1
single-process deployment does not need distributed rate-limit state, and trusting
forwarded headers without an explicit proxy trust chain would let clients forge
their identity.

### API-001: Successful mutations can be replayed for 24 hours

**Choice:** Every API mutation may carry `Idempotency-Key`. Migration `0017`
stores a SHA-256 key digest, a method/path/query/body request digest, and the
successful response in SQLite for 24 hours. An identical request replays the
stored response, a different request using the same key returns 409, and a
concurrent in-progress request returns 409 with `Retry-After`. Failed responses
release the claim so corrected requests can retry. The browser client generates a
UUID for every unsafe request.

Authentication setup/login/logout are excluded because replaying session cookies
would be unsafe. Restore staging is excluded because buffering and retaining a
large backup upload in generic middleware is the wrong ownership boundary.

**Reason:** A client that loses a success response can repeat the command without
creating a second business action, while durable storage preserves this guarantee
across process restarts.

### API-002: Mutable resources require explicit versions

**Choice:** Versioned `PUT`, `PATCH`, and `DELETE` operations require `If-Match`;
creating a singleton configuration or episode override uses version `0`. Missing
preconditions return 428 and stale versions return 409. Catalog Anime now has its
own migrated version for alias and airing-schedule changes; feed deletion consumes
the Feed version. Idempotent writes that do not change an alias or schedule retain
the current version.

**Reason:** The web interface and external clients cannot silently overwrite a
newer administrator change, and a version continues to mean an actual resource
transition rather than an API call count.

### API-003: Pagination preserves existing array responses

**Choice:** Growing list endpoints accept a bounded `limit` and opaque offset
cursor. Responses remain JSON arrays for frontend compatibility and expose
`X-Next-Cursor` plus `X-Page-Limit`; the checked OpenAPI contract declares those
headers. Page size is capped at 200 and cursor offset at 10,000.

**Tradeoff:** This is not a database snapshot. Concurrent insertions or removals
between page requests may move offsets. The cursor contract guarantees ordered,
non-overlapping traversal only while the underlying ordered result is stable; a
future high-volume deployment should replace module queries with keyset cursors
without changing the response headers.

### API-004: Errors and correlation use one public envelope

**Choice:** HTTP, validation, authentication, CSRF, precondition, idempotency, and
unexpected failures return `code`, `message`, optional `details`, and
`correlation_id`. The legacy `detail` message remains during the current client
transition. Every response also returns `X-Correlation-ID`. OpenAPI advertises the
error model, mutation idempotency header, preconditions, and pagination headers;
the generated TypeScript schema is checked into the repository.

**Reason:** Operators can connect browser failures to JSON logs and durable audit
history, while clients can branch on a stable code rather than translated text.

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
keeps the newest seven archives. Manual and pre-restore archives participate in the
same configurable count.

**Reason:** Count retention is predictable on small NAS volumes and does not add a
second timer loop or a hidden file owner.

### BACKUP-004: Restore and migration share one fail-closed startup lock

**Choice:** Startup and the migration CLI take an advisory file lock adjacent to
the SQLite database before restore inspection or Alembic work. Lock acquisition
times out after 60 seconds by default and process exit releases ownership. Inside
the lock, the service compares current and target Alembic heads. A pending
migration of an existing versioned database creates a consistent online archive
with reason `pre-migration`; only a successful backup permits migration. Clean
installs, current schemas, and the second process after a concurrent migration do
not create an archive. A migration failure leaves the archive in normal retention.

**Reason:** A database row cannot serialize work that starts before the schema is
known, and a marker file without an OS lock can become permanently stale after a
crash. Check, snapshot, and upgrade must be one critical section so overlapping
container generations cannot both migrate or replace the same SQLite file.

### OPS-004: Correlation context is persisted across every execution boundary

**Choice:** HTTP requests accept only canonical UUID correlation IDs and generate
one otherwise. Background jobs create a new correlation ID and use the durable job
ID as causation. Integration events persist both IDs; dispatch restores the
correlation and makes the event ID the next causation ID. Audit writes inherit the
active correlation automatically.

**Reason:** One identifier now follows feed fetch, release parsing, candidate
selection, task planning, and external submission without coupling domain APIs to
HTTP request objects or logger arguments.

### OPS-005: JSON logs and diagnostic history are bounded independently

**Choice:** The process writes structured JSON to stdout and
`data/logs/application.jsonl`; the file rotates at UTC midnight and keeps 14 days
by default. Probe requests are excluded. A central formatter redacts URL query
values and sensitive fields, including messages emitted by dependencies.

**Tradeoff:** Container-runtime stdout retention remains an operator concern. The
application-owned file provides a predictable local diagnostic window without
trying to configure Docker or NAS logging policy.

### RET-001: Each module applies retention to its owned records

**Choice:** A daily `system.retention` job asks selection and recognition for
release IDs that must survive, then invokes public cleanup commands. Subscription
evaluations, decisions, and manual actions protect their releases. Recognition
manual corrections protect fingerprints permanently. Other unmatched releases
and unresolved feed entries expire after 90 days; redacted fetch failures expire
after seven days. Delivered integration events and completed job runs expire after
90 days.

**Reason:** `operations` owns timing and evidence, but never deletes another
module's tables. This preserves module extraction boundaries and prevents cleanup
from rewriting decisions or deleting corrected fingerprints.

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

### PKG-002: Release images are reproducible across lifecycle transitions

**Choice:** GitHub Actions publishes `linux/amd64` and `linux/arm64` images to
GHCR for `master`, version tags, and commit SHAs. BuildKit emits maximum-mode
provenance and an SBOM, and GitHub attaches a registry-backed build provenance
attestation. Compose accepts an `ANIME_RSS_IMAGE` override while retaining the
local-build default.

The `make acceptance-compose` harness selects the newest historical commit before
the current migration, builds baseline and current images, and exercises setup,
operator backup, in-place upgrade, clean-volume restore, and backup-based rollback.
Every transition starts the full service, logs in again, and verifies settings,
subscription, and feed projections. Test projects and volumes are uniquely named
and removed on both success and failure.

**Reason:** Schema migration, encryption-key portability, and rollback behavior
must be proven at the container boundary. Unit-level backup tests cannot detect
image entrypoint, volume ownership, static asset, or Compose wiring regressions.

**Tradeoff:** The local acceptance harness validates one native architecture.
Cross-architecture builds, registry publication, SBOM attachment, and attestation
are verified only when the GitHub Actions workflow runs.

### ACC-001: Live acceptance is an immutable, redacted evidence window

**Choice:** The `anime-rss acceptance` CLI exposes `preflight`, `start`, `status`,
and `report` commands. Preflight requires completed setup, two healthy feeds, two
following Bangumi-backed anime, a successfully tested qBittorrent connection,
and a healthy scheduler. `start` writes one immutable timestamp under
`/data/acceptance`; repeated starts preserve the original boundary.

Status and report use a disposable, read-only cross-module SQLite projection.
They aggregate feed refreshes, cross-feed releases, recognition and manual actions,
decisions, downloader attempts, job failures, duplicate task identities, and lost
decision references. They never read endpoint ciphertext, payload ciphertext,
credentials, raw magnet links, or private URL fields.

**Reason:** Existing durable histories already contain the evidence needed for a
seven-day run. A read-only projection avoids a second monitoring write model and
cannot alter Candidate, Decision, DownloadTask, or user history. The explicit
start marker prevents a failed or partial run from being silently restarted to
produce a favorable window.

**Tradeoff:** Counts can detect duplication and state-integrity failures but cannot
prove that an anime title was semantically matched correctly. Final approval
requires human review of the mapped episodes. The marker survives restarts on the
same data volume but is intentionally outside operator backup archives; a clean
restore restarts the seven-day clock.

### SCH-001: Schedule is a downstream projection, never an acquisition source

**Choice:** `schedule` reads catalog metadata, subscriptions, selection slots,
decisions, and instance settings through public APIs. It owns expected-episode
rows and may emit only `EpisodeMissing.v1`.

**Reason:** A broadcast plan is advisory and can be incomplete or wrong. Keeping
it outside recognition and selection makes it structurally impossible for a
calendar row to create a downloader task.

### SCH-002: Weekly expectations are anchored to the first air date

**Choice:** The stored first air date and source-local airtime define episode 1;
subsequent numeric episodes are seven days apart, stop at the known episode
count, and begin no earlier than the subscription activation epoch. Bangumi
times use `Asia/Tokyo`; manual schedules require an explicit IANA timezone.

**Tradeoff:** The generator does not guess irregular broadcasts. Corrections are
explicit episode-level facts supplied manually or by a future provider adapter.

### SCH-003: Missing means no acquisition and no acceptable fallback

**Choice:** A decision or `acquired_elsewhere` state marks the expected episode
acquired. A waiting fallback is acceptable and suppresses a warning. Otherwise a
following subscription becomes missing after the instance grace period, once.

**Reason:** The alert should identify absent usable releases, not pressure a
still-running selection wait or repeatedly notify on every scheduler cycle.

### SCH-004: Irregular broadcasts are versioned episode-level overrides

**Choice:** `schedule_episode_overrides` owns one row per anime and episode key.
An override may replace the timezone-aware expected time, add an arbitrary safe
key such as `SP1` or `OVA1`, or mark the episode cancelled. Two keys may share a
timestamp, which represents a double-episode broadcast. `source` is `manual` in
the interface and can identify a future provider without changing the merge
contract. Split cours are represented by explicit rows for their resumed dates.

The synchronizer builds the numeric weekly baseline, overlays these rows, and
then reconciles the durable projection. Cancelled keys and keys moved outside
the activation-to-eight-day horizon make an existing expected row `inactive`
rather than deleting it. Deleting an override restores the weekly baseline on
the next sync. A moved or reactivated row clears its stale missing-notification
claim and is evaluated once at the corrected time.

Mutations are idempotent when values do not change, accept `If-Match` optimistic
versions, and append create, update, and delete audit events. The merge can only
emit `EpisodeMissing.v1`; tests assert that overrides cannot create Candidate,
Decision, or DownloadTask records.

**Reason:** Irregular schedules need a durable correction layer, but they remain
advisory broadcast facts. Keeping them inside `schedule` preserves the boundary
that only recognition and selection can cause acquisition work, while inactive
history makes corrections and later baseline restoration inspectable.

### SYS-001: Locale and missing threshold are versioned instance settings

**Choice:** Timezone, interface language, grace hours, completed setup steps, and
setup completion live in one optimistic-lock settings row. Stored timestamps
remain UTC; only query projections convert them.

**Reason:** One instance-owned source keeps UI rendering and background missing
evaluation consistent while leaving setup progress durable across restarts.

### SYS-002: Guided setup composes module APIs with fixed durable steps

**Choice:** The eight step IDs are fixed and ordered. Administrator creation
records step one in the same transaction; later steps call their owning module's
normal API and then idempotently record completion. The final candidate step only
uses the read-only backfill preview query. Existing installations with an
administrator are marked complete by migration `0010`; clean installations are
not seeded.

**Reason:** The wizard remains a resumable application workflow rather than a
second implementation of feed, download, catalog, subscription, or selection
behavior. Upgrades do not force established instances through a new first-run
flow.

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

- Provisional recognition grouping remains visible before a catalog identity is
  linked through a subscription alias snapshot.
- Only qBittorrent Web API v2 is implemented; there is no alternate downloader
  adapter or app-side pause/resume command.
- qBittorrent save path, category, and tags are defaults captured when the task
  is planned; later external edits are reflected rather than overwritten.
- The service does not terminate TLS; secure-cookie mode requires an HTTPS reverse
  proxy with one consistent browser origin.
- Backup archives are portable but unencrypted and contain the master key.
- Restore requires an explicit service restart after upload.
- The Webhook adapter emits generic JSON; provider-specific message formats are
  not implemented.

## 6. Remaining Plan Audit

The earlier record incorrectly reduced remaining work to live-feed acceptance.
The original implementation plan is broader. This matrix is the current source of
truth; a row is complete only when code and proportionate evidence both exist.

| Area | Current evidence | Remaining work |
|---|---|---|
| Episode span coverage | `0015`, domain/integration/migration/frontend tests | Complete |
| Subscription lifecycle | All legal commands, archived view, revision-only completed behavior, and archived-stop integration coverage | Complete |
| Unsupported release handling | `0016`, durable manual task origin, idempotent API, audit evidence, release-page command, backend/frontend tests | Complete |
| Parser regression contract | `title-rules.v2`, 320-case golden matrix, focused malformed cases, and 512-case Unicode/property gates | Complete |
| HTTP consistency | `0017`, durable replay/conflict tests, version/precondition tests, cursor traversal tests, structured error tests, and checked OpenAPI/TypeScript contract | Complete |
| Browser-origin security | Host/IP and proxy-origin policy, Fetch Metadata rejection, bounded per-client setup/login and connection-test limits, deployment documentation, and security integration tests | Complete |
| Password KDF | Argon2id setup/reset, fixed parameters, successful-login legacy scrypt migration, timestamp preservation, audit event, malformed-hash rejection, and integration coverage | Complete |
| Startup migration safety | OS-released lock spans restore/check/backup/upgrade; versioned pending schemas receive a validated online `pre-migration` archive; clean/current/failure/contention paths have integration coverage; Compose lifecycle passes | Complete |
| qBittorrent contract | Explicit 4.6/5.x plus Web API 2 policy; fixed real 4.6.7 and 5.0.4 container acceptance; `0018` persisted two-success removal confirmation; failure reset; delete-before-replacement ordering; migration and integration coverage | Complete |
| Stable engineering gates | lint, typecheck, unit/integration, OpenAPI generation, Compose acceptance | Add doctor, checked OpenAPI drift, security scan, clean-room, and release-evidence commands |
| External acceptance | Durable seven-day evidence tooling exists | Configure two real feeds, two Bangumi subscriptions, qBittorrent, then complete seven natural days |

The next implementation unit is the stable engineering gate set. Release gates
then proceed as independent reviewable units; the
seven-day clock starts only after its external preflight is genuinely satisfied.

## 7. Current Verification Evidence

Verified on 2026-07-22 with `make verify` after migration `0018` and parser
`title-rules.v2`:

- Ruff formatting and lint: passed.
- Pyright: passed with zero errors.
- Backend: 109 tests passed, 89.23% statement coverage.
- Frontend: ESLint and TypeScript passed; 14 Vitest tests passed.
- Production Vite build: passed.
- Authentication integration evidence covers Argon2id setup and reset, valid
  legacy scrypt login migration, timestamp preservation, one-time audit output,
  session revocation, and malformed or unknown hash rejection.
- Startup migration evidence covers clean installation, Alembic head inspection,
  a snapshot that remains at the prior revision, one-time backup behavior,
  fail-before-migrate ordering, lock timeout, and post-failure recovery evidence.
- qBittorrent evidence covers explicit version rejection, real 4.6.7/5.0.4
  containers, add/lookup/delete-without-files, two-pass removal confirmation,
  failed-query reset, delete-before-replacement ordering, and an
  `0017 -> 0018 -> 0017 -> 0018` migration round trip.
- Disposable Compose lifecycle: passed for clean setup, operator backup,
  in-place upgrade through `0018`, clean-volume restore, and backup-based
  rollback, including audit history, waiting work, Decision, and DownloadTask
  associations.
- Container publishing workflow: statically validated for `linux/amd64` and
  `linux/arm64`, GHCR tags, BuildKit provenance, SBOM, and GitHub attestation;
  registry publication still requires an actual GitHub Actions run.
- Observability and retention integration evidence covers caller-supplied and
  generated correlation IDs, audit/event propagation, private URL redaction,
  scheduled cleanup of unmatched history, and preservation of subscription and
  manual-correction evidence.
- Feed and recognition integration evidence covers private-URL duplicate
  rejection, distinct tokenized URLs, encrypted-at-rest URL handling, candidate
  supersession, immutable prior decisions, and normal evaluation of the corrected
  candidate.
- Parser re-run evidence covers concurrent-safe initial recognition, append-only
  same-version attempts, unchanged-candidate reuse, changed-candidate supersession,
  immutable prior Decisions, and rejection of low-confidence replacements. The
  `0013` migration passed an `0012 -> head -> 0012 -> head` round trip, and browser
  checks covered real command feedback plus narrow-desktop and 390px layouts.
- Guided-setup integration evidence covers clean administrator setup, ordered and
  idempotent progress, existing-install migration, default download-path capture,
  and a read-only final candidate preview.
- Schedule integration evidence covers UTC-to-instance-timezone rendering,
  one-time missing notification, acquired-elsewhere recovery, and the absence of
  download tasks from schedule processing.
- Episode-override evidence covers postponements, double episodes, special keys,
  cancellations, split-cour-style explicit dates, horizon deactivation, baseline
  restoration, optimistic conflicts, timezone validation, corrected missing
  timing, audit history, and frontend create/edit/delete commands. The `0014`
  migration passed a `0013 -> head -> 0013 -> head` round trip. A disposable
  no-auth browser instance verified those commands at 1280px and 390px with no
  horizontal overflow or console errors.
- Episode-coverage evidence covers scaled integer/decimal spans, range-to-single
  suppression, partial-overlap confirmation, explicit manual override, reset-safe
  history, backfill exclusion, frontend explanation, and migration of prior
  Decisions plus `acquired_elsewhere` actions. Migration `0015` passed an
  `0014 -> head -> 0014 -> head` round trip.
- Subscription-lifecycle evidence covers all legal transitions, rejection of a
  direct archived-to-following jump, completed-state revision upgrades without
  ordinary new episodes, archived-state suppression, lifecycle menus, and the
  separate archived view. A disposable no-auth browser instance verified the
  active and archived views at 914px and 390px with no horizontal overflow,
  action overlap, or clipped lifecycle menu.
- Manual-Release evidence covers the database-enforced origin split, idempotent
  task reuse, reuse of automatic tasks, unsupported/missing Release rejection,
  audit correlation, and retention protection. Migration `0016` passed an
  `0015 -> head -> 0015 -> head` round trip. A disposable no-auth browser
  instance verified successful BTIH submission, existing-queue status, disabled
  pure-BTMH actions, and the Release table at desktop and 390px widths with no
  horizontal overflow or console errors.
- Parser-regression evidence covers 320 full-output golden combinations across
  subtitle groups, localized titles, episode forms, and media profiles; focused
  malformed and unsupported shapes; and 512 deterministic Unicode cases checked
  for NFKC equivalence, repeatability, and persistence bounds. Rule v2 also
  proves bounded casefold expansion, 4096-character input truncation, and safe
  rejection of zero or oversized revisions.
- HTTP-contract evidence covers durable same-request replay, different-request
  key conflict, missing and stale preconditions, version preservation for no-op
  writes, three-page traversal without duplicate or missing rows, invalid cursors,
  structured errors with caller and generated correlation IDs, and checked
  OpenAPI headers. Migration `0017` passed an
  `0016 -> head -> 0016 -> head` round trip, and the disposable Compose lifecycle
  passed setup, backup, in-place upgrade, clean restore, and rollback.
- Browser-security evidence covers IP literals, exact and wildcard trusted hosts,
  untrusted-host rejection, default same-origin writes, cross-origin and cross-site
  Fetch Metadata rejection, explicit HTTPS proxy origins, per-route login and all
  three connection-test limits, structured 429 responses, and `Retry-After`.
- Soak acceptance evidence covers incomplete-preflight refusal, idempotent start,
  the exact seven-day boundary, redacted reporting, cross-feed observation counts,
  and duplicate task identity signals.
- Alias correction evidence proves a newly arriving episode matches after an
  explicit subscription alias update while the earlier unmatched record remains
  historical evidence.

The two-feed/two-anime external acceptance and seven-day real-feed soak remain
runtime work and are not inferred from the automated suites. The 2026-07-22
preflight found administrator setup and the durable scheduler ready, but only
one healthy feed, zero following Bangumi anime, and no verified qBittorrent
connection; it therefore correctly refused to start the seven-day clock.
