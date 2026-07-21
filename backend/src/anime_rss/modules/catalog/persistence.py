from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class AnimeRecord(Base):
    __tablename__ = "catalog_anime"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bangumi_id: Mapped[int | None] = mapped_column(unique=True, nullable=True)
    primary_title: Mapped[str] = mapped_column(String(300))
    title_zh: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title_ja: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    air_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    episode_count: Mapped[int | None] = mapped_column(nullable=True)
    airing_weekday: Mapped[int | None] = mapped_column(nullable=True)
    airing_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    schedule_timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    schedule_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AnimeTitleRecord(Base):
    __tablename__ = "catalog_titles"
    __table_args__ = (
        UniqueConstraint("anime_id", "normalized", name="uq_catalog_title_anime_normalized"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    anime_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_anime.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    normalized: Mapped[str] = mapped_column(String(300), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class MetadataCacheRecord(Base):
    __tablename__ = "catalog_metadata_cache"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(24))
    request_key: Mapped[str] = mapped_column(String(300), unique=True)
    payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
