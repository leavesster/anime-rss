"""Store navigable RSS item links without credentials or query data."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_feed_entry_public_links"
down_revision: str | None = "0022_candidate_title_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("feed_entries") as batch:
        batch.add_column(sa.Column("link_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feed_entries") as batch:
        batch.drop_column("link_url")
