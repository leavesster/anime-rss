import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
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
