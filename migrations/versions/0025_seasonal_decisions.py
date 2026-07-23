"""Persist explicit seasonal anime dismissals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_seasonal_decisions"
down_revision: str | None = "0024_feed_source_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seasonal_decisions",
        sa.Column("bangumi_id", sa.Integer(), primary_key=True),
        sa.Column("decision", sa.String(24), nullable=False, server_default="dismissed"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint("decision IN ('dismissed')", name="ck_seasonal_decision"),
    )


def downgrade() -> None:
    op.drop_table("seasonal_decisions")
