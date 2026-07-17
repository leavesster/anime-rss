# Anime RSS Service Design

Status: Product design approved

Date: 2026-07-17

Target: First public self-hosted release

## 1. Product Definition

This product is a single-user, self-hosted anime download automation service.
It periodically reads multiple user-configured RSS or Atom feeds, identifies
releases for subscribed seasonal TV anime, selects the best acceptable release
for each episode, and submits it to qBittorrent exactly once.

The product is centered on anime subscriptions. RSS feeds are candidate sources,
not the primary object exposed to users.

The automation boundary ends after a download has been submitted, monitored, and
confirmed complete. Playback, transcoding, media scraping, and watch progress are
owned by existing systems such as Jellyfin, Emby, or Plex.

## 2. Target User and Deployment

- One administrator.
- Self-hosted on a NAS or Linux machine.
- Trusted home or private network, while still requiring application login.
- Distributed as an open-source, reusable tool.
- Delivered as one Docker container with a persistent data volume.
- Docker Compose is the primary installation path.
- Both amd64 and arm64 images are required.

The first release does not support registration, multiple users, roles, shared
subscriptions, high availability, or public hosted operation.

## 3. Core Workflow

```text
Configured RSS/Atom feeds
        |
        v
Fetch, validate, normalize, and deduplicate entries
        |
        v
Parse release title into structured attributes
        |
        v
Match anime and episode with an explicit confidence level
        |
        v
Apply subscription hard filters and ordered preferences
        |
        v
Choose immediately or wait for a preferred release
        |
        v
Create an idempotent download decision
        |
        v
Submit to qBittorrent and reconcile task state
        |
        v
Complete, fail, get externally removed, or be superseded by V2/V3
```

Every transition that affects a download decision must be persisted. Restarting
the application must not lose waiting windows, retries, decisions, or task links.

## 4. Scope of Supported Content

The first release automatically handles currently airing TV anime published as
individual episode releases.

Supported episode forms:

- Integer episodes such as `01` and `12`.
- Decimal episodes such as `7.5`.
- Episode ranges such as `01-02`.
- Same-group revisions such as `V2` and `V3`.

The following may be collected and shown, but are not automatically selected:

- Movies.
- OVA and OAD releases.
- Specials.
- BDRip batches.
- Full-season packs.
- Historical bulk downloads.

Users may manually submit unsupported entries to qBittorrent.

## 5. Domain Model

The implementation should preserve the following conceptual entities even if
some are initially represented by fewer database tables.

### Feed

Stores the configured URL, authentication method, request headers, refresh
interval, cache validators, last successful fetch, retry state, and health.

### Feed Entry

Stores source identity, GUID, title, publication time, links, enclosure metadata,
normalized magnet or torrent reference, fetch time, and parsing status.

### Release

Represents a unique BitTorrent publication. The final identity is its info hash.
The same release may be observed in multiple feeds and through multiple entries.

### Anime

Stores a stable local ID, Bangumi ID when available, titles, aliases, cover,
airing metadata, expected episode count, and user overrides.

### Subscription

Connects an anime to version rules, aliases, waiting policy, save path, and
lifecycle state. New subscriptions inherit a global preference profile and may
override individual fields.

### Episode

Represents an expected or observed episode identity. Episode identifiers cannot
be restricted to integers because decimals and ranges are supported.

### Candidate

Connects a parsed release to an anime episode and records confidence, normalized
attributes, filter results, ordered preference comparison, and explanations.

### Decision

Records why a candidate was selected, rejected, delayed, manually overridden, or
superseded. A decision is separate from the downloader's current task state.

### Download Task

Stores the adapter, qBittorrent task identity, info hash, actual save path,
category, tags, last observed state, submission attempts, and external changes.

### Event

An append-oriented audit record for automatic decisions, user actions, errors,
retries, notifications, and reconciliation results.

## 6. Anime Metadata

Bangumi is the primary metadata and search source for the first release.

For each anime, cache at least:

- Local permanent ID.
- Bangumi subject ID.
- Chinese, Japanese, English, and romanized titles when available.
- Additional aliases.
- Air date and airing state.
- Expected episode count.
- Broadcast weekday and schedule.
- Cover reference.
- User-defined matching aliases.

External metadata is advisory. RSS ingestion, matching, and downloading must
continue when Bangumi is unavailable. Users must be able to create a local anime
record and override imported metadata.

Bangumi schedules are used for calendar display and missing-episode alerts only.
They never create download decisions. By default, an episode becomes potentially
missing 24 hours after its expected airtime if no acceptable candidate exists.

All stored timestamps use UTC. The interface renders the administrator's chosen
timezone.

## 7. Title Parsing and Matching

