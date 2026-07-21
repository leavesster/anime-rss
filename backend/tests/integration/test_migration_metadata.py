from pathlib import Path

from alembic.autogenerate import compare_metadata
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
