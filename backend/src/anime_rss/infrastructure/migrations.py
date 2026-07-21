import os
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    current_heads: tuple[str, ...]
    target_heads: tuple[str, ...]

    @property
    def required(self) -> bool:
        return set(self.current_heads) != set(self.target_heads)


def inspect_migrations(database_url: str) -> MigrationPlan:
    config = _migration_config(database_url)
    targets = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            current = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
    finally:
        engine.dispose()
    return MigrationPlan(current_heads=current, target_heads=targets)


def run_migrations(database_url: str) -> None:
    command.upgrade(_migration_config(database_url), "head")


def _migration_config(database_url: str) -> Config:
    repository_root = Path(
        os.environ.get("ANIME_RSS_RUNTIME_ROOT", Path(__file__).resolve().parents[4])
    )
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("script_location", str(repository_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config