Title parsing is deterministic and independent of the decision engine. It should
extract, when present:

- Anime title and candidate aliases.
- Episode number, decimal number, or range.
- Release group.
- Resolution.
- Video codec.
- Subtitle language and packaging.
- Revision number.
- Batch, movie, special, or unsupported-content markers.

Each match has a confidence class:

- High: safe for automatic decisions.
- Medium: plausible but requires user confirmation.
- Low: unrecognized and not eligible for automation.

The system must never silently guess when anime or episode identity is ambiguous.
The interface must explain which alias matched, which fields were extracted, and
why a candidate was accepted or rejected.

Manual correction may add an instance-local alias or matching rule. Corrections
must not become global parsing rules without reviewed regression coverage.

The parser requires a fixture-based regression corpus containing real title
shapes across release groups, languages, episode formats, revisions, resolutions,
codecs, subtitle variants, misleading years or resolution numbers, malformed
input, and oversized input. Parsing the same title must always produce the same
result.

The first release does not use an LLM at runtime for title parsing.

## 8. Version Rules

Rules use two separate concepts.

### Hard Filters

Hard filters express releases that must never be downloaded, for example:

- Raw releases without subtitles.
- 4K releases.
- Unsupported subtitle languages.
- Batches or specials.
- Explicitly blocked release groups.

### Ordered Preferences

Soft preferences are compared lexicographically instead of through opaque
numeric weights. The default field order is:

1. Preferred release group order.
2. Subtitle language order.
3. Resolution order.
4. Video codec order.
5. Revision number.
6. Publication time.
7. Info hash as a stable final tie breaker.

Preference values are ordered lists, for example:

```text
Release group: MiaoMeng > LoliHouse > Sakurato
Resolution: 1080p > 720p
Codec: HEVC > AVC
```

The candidate view must identify the first comparison field on which one release
lost to another.

## 9. Selection Timing

Selection uses a preferred-release and fallback-delay model.

- A candidate that satisfies all preferred conditions is submitted immediately.
- An acceptable fallback starts a configurable waiting window, default two hours.
- A preferred candidate arriving during the window wins.
- If the window expires, the best currently acceptable fallback is submitted.
- Ordinary later releases are ignored after an episode has been downloaded.
- Waiting deadlines and candidate state survive application restarts.

When a subscription is created, only entries first observed after activation are
eligible for automatic decisions. Historical episodes use an explicit backfill
flow: scan, choose an episode range, preview selected releases, confirm, and then
submit. Backfill chooses the current best candidate without a waiting window.

## 10. Revision Upgrades

A release is an automatic revision upgrade only when anime, episode, and release
group match and its revision number is higher.

- If the old task is incomplete, cancel it and submit the new revision.
- If the old task is complete, submit the new revision and mark the old release
  as superseded.
- Never automatically delete completed files.
- A later release from a different group is not an automatic upgrade.

## 11. Deduplication and Idempotency

Deduplication is layered:

1. BitTorrent info hash is the final release identity.
2. A normalized magnet link is used when the hash can be extracted from it.
3. A fetched `.torrent` file is validated and hashed before submission.
4. `feed + GUID` prevents repeated ingestion from the same source while torrent
   identity is not yet available.

Similar titles are not sufficient evidence that two entries are the same release.
Every downloader submission has a durable idempotency key. Scheduler retries,
application restarts, repeated feed observations, and concurrent jobs must never
submit the same decision twice.

## 12. qBittorrent Integration

qBittorrent Web API is the only complete downloader adapter in the first release.
The internal contract should still be adapter-based so other clients can be
added later.

Required capabilities:

- Authenticate and test connectivity.
- Add a magnet URI or uploaded `.torrent` payload.
- Set save path, category, and tags.
- Query task state and progress.
- Cancel an incomplete superseded task.
- Distinguish an existing torrent from a failed submission.
- Reconcile actual downloader state with local records.

qBittorrent is the source of truth for runtime task state. The application is the
source of truth for selection rationale and history.

External qBittorrent actions are respected:

- External pause remains paused.
- External deletion becomes `externally removed` and is not automatically added
  again.
- External path or tag changes are reflected in the application.
- Temporary connection failure retains the last known state and marks it stale;
  it must not be interpreted as task deletion.

The application only controls the qBittorrent save path. It does not rename,
move, hard-link, copy, or delete downloaded files.

## 13. Subscription Lifecycle

Subscriptions have four states:

- Following: process new releases automatically.
- Paused: retain rules and history but stop new decisions.
- Completed: stop expecting ordinary new episodes but continue recognizing
  same-group V2/V3 revisions.
- Archived: hide from the daily dashboard and stop all automatic processing.

