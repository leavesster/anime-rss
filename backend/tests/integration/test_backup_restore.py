from pathlib import Path

from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.system.api import FileSecretCipher
from anime_rss.modules.system.backup import BackupError, BackupService
from sqlalchemy import text


def test_backup_archive_restores_database_and_master_key(tmp_path: Path) -> None:
    database_path = tmp_path / "anime-rss.sqlite3"
    key_path = tmp_path / "keys" / "master.key"
    database_url = f"sqlite:///{database_path}"
    run_migrations(database_url)
    FileSecretCipher.load_or_create(key_path)
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        record_event(
            session,
            event_type="backup.fixture",
            entity_type="fixture",
            entity_id="one",
        )
    engine.dispose()

    service = BackupService(
        database_url=database_url,
        master_key_file=key_path,
        data_dir=tmp_path,
        retention_count=2,
    )
    backup = service.create_backup()
    archive = service.backup_path(backup.filename)
    original_key = key_path.read_bytes()

    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_events"))
    engine.dispose()
    key_path.write_bytes(b"x" * 32)

    staged = service.stage_restore(archive)
    assert staged.restart_required is True
    assert service.apply_pending_restore() is True
    assert service.apply_pending_restore() is False
    assert key_path.read_bytes() == original_key
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM audit_events")) == 1
    engine.dispose()
    assert any(item.reason == "pre-restore" for item in service.list_backups())


def test_backup_rejects_invalid_archives_and_prunes_retention(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'anime-rss.sqlite3'}"
    key_path = tmp_path / "master.key"
    run_migrations(database_url)
    FileSecretCipher.load_or_create(key_path)
    service = BackupService(
        database_url=database_url,
        master_key_file=key_path,
        data_dir=tmp_path,
        retention_count=2,
    )
    service.create_backup()
    service.create_backup()
    service.create_backup()
    assert len(service.list_backups()) == 2

    invalid = tmp_path / "invalid.backup"
    invalid.write_bytes(b"not a backup")
    try:
        service.stage_restore(invalid)
    except BackupError as error:
        assert str(error) == "backup archive is invalid"
    else:
        raise AssertionError("invalid archive was accepted")
