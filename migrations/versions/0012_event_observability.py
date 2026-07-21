"""Persist event correlation and causation identifiers."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_observability"
down_revision: str | None = "0011_feed_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_integration_events") as batch:
        batch.add_column(sa.Column("correlation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("causation_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_runtime_integration_events_correlation_id",
        "runtime_integration_events",
        ["correlation_id"],
    )
    op.create_index(
        "ix_runtime_integration_events_causation_id",
        "runtime_integration_events",
        ["causation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_integration_events_causation_id",
        table_name="runtime_integration_events",
    )
    op.drop_index(
        "ix_runtime_integration_events_correlation_id",
        table_name="runtime_integration_events",
    )
    with op.batch_alter_table("runtime_integration_events") as batch:
        batch.drop_column("causation_id")
        batch.drop_column("correlation_id")