External metadata may suggest completion but cannot automatically archive a
subscription. Resuming after a pause does not automatically download entries
observed during the pause; those use the backfill preview flow.

## 14. Manual Controls and Auditability

For each episode, the administrator can:

- Inspect all candidates and comparison explanations.
- Select a candidate immediately.
- Reject a release.
- Remap a release to the correct anime or episode.
- Mark an episode as acquired elsewhere.
- Retry a failed submission.
- Reset an automatic decision without bypassing info-hash deduplication.

Every action creates an event. Decisions must not be silently overwritten or
removed to simulate a reset.

## 15. User Interface

The home page is an exception-oriented anime dashboard, not an RSS reader.

It shows:

- Today's and the next seven days' airing schedule.
- The latest state for each followed anime and episode.
- Releases waiting for a preferred candidate.
- Items requiring manual confirmation.
- Missing-episode warnings.
- Feed and downloader failures.
- Recent automatic decisions.

Additional views:

- Anime search and subscription creation.
- Subscription detail with episodes, candidates, aliases, and overrides.
- Manual confirmation inbox.
- Raw release library for search and debugging.
- Feed management and fetch history.
- qBittorrent connection and task reconciliation.
- Global preference profile.
- Notifications, audit events, backup, and system health.

The web application must be responsive. A phone can review exceptions, inspect
candidates, select a release, retry a task, and pause a subscription. Complex
configuration is optimized for desktop. A native app and offline PWA behavior
are not first-release requirements.

## 16. Initial Setup

An unconfigured installation enters a guided setup flow:

1. Create the administrator password.
2. Choose timezone and interface language.
3. Connect to qBittorrent and verify required API capabilities.
4. Configure default save path, category, and tags.
5. Add at least one feed and preview normalized entries.
6. Configure the global version preference profile.
7. Search for and subscribe to the first anime.
8. Preview currently known candidates without automatically backfilling them.

Errors must be specific enough to act on, such as authentication failure,
unsupported feed format, invalid torrent payload, or qBittorrent API rejection.

## 17. Feed Support

The application provides configuration presets for common feed shapes, but users
supply all actual feed URLs and credentials. It does not operate a central feed,
torrent index, proxy, or public aggregation service.

Supported configuration:

- Public RSS or Atom URL.
- Private token embedded in a URL.
- HTTP Basic Authentication.
- Custom request headers.
- Per-feed refresh interval.
- Manual connectivity and parsing test.

Fetch behavior:

- Default interval: ten minutes.
- Configurable range: five to sixty minutes.
- Random jitter to avoid synchronized requests.
- ETag and Last-Modified support.
- Exponential retry backoff up to one hour.
- Immediate credential-error state for HTTP 401 or 403.
- Persisted retry state across restarts.
- One failure notification after a threshold and one recovery event.

## 18. Notifications

The first release provides in-application notifications and a generic structured
JSON webhook.

Notify on:

- Episode submitted for download.
- Fallback selected after its waiting window.
- V2/V3 replacement.
- Repeated feed failure and recovery.
- Downloader unavailability or submission failure.
- Item requiring manual confirmation.
- Episode still missing after the configured schedule threshold.

Platform-specific Telegram, DingTalk, Slack, Gotify, and similar integrations are
future adapters rather than first-release dependencies.

## 19. Authentication and Secrets

- One administrator account.
- First-run password creation.
- Password stored only as a strong password hash.
- Secure cookie-based web session.
- API protected by the same authentication boundary.
- Command-line administrator password reset.
- Feed, qBittorrent, and webhook credentials encrypted at rest.
- Secrets and URL tokens redacted from UI diagnostics, logs, and error reports.
- No registration, password email recovery, OAuth, or role system.

## 20. Network and Input Safety

- Only explicitly configured feed URLs are fetched as feeds.
- Automatically fetched torrent responses have strict size and time limits.
- Redirect count is limited.
- Authentication headers are not forwarded to a different redirect host.
- Only HTTP(S) torrent downloads and magnet URIs are accepted.
- Torrent payloads must be valid bencode with valid info dictionaries.
- Feed descriptions do not cause automatic image, script, or attachment fetches.
- Internal addresses are allowed for explicitly configured feeds, qBittorrent,
  and webhooks because private-network self-hosting is a core use case.

## 21. Data Retention and Backup

- Releases and decisions related to subscriptions: retain until the user deletes
  the subscription data.
- Unmatched feed entries: retain 90 days.
- Manually rejected or corrected release fingerprints: retain permanently.
- Raw feed XML: do not retain during normal successful operation.
- Redacted parsing-failure payload: retain up to seven days.
- Rolling application logs: retain 14 days by default.
- Create a consistent daily SQLite backup and retain seven backups by default.
- Backup and restore must preserve subscriptions, aliases, rules, decisions,
  waiting windows, and task links.
