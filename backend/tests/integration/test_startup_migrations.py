import sqlite3
import zipfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from anime_rss.infrastructure.migrations import inspect_migrations
from anime_rss.modules.system.api import FileSecretCipher
from anime_rss.modules.system.backup import BackupService
from anime_rss.modules.system.startup import (
    MigrationFileLock,
    MigrationLockError,
    StartupService,
)


def _upgrade_to(database_url: str, revision: str) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


def _service(tmp_path: Path, database_url: str) -> StartupService:
    return StartupService(
        database_url=database_url,
        backups=BackupService(
            database_url=database_url,
            master_key_file=tmp_path / "master.key",
            data_dir=tmp_path,
            retention_count=7,
        ),
    )


def test_clean_startup_migrates_without_creating_an_empty_backup(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'anime-rss.sqlite3'}"
    FileSecretCipher.load_or_create(tmp_path / "master.key")

    result = _service(tmp_path, database_url).prepare(auto_migrate=True)

    assert result.restored is False
    assert result.migration_plan.required is False
    assert result.migration_backup is None
    assert not (tmp_path / "backups").exists()
    assert (tmp_path / ".anime-rss-migration.lock").is_file()


def test_existing_database_is_backed_up_before_migration_and_only_once(tmp_path: Path) -> None:
    database_path = tmp_path / "anime-rss.sqlite3"
    database_url = f"sqlite:///{database_path}"
    _upgrade_to(database_url, "0016_manual_downloads")
    FileSecretCipher.load_or_create(tmp_path / "master.key")
    service = _service(tmp_path, database_url)

    first = service.prepare(auto_migrate=True)

    assert first.migration_plan.required is False
    assert first.migration_backup is not None
    assert first.migration_backup.reason == "pre-migration"
    archive_path = tmp_path / "backups" / first.migration_backup.filename
    snapshot_path = tmp_path / "pre-migration.sqlite3"
    with zipfile.ZipFile(archive_path) as archive:
        snapshot_path.write_bytes(archive.read("database.sqlite3"))
    with sqlite3.connect(snapshot_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0016_manual_downloads",
        )
    assert inspect_migrations(database_url).required is False

    second = service.prepare(auto_migrate=True)
    assert second.migration_backup is None
    assert len(list((tmp_path / "backups").glob("*.backup"))) == 1


def test_failed_migration_keeps_the_pre_migration_backup(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'anime-rss.sqlite3'}"
    _upgrade_to(database_url, "0016_manual_downloads")
    FileSecretCipher.load_or_create(tmp_path / "master.key")
    backups = BackupService(
        database_url=database_url,
        master_key_file=tmp_path / "master.key",
        data_dir=tmp_path,
    )

    def fail_migration(_: str) -> None:
        raise RuntimeError("migration failed")

    service = StartupService(
        database_url=database_url,
        backups=backups,
        migration_runner=fail_migration,
    )
    with pytest.raises(RuntimeError, match="migration failed"):
        service.prepare(auto_migrate=True)

    listed = backups.list_backups()
    assert len(listed) == 1
    assert listed[0].reason == "pre-migration"
    assert inspect_migrations(database_url).current_heads == ("0016_manual_downloads",)


def test_migration_lock_times_out_without_entering_the_critical_section(tmp_path: Path) -> None:
    lock_path = tmp_path / ".anime-rss-migration.lock"
    with (
        MigrationFileLock(lock_path, timeout_seconds=1),
        pytest.raises(MigrationLockError, match="timed out waiting for migration lock"),
        MigrationFileLock(lock_path, timeout_seconds=0.05),
    ):
        raise AssertionError("contended migration lock was acquired")
