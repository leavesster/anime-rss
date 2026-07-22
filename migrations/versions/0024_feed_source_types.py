"""Distinguish aggregate feeds from feeds dedicated to one anime."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_feed_source_types"
down_revision: str | None = "0023_feed_entry_public_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("feed_feeds") as batch:
        batch.add_column(
            sa.Column(
                "source_type",
                sa.String(24),
                nullable=False,
                server_default="aggregate",
            )
        )
        batch.create_check_constraint(
            "ck_feed_source_type",
            "source_type IN ('aggregate', 'single_anime')",
        )
        batch.create_index("ix_feed_feeds_source_type", ["source_type"])


def downgrade() -> None:
    with op.batch_alter_table("feed_feeds") as batch:
        batch.drop_index("ix_feed_feeds_source_type")
        batch.drop_constraint("ck_feed_source_type", type_="check")
        batch.drop_column("source_type")
