from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANIME_RSS_", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    master_key_file: Path | None = None
    log_level: str = "INFO"
    log_retention_days: int = Field(default=14, ge=1, le=365)
    auto_migrate: bool = True
    migration_lock_timeout_seconds: float = Field(default=60.0, ge=0.1, le=600.0)
    web_dist_dir: Path | None = None

    feed_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    feed_read_timeout_seconds: float = Field(default=30.0, gt=0)
    feed_max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    selection_poll_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    download_poll_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    scheduler_poll_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    scheduler_lease_seconds: int = Field(default=60, ge=10, le=600)
    auth_enabled: bool = True
    auth_cookie_secure: bool = False
    auth_session_days: int = Field(default=30, ge=1, le=365)
    browser_trusted_hosts: str = "localhost,testserver"
    browser_trusted_origins: str = ""
    auth_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    auth_rate_limit_window_seconds: int = Field(default=300, ge=1, le=3600)
    connection_test_rate_limit_attempts: int = Field(default=10, ge=1, le=100)
    connection_test_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    backup_interval_hours: int = Field(default=24, ge=1, le=168)
    backup_retention_count: int = Field(default=7, ge=1, le=365)
    backup_max_restore_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)
    feed_failure_retention_days: int = Field(default=7, ge=1, le=365)
    unmatched_retention_days: int = Field(default=90, ge=1, le=3650)
    operational_history_retention_days: int = Field(default=90, ge=1, le=3650)
    retention_interval_hours: int = Field(default=24, ge=1, le=168)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'anime-rss.sqlite3').absolute()}"

    @property
    def resolved_master_key_file(self) -> Path:
        return self.master_key_file or self.data_dir / "keys" / "master.key"

    @property
    def resolved_browser_trusted_hosts(self) -> tuple[str, ...]:
        return tuple(
            value.strip() for value in self.browser_trusted_hosts.split(",") if value.strip()
        )

    @property
    def resolved_browser_trusted_origins(self) -> tuple[str, ...]:
        return tuple(
            value.strip() for value in self.browser_trusted_origins.split(",") if value.strip()
        )
