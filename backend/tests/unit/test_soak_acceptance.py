import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from anime_rss.acceptance import SoakAcceptanceService, SoakNotReadyError


def _create_database(data_dir: Path, *, ready: bool) -> sqlite3.Connection:
    data_dir.mkdir()
    connection = sqlite3.connect(data_dir / "anime-rss.sqlite3")
    connection.executescript(
        """
        CREATE TABLE sys_instance_settings (setup_completed INTEGER NOT NULL);
        CREATE TABLE feed_feeds (
            health TEXT NOT NULL,
            consecutive_failures INTEGER NOT NULL,
            last_success_at TEXT
        );
        CREATE TABLE catalog_anime (id TEXT PRIMARY KEY, source TEXT, bangumi_id INTEGER);
        CREATE TABLE sub_subscriptions (anime_id TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE download_configs (
            adapter TEXT NOT NULL,
            last_success_at TEXT,
            last_error_code TEXT
        );
        CREATE TABLE runtime_scheduler_state (last_success_at TEXT, last_error_code TEXT);
        CREATE TABLE feed_fetches (
            started_at TEXT NOT NULL,
            status TEXT NOT NULL,
            new_entry_count INTEGER NOT NULL
        );
        CREATE TABLE audit_events (created_at TEXT NOT NULL, event_type TEXT NOT NULL);
        CREATE TABLE feed_entries (id TEXT PRIMARY KEY, feed_id TEXT NOT NULL);
        CREATE TABLE release_sources (
            release_id TEXT NOT NULL,
            feed_entry_id TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        CREATE TABLE match_candidates (first_seen_at TEXT NOT NULL);
        CREATE TABLE match_manual_actions (created_at TEXT NOT NULL);
        CREATE TABLE select_decisions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
        CREATE TABLE select_manual_actions (created_at TEXT NOT NULL);
        CREATE TABLE download_attempts (started_at TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE runtime_job_runs (started_at TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE download_tasks (
            subscription_id TEXT NOT NULL,
            info_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            stale INTEGER NOT NULL
        );
        CREATE TABLE select_episode_slots (selected_decision_id TEXT);
        """
    )
    connection.execute("INSERT INTO sys_instance_settings VALUES (?)", (int(ready),))
    if ready:
        connection.executemany(
            "INSERT INTO feed_feeds VALUES ('healthy', 0, '2026-07-22T00:00:00Z')",
            ((), ()),
        )
        connection.executemany(
            "INSERT INTO catalog_anime VALUES (?, 'bangumi', ?)",
            (("anime-1", 1), ("anime-2", 2)),
        )
        connection.executemany(
            "INSERT INTO sub_subscriptions VALUES (?, 'following')",
            (("anime-1",), ("anime-2",)),
        )
        connection.execute(
            "INSERT INTO download_configs VALUES ('qbittorrent', '2026-07-22T00:00:00Z', NULL)"
        )
        connection.execute(
            "INSERT INTO runtime_scheduler_state VALUES ('2026-07-22T00:00:00Z', NULL)"
        )
    connection.commit()
    return connection


def test_soak_start_refuses_incomplete_preflight(tmp_path: Path) -> None:
    connection = _create_database(tmp_path / "data", ready=False)
    connection.close()
    service = SoakAcceptanceService(tmp_path / "data")

    checks = service.preflight()

    assert {check.key for check in checks if not check.passed} == {
        "setup",
        "feeds",
        "subscriptions",
        "downloader",
        "scheduler",
    }
    with pytest.raises(SoakNotReadyError):
        service.start(now=datetime(2026, 7, 22, tzinfo=UTC))
    assert not (tmp_path / "data/acceptance/real-feed-soak.json").exists()


def test_soak_state_is_idempotent_and_reports_seven_day_window(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    connection = _create_database(data_dir, ready=True)
    service = SoakAcceptanceService(data_dir)
    started_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)

    state = service.start(now=started_at)
    repeated = service.start(now=started_at + timedelta(days=2))

    assert repeated == state
    assert service.status(now=started_at + timedelta(days=6)).phase == "running"

    observed_at = "2026-07-23T01:00:00Z"
    connection.executemany(
        "INSERT INTO feed_fetches VALUES (?, ?, ?)",
        ((observed_at, "success", 2), (observed_at, "transient_failure", 0)),
    )
    connection.execute("INSERT INTO audit_events VALUES (?, 'feed.refresh_failed')", (observed_at,))
    connection.executemany(
        "INSERT INTO feed_entries VALUES (?, ?)",
        (("entry-1", "feed-1"), ("entry-2", "feed-2")),
    )
    connection.executemany(
        "INSERT INTO release_sources VALUES ('release-1', ?, ?)",
        (("entry-1", observed_at), ("entry-2", observed_at)),
    )
    connection.executemany(
        "INSERT INTO download_tasks VALUES ('subscription-1', 'hash-1', 'completed', 0)",
        ((), ()),
    )
    connection.commit()
    connection.close()

    status = service.status(now=started_at + timedelta(days=7))

    assert status.phase == "duration_met"
    assert status.metrics["feed_fetch_successes"] == 1
    assert status.metrics["feed_fetch_failures"] == 1
    assert status.metrics["feed_failure_events"] == 1
    assert status.metrics["new_feed_entries"] == 2
    assert status.metrics["cross_feed_releases"] == 1
    assert status.metrics["duplicate_download_identities"] == 1
    report = service.render_report(now=started_at + timedelta(days=7))
    assert "Phase: `duration_met`" in report
    assert "counts cannot prove semantic correctness" in report
