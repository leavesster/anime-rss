"""Persist dismissed unmatched recognition releases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_recognition_dismissals"
down_revision: str | None = "0019_release_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_dismissed_releases",
        sa.Column("release_id", sa.String(36), primary_key=True),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["match_attempts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_match_dismissed_releases_attempt_id",
        "match_dismissed_releases",
        ["attempt_id"],
    )


def downgrade() -> None:
    op.drop_table("match_dismissed_releases")
