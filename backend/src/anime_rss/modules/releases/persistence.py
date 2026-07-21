from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class ReleaseRecord(Base):
    __tablename__ = "release_releases"
    __table_args__ = (
        UniqueConstraint("identity_kind", "identity_value", name="uq_release_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_kind: Mapped[str] = mapped_column(String(16))
    identity_value: Mapped[str] = mapped_column(String(80))
    btih: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    btmh: Mapped[str | None] = mapped_column(String(68), nullable=True, index=True)
    automation_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)


class ReleaseSourceRecord(Base):
    __tablename__ = "release_sources"
    __table_args__ = (UniqueConstraint("release_id", "feed_entry_id", name="uq_release_source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    feed_entry_id: Mapped[str] = mapped_column(
        ForeignKey("feed_entries.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReleasePayloadRecord(Base):
    __tablename__ = "release_payloads"
    __table_args__ = (UniqueConstraint("release_id", "sha256", name="uq_release_payload"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="CASCADE"), index=True
    )
    feed_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("feed_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
