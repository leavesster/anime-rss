"""Add versioned per-episode broadcast schedule overrides."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_schedule_overrides"
down_revision: str | None = "0013_recognition_rerun"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_episode_overrides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("anime_id", sa.String(36), nullable=False),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("expected_at", sa.String(32), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["anime_id"], ["catalog_anime.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "anime_id",
            "episode_key",
            name="uq_schedule_override_anime_episode",
        ),
    )
    op.create_index(
        "ix_schedule_episode_overrides_anime_id",
        "schedule_episode_overrides",
        ["anime_id"],
    )
    op.create_index(
        "ix_schedule_episode_overrides_episode_key",
        "schedule_episode_overrides",
        ["episode_key"],
    )


def downgrade() -> None:
    op.drop_table("schedule_episode_overrides")
