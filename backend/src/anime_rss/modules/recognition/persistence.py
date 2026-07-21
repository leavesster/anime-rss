from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class MatchAttemptRecord(Base):
    __tablename__ = "match_attempts"
    __table_args__ = (
        Index(
            "uq_match_attempt_initial_feed_entry",
            "feed_entry_id",
            unique=True,
            sqlite_where=text("trigger = 'initial'"),
        ),
        Index(
            "ix_match_attempt_feed_parser_time",
            "feed_entry_id",
            "parser_version",
            "parsed_at",
        ),
        Index("ix_match_attempt_release_time", "release_id", "parsed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    feed_entry_id: Mapped[str] = mapped_column(
        ForeignKey("feed_entries.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(24), default="initial")
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
    __table_args__ = (
        Index(
            "uq_match_candidate_active_release",
            "release_id",
            unique=True,
            sqlite_where=text("superseded_by_candidate_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("match_attempts.id", ondelete="CASCADE"), index=True
    )
    supersedes_candidate_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    superseded_by_candidate_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
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


class ManualActionRecord(Base):
    __tablename__ = "match_manual_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("match_candidates.id", ondelete="CASCADE"), index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("match_attempts.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
