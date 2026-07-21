"""Preserve existing installations when guided setup becomes mandatory."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0010_guided_setup"
down_revision: str | None = "0009_schedule_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPLETED_STEPS = [
    "administrator",
    "instance_preferences",
    "qbittorrent_connection",
    "download_defaults",
    "feed",
    "global_preferences",
    "subscription",
    "candidate_preview",
]


def upgrade() -> None:
    with op.batch_alter_table("download_configs") as batch:
        batch.add_column(sa.Column("default_save_path", sa.String(1024), nullable=True))

    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM sys_admin_accounts LIMIT 1")).first() is None:
        return

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    steps = json.dumps(_COMPLETED_STEPS)
    updated = connection.execute(
        sa.text(
            """
            UPDATE sys_instance_settings
            SET setup_completed_steps = :steps,
                setup_completed = 1,
                version = version + 1,
                updated_at = :now
            WHERE id = 'default'
            """
        ),
        {"steps": steps, "now": now},
    )
    if updated.rowcount:
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO sys_instance_settings (
                id, timezone, interface_language, missing_episode_grace_hours,
                setup_completed_steps, setup_completed, version, created_at, updated_at
            ) VALUES (
                'default', 'Asia/Shanghai', 'zh-CN', 24,
                :steps, 1, 1, :now, :now
            )
            """
        ),
        {"steps": steps, "now": now},
    )


def downgrade() -> None:
    # Setup completion may have changed after this migration; never erase user progress.
    with op.batch_alter_table("download_configs") as batch:
        batch.drop_column("default_save_path")
