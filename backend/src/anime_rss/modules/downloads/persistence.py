from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class DownloaderConfigRecord(Base):
    __tablename__ = "download_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    adapter: Mapped[str] = mapped_column(String(32), default="qbittorrent")
    base_url_redacted: Mapped[str] = mapped_column(String(2048))
    base_url_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    username_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    password_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    default_save_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_tags: Mapped[list[str]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DownloadTaskRecord(Base):
    __tablename__ = "download_tasks"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_download_task_decision"),
        UniqueConstraint("idempotency_key", name="uq_download_task_idempotency"),
        CheckConstraint(
            "state IN ('planned','retrying','submitting','submitted','downloading',"
            "'paused','completed','failed','externally_removed','canceling','superseded')",
            name="ck_download_task_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("select_decisions.id", ondelete="CASCADE"), index=True
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_releases.id", ondelete="RESTRICT"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    info_hash: Mapped[str] = mapped_column(String(80), index=True)
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    adapter: Mapped[str] = mapped_column(String(32), default="qbittorrent")
    idempotency_key: Mapped[str] = mapped_column(String(180))
    state: Mapped[str] = mapped_column(String(32), index=True)
    requested_save_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    actual_save_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_once: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    supersedes_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_by_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    operation_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DownloadAttemptRecord(Base):
    __tablename__ = "download_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("download_tasks.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
