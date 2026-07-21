"""Create catalog, subscriptions, and deterministic selection state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_subscription_selection"
down_revision: str | None = "0003_release_recognition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_anime",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bangumi_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("primary_title", sa.String(300), nullable=False),
        sa.Column("title_zh", sa.String(300), nullable=True),
        sa.Column("title_ja", sa.String(300), nullable=True),
        sa.Column("title_en", sa.String(300), nullable=True),
        sa.Column("summary", sa.String(4000), nullable=True),
        sa.Column("air_date", sa.String(10), nullable=True),
        sa.Column("episode_count", sa.Integer(), nullable=True),
        sa.Column("cover_url", sa.String(2048), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "catalog_titles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("anime_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("normalized", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["anime_id"], ["catalog_anime.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("anime_id", "normalized", name="uq_catalog_title_anime_normalized"),
    )
    op.create_index("ix_catalog_titles_anime_id", "catalog_titles", ["anime_id"])
    op.create_index("ix_catalog_titles_normalized", "catalog_titles", ["normalized"])
    op.create_table(
        "catalog_metadata_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("request_key", sa.String(300), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_catalog_metadata_cache_expires_at", "catalog_metadata_cache", ["expires_at"]
    )

    op.create_table(
        "sub_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("anime_id", sa.String(36), nullable=False),
        sa.Column("anime_title", sa.String(300), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("match_keys", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("activation_at", sa.String(32), nullable=False),
        sa.Column("save_path", sa.String(1024), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "state IN ('following','paused','completed','archived')",
            name="ck_subscription_state",
        ),
        sa.ForeignKeyConstraint(["anime_id"], ["catalog_anime.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sub_subscriptions_anime_id", "sub_subscriptions", ["anime_id"], unique=True)
    op.create_index("ix_sub_subscriptions_state", "sub_subscriptions", ["state"])
    op.create_index("ix_sub_subscriptions_activation_at", "sub_subscriptions", ["activation_at"])
    op.create_table(
        "sub_subscription_epochs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("ended_at", sa.String(32), nullable=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_sub_subscription_epochs_subscription_id",
        "sub_subscription_epochs",
        ["subscription_id"],
    )

    op.create_table(
        "select_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("preferred", sa.Boolean(), nullable=False),
        sa.Column("hard_filter_results", sa.JSON(), nullable=False),
        sa.Column("rank", sa.JSON(), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "subscription_id", "candidate_id", name="uq_selection_subscription_candidate"
        ),
    )
    for name in ("subscription_id", "candidate_id", "release_id", "episode_key"):
        op.create_index(f"ix_select_evaluations_{name}", "select_evaluations", [name])

    op.create_table(
        "select_episode_slots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("anime_title", sa.String(300), nullable=False),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("fallback_deadline", sa.String(32), nullable=True),
        sa.Column("best_candidate_id", sa.String(36), nullable=True),
        sa.Column("selected_decision_id", sa.String(36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("subscription_id", "episode_key", name="uq_selection_slot_episode"),
    )
    for name in ("subscription_id", "episode_key", "state", "fallback_deadline"):
        op.create_index(f"ix_select_episode_slots_{name}", "select_episode_slots", [name])

    op.create_table(
        "select_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slot_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("reason", sa.JSON(), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False),
        sa.Column("candidate_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["select_episode_slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "slot_id", "candidate_id", "kind", name="uq_selection_decision_candidate_kind"
        ),
    )
    for name in (
        "slot_id",
        "subscription_id",
        "episode_key",
        "candidate_id",
        "release_id",
        "kind",
    ):
        op.create_index(f"ix_select_decisions_{name}", "select_decisions", [name])


def downgrade() -> None:
    op.drop_table("select_decisions")
    op.drop_table("select_episode_slots")
    op.drop_table("select_evaluations")
    op.drop_table("sub_subscription_epochs")
    op.drop_table("sub_subscriptions")
    op.drop_table("catalog_metadata_cache")
    op.drop_table("catalog_titles")
    op.drop_table("catalog_anime")
