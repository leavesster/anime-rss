"""Require two successful misses before external removal."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_download_reconciliation"
down_revision: str | None = "0017_http_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("download_tasks") as batch:
        batch.add_column(sa.Column("missing_observation_count", sa.Integer(), nullable=True))
    op.execute("UPDATE download_tasks SET missing_observation_count = 0")
    with op.batch_alter_table("download_tasks") as batch:
        batch.alter_column(
            "missing_observation_count",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("download_tasks") as batch:
        batch.drop_column("missing_observation_count")
