import os
import sqlite3
from pathlib import Path

from anime_rss.config import Settings
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.modules.system.api import FileSecretCipher
from anime_rss.modules.system.doctor import DoctorService


def _statuses(settings: Settings) -> dict[str, str]:
    return {check.key: check.status for check in DoctorService(settings).run()}


def test_doctor_accepts_an_uninitialized_writable_data_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "new", web_dist_dir=tmp_path / "missing-web")

    statuses = _statuses(settings)

    assert statuses == {
        "data_directory": "pass",
        "database": "pass",
        "schema": "pass",
        "master_key": "pass",
        "restore_state": "pass",
        "web_assets": "warning",
    }


def test_doctor_checks_database_schema_key_permissions_and_restore_state(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "anime-rss.sqlite3"
    key_path = data_dir / "keys" / "master.key"
    run_migrations(f"sqlite:///{database_path}")
    FileSecretCipher.load_or_create(key_path)
    web_dist = tmp_path / "web"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("ok", encoding="utf-8")
    settings = Settings(data_dir=data_dir, web_dist_dir=web_dist)

    assert set(_statuses(settings).values()) == {"pass"}

    key_path.chmod(0o644)
    marker = data_dir / "restore" / "pending" / "pending.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    statuses = _statuses(settings)
    assert statuses["master_key"] == "fail"
    assert statuses["restore_state"] == "fail"

    key_path.chmod(0o600)
    os.remove(key_path)
    assert _statuses(settings)["master_key"] == "fail"


def test_doctor_rejects_database_corruption_and_pending_migration(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / "anime-rss.sqlite3"
    key_path = data_dir / "keys" / "master.key"
    settings = Settings(data_dir=data_dir, web_dist_dir=tmp_path / "missing-web")
    FileSecretCipher.load_or_create(key_path)

    database_path.write_bytes(b"not a sqlite database")
    statuses = _statuses(settings)
    assert statuses["database"] == "fail"
    assert statuses["schema"] == "fail"

    database_path.unlink()
    run_migrations(f"sqlite:///{database_path}")
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '0017_http_contracts'")
    statuses = _statuses(settings)
    assert statuses["database"] == "pass"
    assert statuses["schema"] == "fail"
