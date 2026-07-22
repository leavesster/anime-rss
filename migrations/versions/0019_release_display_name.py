"""Store a human-readable name for BitTorrent releases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_release_display_name"
down_revision: str | None = "0018_download_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("release_releases") as batch:
        batch.add_column(sa.Column("display_name", sa.String(4096), nullable=True))
    op.execute(
        """
        UPDATE release_releases
        SET display_name = (
            SELECT feed_entries.title_raw
            FROM release_sources
            JOIN feed_entries ON feed_entries.id = release_sources.feed_entry_id
            WHERE release_sources.release_id = release_releases.id
            ORDER BY release_sources.observed_at ASC
            LIMIT 1
        )
        WHERE display_name IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("release_releases") as batch:
        batch.drop_column("display_name")
