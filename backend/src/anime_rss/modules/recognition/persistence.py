from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class MatchAttemptRecord(Base):
    __tablename__ = "match_attempts"
    __table_args__ = (UniqueConstraint("feed_entry_id", name="uq_match_attempt_feed_entry"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    feed_entry_id: Mapped[str] = mapped_column(
        ForeignKey("feed_entries.id", ondelete="CASCADE"), index=True
    )
    parser_version: Mapped[str] = mapped_column(String(40))
    source_title: Mapped[str] = mapped_column(String(4096))
    release_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    series_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    series_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_start: Mapped[str | None] = mapped_column(String(24), nullable=True)
    episode_end: Mapped[str | None] = mapped_column(String(24), nullable=True)
    episode_key: Mapped[str | None] = mapped_column(String(52), nullable=True, index=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    subtitle_language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_kind: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[str] = mapped_column(String(16), index=True)
    reason_code: Mapped[str] = mapped_column(String(80))
    parsed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CandidateRecord(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (UniqueConstraint("release_id", name="uq_match_candidate_release"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("match_attempts.id", ondelete="CASCADE"), unique=True
    )
    source_title: Mapped[str] = mapped_column(String(4096))
    series_title: Mapped[str] = mapped_column(String(300))
    series_key: Mapped[str] = mapped_column(String(300), index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_start: Mapped[str] = mapped_column(String(24))
    episode_end: Mapped[str | None] = mapped_column(String(24), nullable=True)
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    release_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    subtitle_language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_kind: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[str] = mapped_column(String(16), index=True)
    recognition_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
