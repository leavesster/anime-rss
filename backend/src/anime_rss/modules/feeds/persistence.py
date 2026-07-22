from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now
from anime_rss.modules.feeds.domain import FeedHealth


class FeedRecord(Base):
    __tablename__ = "feed_feeds"
    __table_args__ = (
        CheckConstraint(
            "interval_seconds >= 300 AND interval_seconds <= 3600",
            name="ck_feed_interval",
        ),
        Index("uq_feed_url_fingerprint", "url_fingerprint", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    url_redacted: Mapped[str] = mapped_column(String(2048))
    url_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    endpoint_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    headers_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    interval_seconds: Mapped[int] = mapped_column(default=600)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(512), nullable=True)
    health: Mapped[str] = mapped_column(String(40), default=FeedHealth.UNKNOWN.value)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class FeedFetchRecord(Base):
    __tablename__ = "feed_fetches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    feed_id: Mapped[str] = mapped_column(
        ForeignKey("feed_feeds.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entry_count: Mapped[int] = mapped_column(default=0)
    new_entry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime())


class FeedEntryRecord(Base):
    __tablename__ = "feed_entries"
    __table_args__ = (UniqueConstraint("feed_id", "guid_hash", name="uq_feed_entry_guid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    feed_id: Mapped[str] = mapped_column(
        ForeignKey("feed_feeds.id", ondelete="CASCADE"), index=True
    )
    source_guid: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    guid_hash: Mapped[str] = mapped_column(String(64))
    identity_strength: Mapped[str] = mapped_column(String(16))
    title_raw: Mapped[str] = mapped_column(String(4096))
    title_normalized: Mapped[str] = mapped_column(String(4096))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    link_redacted: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    torrent_reference_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    release_status: Mapped[str] = mapped_column(String(32), default="pending")
    release_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
