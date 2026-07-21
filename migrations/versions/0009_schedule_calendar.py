"""Add instance preferences and airing schedule projections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_schedule_calendar"
down_revision: str | None = "0008_release_acceptance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sys_instance_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("interface_language", sa.String(16), nullable=False),
        sa.Column("missing_episode_grace_hours", sa.Integer(), nullable=False),
        sa.Column("setup_completed_steps", sa.JSON(), nullable=False),
        sa.Column("setup_completed", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    with op.batch_alter_table("catalog_anime") as batch:
        batch.add_column(sa.Column("airing_weekday", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("airing_time", sa.String(5), nullable=True))
        batch.add_column(sa.Column("schedule_timezone", sa.String(80), nullable=True))
        batch.add_column(sa.Column("schedule_source", sa.String(24), nullable=True))
        batch.add_column(sa.Column("schedule_updated_at", sa.String(32), nullable=True))
    op.create_table(
        "schedule_expected_episodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("anime_id", sa.String(36), nullable=False),
        sa.Column("anime_title", sa.String(300), nullable=False),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("expected_at", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("has_acceptable_candidate", sa.Boolean(), nullable=False),
        sa.Column("schedule_source", sa.String(24), nullable=False),
        sa.Column("missing_notified_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "subscription_id",
            "episode_key",
            name="uq_schedule_expected_subscription_episode",
        ),
    )
    for name in (
        "subscription_id",
        "anime_id",
        "episode_key",
        "expected_at",
        "state",
    ):
        op.create_index(
            f"ix_schedule_expected_episodes_{name}", "schedule_expected_episodes", [name]
        )


def downgrade() -> None:
    op.drop_table("schedule_expected_episodes")
    with op.batch_alter_table("catalog_anime") as batch:
        batch.drop_column("schedule_updated_at")
        batch.drop_column("schedule_source")
        batch.drop_column("schedule_timezone")
        batch.drop_column("airing_time")
        batch.drop_column("airing_weekday")
    op.drop_table("sys_instance_settings")
