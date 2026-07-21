"""Add global preferences and auditable episode controls."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_release_acceptance"
down_revision: str | None = "0007_product_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sub_preference_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.add_column(
        "sub_subscriptions",
        sa.Column("use_global_rules", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "select_manual_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=True),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=True),
        sa.Column("release_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("reason", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["slot_id"], ["select_episode_slots.id"], ondelete="SET NULL"),
    )
    for name in ("subscription_id", "slot_id", "episode_key", "candidate_id", "action"):
        op.create_index(f"ix_select_manual_actions_{name}", "select_manual_actions", [name])


def downgrade() -> None:
    op.drop_table("select_manual_actions")
    op.drop_column("sub_subscriptions", "use_global_rules")
    op.drop_table("sub_preference_profiles")
