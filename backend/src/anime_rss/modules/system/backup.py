import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy.engine import make_url

from anime_rss.kernel.time import Clock, utc_now

_ARCHIVE_VERSION = 1
_DATABASE_MEMBER = "database.sqlite3"
_KEY_MEMBER = "master.key"
_MANIFEST_MEMBER = "manifest.json"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class RestoreStage:
    backup_filename: str
    created_at: datetime
    restart_required: bool = True


class BackupService:
    """Creates portable archives and stages restore work for the next startup."""

    def __init__(
        self,
        *,
        database_url: str,
        master_key_file: Path,
        data_dir: Path,
        retention_count: int = 14,
        max_restore_bytes: int = 512 * 1024 * 1024,
        clock: Clock = utc_now,
    ) -> None:
        self._database_path = self.database_path(database_url)
        self._master_key_file = master_key_file
        self._backup_dir = data_dir / "backups"
        self._restore_dir = data_dir / "restore"
        self._retention_count = retention_count
        self._max_restore_bytes = max_restore_bytes
        self._clock = clock

    @staticmethod
    def database_path(database_url: str) -> Path:
        url = make_url(database_url)
        if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
            raise BackupError("backup requires a file-backed SQLite database")
        return Path(url.database).absolute()

    def create_backup(self, *, reason: str = "manual") -> BackupInfo:
        now = self._clock()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        name = f"anime-rss-{now.strftime('%Y%m%dT%H%M%SZ')}-{reason}.backup"
        destination = self._backup_dir / name
        if destination.exists():
            name = (
                f"anime-rss-{now.strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(3).hex()}-{reason}.backup"
            )
            destination = self._backup_dir / name

        with tempfile.TemporaryDirectory(dir=self._backup_dir) as temporary:
            database_copy = Path(temporary) / _DATABASE_MEMBER
            self._copy_database(database_copy)
            manifest = {
                "archive_version": _ARCHIVE_VERSION,
                "application": "anime-rss-service",
                "created_at": now.isoformat(),
                "reason": reason,
                "database_member": _DATABASE_MEMBER,
                "master_key_member": _KEY_MEMBER,
            }
            partial = destination.with_suffix(".partial")
            try:
                with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(database_copy, _DATABASE_MEMBER)
                    archive.write(self._master_key_file, _KEY_MEMBER)
                    archive.writestr(
                        _MANIFEST_MEMBER,
                        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                    )
                os.replace(partial, destination)
            finally:
                partial.unlink(missing_ok=True)
        self.prune()
        return BackupInfo(name, destination.stat().st_size, now, reason)

    def list_backups(self) -> list[BackupInfo]:
        if not self._backup_dir.exists():
            return []
        values: list[BackupInfo] = []
        for path in self._backup_dir.glob("*.backup"):
            try:
                manifest = self._read_manifest(path)
                values.append(
                    BackupInfo(
                        filename=path.name,
                        size_bytes=path.stat().st_size,
                        created_at=datetime.fromisoformat(cast(str, manifest["created_at"])),
                        reason=cast(str, manifest.get("reason", "manual")),
                    )
                )
            except (BackupError, KeyError, TypeError, ValueError):
                continue
        return sorted(values, key=lambda item: (item.created_at, item.filename), reverse=True)

    def backup_path(self, filename: str) -> Path:
        if Path(filename).name != filename or not filename.endswith(".backup"):
            raise BackupError("invalid backup filename")
        path = self._backup_dir / filename
        if not path.is_file():
            raise LookupError("backup not found")
        return path

    def stage_restore(self, archive_path: Path) -> RestoreStage:
        manifest = self._read_manifest(archive_path)
        self._restore_dir.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=self._restore_dir, prefix="staging-"))
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = set(archive.namelist())
                if members != {_MANIFEST_MEMBER, _DATABASE_MEMBER, _KEY_MEMBER}:
                    raise BackupError("backup archive contains unexpected files")
                if sum(item.file_size for item in archive.infolist()) > self._max_restore_bytes:
                    raise BackupError("backup archive expands beyond the restore limit")
                database_target = temporary / _DATABASE_MEMBER
                key_target = temporary / _KEY_MEMBER
                with archive.open(_DATABASE_MEMBER) as source, database_target.open("wb") as target:
                    shutil.copyfileobj(source, target)
                with archive.open(_KEY_MEMBER) as source, key_target.open("wb") as target:
                    shutil.copyfileobj(source, target)
            self._validate_database(database_target)
            key_bytes = key_target.read_bytes()
            if len(key_bytes) != 32:
                raise BackupError("backup master key is invalid")
            marker = {
                "archive_version": _ARCHIVE_VERSION,
                "backup_filename": archive_path.name,
                "created_at": cast(str, manifest["created_at"]),
            }
            (temporary / "pending.json").write_text(
                json.dumps(marker, sort_keys=True), encoding="utf-8"
            )
            pending = self._restore_dir / "pending"
            previous = self._restore_dir / "previous"
            if previous.exists():
                shutil.rmtree(previous)
            if pending.exists():
                os.replace(pending, previous)
            os.replace(temporary, pending)
            shutil.rmtree(previous, ignore_errors=True)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return RestoreStage(
            backup_filename=archive_path.name,
            created_at=datetime.fromisoformat(cast(str, manifest["created_at"])),
        )

    def apply_pending_restore(self) -> bool:
        pending = self._restore_dir / "pending"
        marker_path = pending / "pending.json"
        if not marker_path.is_file():
            return False
        database_source = pending / _DATABASE_MEMBER
        key_source = pending / _KEY_MEMBER
        self._validate_database(database_source)
        if len(key_source.read_bytes()) != 32:
            raise BackupError("pending restore master key is invalid")

        if self._database_path.exists() and self._master_key_file.exists():
            self.create_backup(reason="pre-restore")
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._master_key_file.parent.mkdir(parents=True, exist_ok=True)
        os.replace(database_source, self._database_path)
        os.replace(key_source, self._master_key_file)
        shutil.rmtree(pending)
        return True

    def prune(self) -> int:
        backups = self.list_backups()
        removed = 0
        for item in backups[self._retention_count :]:
            (self._backup_dir / item.filename).unlink(missing_ok=True)
            removed += 1
        return removed

    def _copy_database(self, destination: Path) -> None:
        if not self._database_path.is_file():
            raise BackupError("database file does not exist")
        with sqlite3.connect(self._database_path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        self._validate_database(destination)

    @staticmethod
    def _validate_database(path: Path) -> None:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                application_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
                ).fetchone()
        except sqlite3.Error as error:
            raise BackupError("backup database cannot be opened") from error
        if result != ("ok",) or application_table is None:
            raise BackupError("backup database failed validation")

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(path) as archive:
                raw = archive.read(_MANIFEST_MEMBER)
            value = cast(object, json.loads(raw))
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
            raise BackupError("backup archive is invalid") from error
        if not isinstance(value, dict):
            raise BackupError("backup manifest is invalid")
        manifest = cast(dict[str, Any], value)
        if (
            manifest.get("archive_version") != _ARCHIVE_VERSION
            or manifest.get("application") != "anime-rss-service"
            or not isinstance(manifest.get("created_at"), str)
        ):
            raise BackupError("backup archive version is not supported")
        return manifest
