import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from anime_rss.infrastructure import api as api_persistence  # noqa: F401
from anime_rss.infrastructure import events as event_persistence  # noqa: F401
from anime_rss.infrastructure.database import Base, create_database_engine
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.modules.audit import persistence as audit_persistence  # noqa: F401
from anime_rss.modules.catalog import persistence as catalog_persistence  # noqa: F401
from anime_rss.modules.downloads import persistence as download_persistence  # noqa: F401
from anime_rss.modules.feeds import persistence as feed_persistence  # noqa: F401
from anime_rss.modules.notifications import persistence as notification_persistence  # noqa: F401
from anime_rss.modules.operations import persistence as operations_persistence  # noqa: F401
from anime_rss.modules.recognition import persistence as recognition_persistence  # noqa: F401
from anime_rss.modules.releases import persistence as release_persistence  # noqa: F401
from anime_rss.modules.selection import persistence as selection_persistence  # noqa: F401
from anime_rss.modules.subscriptions import persistence as subscription_persistence  # noqa: F401
from anime_rss.modules.system import persistence as system_persistence  # noqa: F401


def test_migrations_match_sqlalchemy_metadata(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    run_migrations(database_url)
    engine = create_database_engine(database_url)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == []
    engine.dispose()


def test_download_reconciliation_migration_round_trip(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'download-reconciliation.sqlite3'}"
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0017_http_contracts")

    engine = create_database_engine(database_url)
    assert "missing_observation_count" not in {
        column["name"] for column in sa.inspect(engine).get_columns("download_tasks")
    }
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    assert "missing_observation_count" in {
        column["name"] for column in sa.inspect(engine).get_columns("download_tasks")
    }
    engine.dispose()

    command.downgrade(config, "0017_http_contracts")
    command.upgrade(config, "head")


def test_release_display_name_migration_backfills_existing_release(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'release-display-name.sqlite3'}"
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0018_download_reconciliation")
    engine = create_database_engine(database_url)
    timestamp = "2026-07-22T00:00:00Z"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO feed_feeds (
                    id, name, url_redacted, url_fingerprint, endpoint_ciphertext,
                    interval_seconds, health, consecutive_failures, version, created_at, updated_at
                ) VALUES (
                    'feed', 'Feed', 'https://feed.test/rss', 'fingerprint', X'00',
                    600, 'healthy', 0, 1, :timestamp, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO feed_entries (
                    id, feed_id, guid_hash, identity_strength, title_raw, title_normalized,
                    release_status, first_seen_at
                ) VALUES (
                    'entry', 'feed', 'guid-hash', 'strong', '[Group] Anime - 01.mkv',
                    '[Group] Anime - 01.mkv', 'identified', :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO release_releases (
                    id, identity_kind, identity_value, btih, automation_eligible, first_seen_at
                ) VALUES (
                    'release', 'btih', '0123456789abcdef0123456789abcdef01234567',
                    '0123456789abcdef0123456789abcdef01234567', 1, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO release_sources (id, release_id, feed_entry_id, observed_at)
                VALUES ('source', 'release', 'entry', :timestamp)
                """
            ),
            {"timestamp": timestamp},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        display_name = connection.scalar(
            sa.text("SELECT display_name FROM release_releases WHERE id = 'release'")
        )
    assert display_name == "[Group] Anime - 01.mkv"
    engine.dispose()


def test_guided_setup_migration_completes_existing_administrator(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'upgrade.sqlite3'}"
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0009_schedule_calendar")
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO sys_admin_accounts (
                    id, username, password_hash, password_changed_at, created_at, updated_at
                ) VALUES (
                    'administrator', 'admin', 'hash',
                    '2026-07-22T00:00:00Z', '2026-07-22T00:00:00Z', '2026-07-22T00:00:00Z'
                )
                """
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT setup_completed_steps, setup_completed "
                "FROM sys_instance_settings WHERE id = 'default'"
            )
        ).one()
    assert json.loads(row.setup_completed_steps)[-1] == "candidate_preview"
    assert row.setup_completed == 1
    engine.dispose()


def test_episode_coverage_migration_backfills_existing_decisions_and_manual_acquisition(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'coverage-upgrade.sqlite3'}"
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0014_schedule_overrides")
    engine = create_database_engine(database_url)
    timestamp = "2026-07-22T00:00:00Z"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_anime (
                    id, primary_title, source, created_at, updated_at
                ) VALUES ('anime', 'Migration Anime', 'local', :timestamp, :timestamp)
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO release_releases (
                    id, identity_kind, identity_value, btih, automation_eligible, first_seen_at
                ) VALUES (
                    'release', 'btih', '0123456789abcdef0123456789abcdef01234567',
                    '0123456789abcdef0123456789abcdef01234567', 1, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO sub_subscriptions (
                    id, anime_id, anime_title, state, match_keys, rules,
                    activation_at, version, created_at, updated_at
                ) VALUES (
                    'subscription', 'anime', 'Migration Anime', 'following', '["migrationanime"]',
                    '{}', :timestamp, 1, :timestamp, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO select_episode_slots (
                    id, subscription_id, anime_title, episode_key, state, version,
                    created_at, updated_at
                ) VALUES (
                    'slot-range', 'subscription', 'Migration Anime', '1-2', 'decided', 1,
                    :timestamp, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO select_decisions (
                    id, slot_id, subscription_id, episode_key, candidate_id, release_id,
                    kind, reason, rules_snapshot, candidate_snapshot, created_at
                ) VALUES (
                    'decision-range', 'slot-range', 'subscription', '1-2', 'candidate',
                    'release', 'selected_backfill', '{}', '{}', '{}', :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO download_tasks (
                    id, decision_id, release_id, subscription_id, info_hash, adapter,
                    idempotency_key, state, tags, progress, stale, observed_once,
                    cancellation_requested, attempt_count, version, created_at, updated_at
                ) VALUES (
                    'download-task', 'decision-range', 'release', 'subscription',
                    '0123456789abcdef0123456789abcdef01234567', 'qbittorrent',
                    'download-request:decision-range:release:1', 'planned', '[]', 0, 0, 0,
                    0, 0, 1, :timestamp, :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO select_manual_actions (
                    id, subscription_id, episode_key, action, reason, created_at
                ) VALUES (
                    'manual-decimal', 'subscription', '3.5', 'acquired_elsewhere', '{}',
                    :timestamp
                )
                """
            ),
            {"timestamp": timestamp},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        coverage = list(
            connection.execute(
                sa.text(
                    "SELECT covered_episode_key, covered_value_millis, source_type "
                    "FROM select_episode_coverages ORDER BY covered_value_millis"
                )
            )
        )
        task_origin = connection.execute(
            sa.text("SELECT origin_kind FROM download_tasks WHERE id = 'download-task'")
        ).scalar_one()
    assert coverage == [
        ("1", 1000, "decision"),
        ("2", 2000, "decision"),
        ("3.5", 3500, "manual_action"),
    ]
    assert task_origin == "selection_decision"
    engine.dispose()

    command.downgrade(config, "0014_schedule_overrides")
    command.upgrade(config, "head")
