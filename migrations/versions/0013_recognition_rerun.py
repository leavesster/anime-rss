"""Preserve explicit parser re-run attempts while keeping ingestion idempotent."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_recognition_rerun"
down_revision: str | None = "0012_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("match_attempts") as batch:
        batch.drop_constraint("uq_match_attempt_feed_entry", type_="unique")
        batch.add_column(
            sa.Column(
                "trigger",
                sa.String(24),
                nullable=False,
                server_default="initial",
            )
        )
    op.create_index(
        "uq_match_attempt_initial_feed_entry",
        "match_attempts",
        ["feed_entry_id"],
        unique=True,
        sqlite_where=sa.text("trigger = 'initial'"),
    )
    op.create_index(
        "ix_match_attempt_feed_parser_time",
        "match_attempts",
        ["feed_entry_id", "parser_version", "parsed_at"],
    )
    op.create_index(
        "ix_match_attempt_release_time",
        "match_attempts",
        ["release_id", "parsed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_attempt_release_time", table_name="match_attempts")
    op.drop_index("ix_match_attempt_feed_parser_time", table_name="match_attempts")
    op.drop_index("uq_match_attempt_initial_feed_entry", table_name="match_attempts")
    with op.batch_alter_table("match_attempts") as batch:
        batch.drop_column("trigger")
        batch.create_unique_constraint("uq_match_attempt_feed_entry", ["feed_entry_id"])
