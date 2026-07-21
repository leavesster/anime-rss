from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class ExpectedEpisodeRecord(Base):
    __tablename__ = "schedule_expected_episodes"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "episode_key",
            name="uq_schedule_expected_subscription_episode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    anime_id: Mapped[str] = mapped_column(String(36), index=True)
    anime_title: Mapped[str] = mapped_column(String(300))
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    expected_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    state: Mapped[str] = mapped_column(String(24), index=True)
    has_acceptable_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_source: Mapped[str] = mapped_column(String(24))
    missing_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EpisodeScheduleOverrideRecord(Base):
    __tablename__ = "schedule_episode_overrides"
    __table_args__ = (
        UniqueConstraint(
            "anime_id",
            "episode_key",
            name="uq_schedule_override_anime_episode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    anime_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_anime.id", ondelete="CASCADE"), index=True
    )
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    expected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
