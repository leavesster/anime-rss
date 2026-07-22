import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from anime_rss.config import Settings
from anime_rss.infrastructure.migrations import inspect_migrations
from anime_rss.modules.system.backup import BackupError, BackupService

DoctorStatus = Literal["pass", "warning", "fail"]


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    key: str
    status: DoctorStatus
    detail: str


class DoctorService:
    """Read-only deployment diagnostics for an installation or empty data directory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self) -> tuple[DoctorCheck, ...]:
        checks = [self._check_data_directory()]
        try:
            database_path = BackupService.database_path(self._settings.resolved_database_url)
        except BackupError as error:
            checks.append(DoctorCheck("database", "fail", str(error)))
            database_path = None

        database_exists = database_path is not None and database_path.is_file()
        if database_path is not None:
            checks.append(self._check_database(database_path))
            checks.append(self._check_schema(database_path))
        checks.append(self._check_master_key(database_exists))
        checks.append(self._check_restore_state())
        checks.append(self._check_web_assets())
        return tuple(checks)

    def _check_data_directory(self) -> DoctorCheck:
        path = self._settings.data_dir.absolute()
        if path.exists():
            if not path.is_dir():
                return DoctorCheck("data_directory", "fail", f"not a directory: {path}")
            if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                return DoctorCheck("data_directory", "fail", f"not readable and writable: {path}")
            return DoctorCheck("data_directory", "pass", f"readable and writable: {path}")

        parent = self._nearest_existing_parent(path)
        if parent.is_dir() and os.access(parent, os.W_OK | os.X_OK):
            return DoctorCheck("data_directory", "pass", f"will be created below: {parent}")
        return DoctorCheck("data_directory", "fail", f"cannot create: {path}")

    @staticmethod
    def _nearest_existing_parent(path: Path) -> Path:
        current = path
        while not current.exists() and current != current.parent:
            current = current.parent
        return current

    @staticmethod
    def _check_database(path: Path) -> DoctorCheck:
        if not path.exists():
            return DoctorCheck("database", "pass", "not initialized")
        if not path.is_file():
            return DoctorCheck("database", "fail", f"not a regular file: {path}")
        encoded = quote(str(path.resolve()), safe="/")
        try:
            with sqlite3.connect(f"file:{encoded}?mode=ro", uri=True) as connection:
                connection.execute("PRAGMA query_only = ON")
                result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as error:
            return DoctorCheck("database", "fail", f"cannot open SQLite database: {error}")
        if result != ("ok",):
            return DoctorCheck("database", "fail", f"SQLite quick_check returned: {result!r}")
        return DoctorCheck("database", "pass", f"SQLite quick_check passed: {path}")

    def _check_schema(self, database_path: Path) -> DoctorCheck:
        if not database_path.is_file():
            return DoctorCheck("schema", "pass", "not initialized")
        try:
            plan = inspect_migrations(self._settings.resolved_database_url)
        except Exception as error:
            return DoctorCheck("schema", "fail", f"cannot inspect migration state: {error}")
        current = ",".join(plan.current_heads) or "none"
        target = ",".join(plan.target_heads) or "none"
        if plan.required:
            return DoctorCheck("schema", "fail", f"migration required: {current} -> {target}")
        return DoctorCheck("schema", "pass", f"at head: {current}")

    def _check_master_key(self, database_exists: bool) -> DoctorCheck:
        path = self._settings.resolved_master_key_file
        if not path.exists():
            if database_exists:
                return DoctorCheck("master_key", "fail", f"missing for existing database: {path}")
            return DoctorCheck("master_key", "pass", "not initialized")
        if not path.is_file():
            return DoctorCheck("master_key", "fail", f"not a regular file: {path}")
        try:
            key_size = path.stat().st_size
        except OSError as error:
            return DoctorCheck("master_key", "fail", f"cannot inspect key: {error}")
        if key_size != 32:
            return DoctorCheck("master_key", "fail", f"expected 32 bytes, found {key_size}")
        permissions = stat.S_IMODE(path.stat().st_mode)
        if permissions & 0o077:
            return DoctorCheck(
                "master_key", "fail", f"permissions must be 0600, found {permissions:04o}"
            )
        return DoctorCheck("master_key", "pass", f"32 bytes with {permissions:04o} permissions")

    def _check_restore_state(self) -> DoctorCheck:
        marker = self._settings.data_dir / "restore" / "pending" / "pending.json"
        if marker.exists():
            return DoctorCheck("restore_state", "fail", "restore is staged; restart is required")
        return DoctorCheck("restore_state", "pass", "no pending restore")

    def _check_web_assets(self) -> DoctorCheck:
        index = self._settings.resolved_web_dist_dir / "index.html"
        if index.is_file():
            return DoctorCheck("web_assets", "pass", f"found: {index}")
        return DoctorCheck(
            "web_assets",
            "warning",
            f"not built at {index}; API-only development remains available",
        )


def render_doctor(checks: tuple[DoctorCheck, ...]) -> str:
    return "\n".join(f"{check.status.upper():7} {check.key}: {check.detail}" for check in checks)