- Credential export is encrypted and handled separately from ordinary readable
  configuration export.

## 22. Technical Architecture

Recommended first-release stack:

- Python backend.
- FastAPI for the HTTP API and authentication boundary.
- SQLAlchemy for persistence.
- Alembic for schema migrations.
- SQLite in WAL mode where appropriate.
- A lightweight scheduler whose durable job state lives in the database.
- `feedparser` or an equivalent mature RSS/Atom parser.
- A dedicated deterministic anime-title parsing module.
- TypeScript and React frontend.
- OpenAPI-generated frontend API types.
- Frontend static assets served by the backend in the production container.

The production topology is one application process group and one SQLite data
volume. Redis, PostgreSQL, and a separate task queue are not required. Scheduler
leases or database locks must prevent duplicate work if the application briefly
has overlapping workers during restart.

## 23. Observability

The application should expose:

- Health endpoint for process and database readiness.
- Feed health and last successful fetch.
- Bangumi metadata freshness.
- qBittorrent connectivity and last successful reconciliation.
- Scheduler job state and next execution time.
- Pending waiting decisions.
- Failed submission attempts.
- Structured logs with correlation IDs for fetch, parse, decision, and submit
  operations.

Normal health checks must not flood application logs.

## 24. First-Release Non-Goals

- Multiple users, registration, roles, and shared subscriptions.
- Online playback, transcoding, media scraping, and watch progress.
- Transmission, Deluge, aria2, and other downloaders.
- Automatic movies, OVA, specials, BDRip batches, and season packs.
- Automatic historical backfill without preview and confirmation.
- Automatic file renaming, moving, copying, hard-linking, or deletion.
- LLM-based runtime matching.
- Native mobile applications.
- Public RSS or torrent indexing.
- Web-page scraping and resource search.
- Redis, PostgreSQL, multi-node operation, Kubernetes, and high availability.
- Plugin marketplace or arbitrary user-script execution.
- Automatic upgrades across different release groups.

## 25. Delivery Stages

### Stage 1: Ingestion Foundation

- Feed configuration and secure fetching.
- RSS/Atom normalization.
- Torrent validation and info-hash identity.
- Release storage and layered deduplication.
- Feed health and retry state.

### Stage 2: Anime and Parsing

- Bangumi search and local metadata cache.
- Local anime and alias management.
- Deterministic title parser.
- Confidence classification.
- Parser fixture corpus and regression suite.

### Stage 3: Subscription Decision Engine

- Global preferences and per-anime overrides.
- Hard filters and lexicographic preferences.
- Episode candidates and explanations.
- Preferred/fallback waiting windows.
- Backfill preview.
- V2/V3 upgrade decisions.

### Stage 4: qBittorrent Integration

- Adapter contract.
- Idempotent submission.
- Task-state reconciliation.
- External modification behavior.
- Retry and failure handling.

### Stage 5: Product Interface

- Administrator setup and login.
- Initialization wizard.
- Dashboard and airing calendar.
- Subscription and episode views.
- Manual confirmation inbox.
- Release and audit views.
- Responsive mobile interactions.

### Stage 6: Operational Delivery

- Webhooks and notifications.
- Backup, restore, retention, and migrations.
- Multi-architecture Docker image.
- Docker Compose documentation.
- Security review and diagnostic redaction.
- Seven-day live soak test.

## 26. Acceptance Criteria

The first release is complete only when all of the following hold:

1. A clean Docker Compose environment can complete the setup wizard.
2. At least two different feeds can be connected and refreshed reliably.
3. Two currently airing anime can be found through Bangumi and subscribed.
4. Preferred, fallback, and hard-rejected releases are distinguished correctly.
5. A fallback waiting window survives an application restart.
6. The same release observed through multiple feeds is submitted only once.
7. Temporary qBittorrent downtime can be recovered without duplicate submission.
8. One manual alias correction causes later entries of that shape to match.
9. V2 can replace an incomplete task while completed old files remain untouched.
10. External deletion in qBittorrent is respected and does not trigger re-add.
11. Backup restoration into a clean container preserves subscriptions, history,
    waiting jobs, and task associations.
12. The service runs for seven consecutive days against real feeds without an
    incorrect anime match, duplicate download, or lost decision state.

## 27. Design Principle

The service must always be able to answer three questions:

1. Why was this release considered to be this anime and episode?
2. Why did this release win or lose against the other candidates?
3. Why was this qBittorrent task created, replaced, retried, or left alone?

If a feature cannot preserve those explanations and idempotent behavior, it does
not belong in the first release.
