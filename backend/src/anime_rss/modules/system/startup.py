import fcntl
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from anime_rss.infrastructure.migrations import (
    MigrationPlan,
    inspect_migrations,
    run_migrations,
)
from anime_rss.modules.system.backup import BackupInfo, BackupService


class MigrationLockError(RuntimeError):
    pass


class MigrationFileLock:
    """Process-scoped lock that serializes restore and schema migration work."""

    def __init__(self, path: Path, *, timeout_seconds: float) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "MigrationFileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    handle.close()
                    raise MigrationLockError(
                        f"timed out waiting for migration lock: {self._path}"
                    ) from None
                time.sleep(min(0.05, remaining))
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n".encode())
        handle.flush()
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


@dataclass(frozen=True, slots=True)
class StartupPreparation:
    restored: bool
    migration_plan: MigrationPlan
    migration_backup: BackupInfo | None


class StartupService:
    def __init__(
        self,
        *,
        database_url: str,
        backups: BackupService,
        lock_timeout_seconds: float = 60.0,
        migration_inspector: Callable[[str], MigrationPlan] = inspect_migrations,
        migration_runner: Callable[[str], None] = run_migrations,
    ) -> None:
        database_path = BackupService.database_path(database_url)
        self._database_url = database_url
        self._backups = backups
        self._lock = MigrationFileLock(
            database_path.with_name(".anime-rss-migration.lock"),
            timeout_seconds=lock_timeout_seconds,
        )
        self._migration_inspector = migration_inspector
        self._migration_runner = migration_runner

    def prepare(self, *, auto_migrate: bool) -> StartupPreparation:
        with self._lock:
            restored = self._backups.apply_pending_restore()
            plan = self._migration_inspector(self._database_url)
            migration_backup = None
            if auto_migrate and plan.required:
                if plan.current_heads:
                    migration_backup = self._backups.create_backup(reason="pre-migration")
                self._migration_runner(self._database_url)
                plan = self._migration_inspector(self._database_url)
                if plan.required:
                    raise RuntimeError("database migration did not reach the target revision")
            return StartupPreparation(
                restored=restored,
                migration_plan=plan,
                migration_backup=migration_backup,
            )
