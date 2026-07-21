from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class EvaluationRecord(Base):
    __tablename__ = "select_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "candidate_id", name="uq_selection_subscription_candidate"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    release_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    eligible: Mapped[bool]
    preferred: Mapped[bool]
    hard_filter_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    rank: Mapped[list[int | str]] = mapped_column(JSON)
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    trigger: Mapped[str] = mapped_column(String(24))


class EpisodeSlotRecord(Base):
    __tablename__ = "select_episode_slots"
    __table_args__ = (
        UniqueConstraint("subscription_id", "episode_key", name="uq_selection_slot_episode"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    anime_title: Mapped[str] = mapped_column(String(300))
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    fallback_deadline: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, index=True
    )
    best_candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    selected_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DecisionRecord(Base):
    __tablename__ = "select_decisions"
    __table_args__ = (
        UniqueConstraint(
            "slot_id", "candidate_id", "kind", name="uq_selection_decision_candidate_kind"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slot_id: Mapped[str] = mapped_column(
        ForeignKey("select_episode_slots.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    release_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[dict[str, Any]] = mapped_column(JSON)
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ManualActionRecord(Base):
    __tablename__ = "select_manual_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("sub_subscriptions.id", ondelete="CASCADE"), index=True
    )
    slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("select_episode_slots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    episode_key: Mapped[str] = mapped_column(String(52), index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    release_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
