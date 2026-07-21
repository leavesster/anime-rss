from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class SubscriptionRecord(Base):
    __tablename__ = "sub_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('following','paused','completed','archived')",
            name="ck_subscription_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    anime_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_anime.id", ondelete="CASCADE"), unique=True, index=True
    )
    anime_title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(24), index=True)
    match_keys: Mapped[list[str]] = mapped_column(JSON)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)
    use_global_rules: Mapped[bool] = mapped_column(default=False)
    activation_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    save_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class SubscriptionEpochRecord(Base):
    __tablename__ = "sub_subscription_epochs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reason: Mapped[str] = mapped_column(String(40))


class PreferenceProfileRecord(Base):
    __tablename__ = "sub_preference_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
