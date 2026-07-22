# First Release Acceptance Evidence

This document tracks the twelve release criteria in `DESIGN.md`. A criterion is
marked verified only when the stated evidence exercises its real boundary. The
release remains incomplete while any row is pending.

Last reviewed: 2026-07-22.

| # | Criterion | Automated or container evidence | Real-system evidence | Status |
| --- | --- | --- | --- | --- |
| 1 | Clean Compose setup | `make acceptance-compose` completes all eight setup steps in a historical image and logs in after upgrade. | Not required beyond the disposable container run. | Verified |
| 2 | Two feeds refresh reliably | Feed refresh, caching, retry, and scheduler integration tests pass. | Current preflight: one of one feed is healthy; a second real feed is required. | Pending |
| 3 | Two airing Bangumi anime are subscribed | Bangumi search, cache, import, schedule, and subscription integration tests pass. | Current preflight: zero following subscriptions have Bangumi identity; two are required. | Pending |
| 4 | Preferred, fallback, and rejected releases differ | Selection domain and subscription-selection integration tests cover all three outcomes and explanations. | The soak report records decisions for review. | Verified |
| 5 | Fallback wait survives restart | `test_fallback_deadline_survives_and_commits_when_due` restarts the application after persisting the deadline. | The soak report flags lost selected decisions. | Verified |
| 6 | A release seen in multiple feeds submits once | `test_same_release_from_two_feeds_is_stored_once` and timeout-after-success download coverage prove release and submission idempotency. | The soak report counts cross-feed releases and duplicate download identities. | Verified |
| 7 | qBittorrent downtime recovers without duplication | Download integration tests cover transient failure, lookup before retry, interrupted submission recovery, and explicit retry. | qBittorrent must be connected before the soak can start. | Verified |
| 8 | One alias correction affects later matching | `test_manual_alias_correction_matches_later_entries` proves a new entry matches after an explicit subscription alias update without rewriting the earlier unmatched entry. | Manual mapping and selection actions are counted for review. | Verified |
| 9 | V2 replaces incomplete work without deleting old files | `test_upgrade_cancels_incomplete_task_without_deleting_files` asserts `deleteFiles=false`, persisted supersession, delete-before-add ordering, and new submission. | Real 4.6.7 and 5.0.4 contract acceptance exercises incomplete cancellation. | Verified |
| 10 | External qBittorrent deletion is respected | `test_config_submit_reconcile_external_delete_and_explicit_retry` requires two consecutive successful empty lookups, resets confirmation across a failed lookup, and proves no automatic re-add before explicit retry. | The soak report surfaces unresolved downloader state. | Verified |
| 11 | Clean restore preserves durable associations | `make acceptance-compose` verifies setup, audit history, a waiting job, subscription/feed data, Decision, and DownloadTask association after in-place upgrade, clean restore, and rollback. | Not required beyond the disposable container run. | Verified |
| 12 | Seven real-feed days have no bad match, duplicate, or lost state | The soak tool refuses an incomplete preflight, records an immutable start, and reports integrity signals at the seven-day boundary. | Seven natural days plus manual mapping review are required. | Pending |

## Soak Procedure

Run the preflight against the persistent data directory:

```bash
make acceptance-soak-preflight
```

It requires completed setup, at least two healthy feeds, two following Bangumi
subscriptions, a successfully tested qBittorrent connection, and a healthy
scheduler. Once every check passes, start exactly once:

```bash
make acceptance-soak-start
```

The start marker is immutable and stored at
`data/acceptance/real-feed-soak.json`. Re-running `start` returns the original
window. It survives process and container restarts on the same data volume. It is
not included in operator backup archives; restoring into a clean volume requires
a new seven-day window.

Inspect progress or render the current Markdown evidence at any time:

```bash
make acceptance-soak-status
make acceptance-soak-report
```

`duration_met` means only that seven natural days elapsed. Final approval still
requires reviewing anime and episode mappings, manual corrections, and the actual
qBittorrent task list. Aggregate counts cannot prove semantic matching quality.

## Release Evidence Gate

After criterion 12 reaches the seven-day boundary, copy
`scripts/release-review-template.md` to the ignored `release-review.md`, complete
all three checks, and run:

```bash
make release-evidence VERSION=<semver>
make release-evidence-check VERSION=<semver>
```

Evidence creation refuses a pending soak or incomplete manual review before it
runs the isolated automated suite. The final directory records the exact Git
revision and checksums the clean-room log, this criteria document, the redacted
soak report, and the completed review. It is immutable for that version.
