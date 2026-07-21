from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANIME_RSS_", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    master_key_file: Path | None = None
    log_level: str = "INFO"
    auto_migrate: bool = True
    web_dist_dir: Path | None = None

    feed_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    feed_read_timeout_seconds: float = Field(default=30.0, gt=0)
    feed_max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    selection_poll_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    download_poll_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    scheduler_poll_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    scheduler_lease_seconds: int = Field(default=60, ge=10, le=600)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'anime-rss.sqlite3').absolute()}"

    @property
    def resolved_master_key_file(self) -> Path:
        return self.master_key_file or self.data_dir / "keys" / "master.key"
