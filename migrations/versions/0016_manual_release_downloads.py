"""Allow durable manual download tasks for unsupported releases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_manual_downloads"
down_revision: str | None = "0015_episode_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("download_tasks") as batch:
        batch.add_column(sa.Column("origin_kind", sa.String(32), nullable=True))
    op.execute(
        "UPDATE download_tasks SET origin_kind = 'selection_decision' WHERE origin_kind IS NULL"
    )
    with op.batch_alter_table("download_tasks") as batch:
        batch.alter_column("origin_kind", existing_type=sa.String(32), nullable=False)
        batch.alter_column("decision_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("subscription_id", existing_type=sa.String(36), nullable=True)
        batch.create_check_constraint(
            "ck_download_task_origin",
            "(origin_kind = 'selection_decision' AND decision_id IS NOT NULL "
            "AND subscription_id IS NOT NULL) OR "
            "(origin_kind = 'manual_release' AND decision_id IS NULL "
            "AND subscription_id IS NULL)",
        )
    op.create_index("ix_download_tasks_origin_kind", "download_tasks", ["origin_kind"])


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM download_attempts WHERE task_id IN "
            "(SELECT id FROM download_tasks WHERE origin_kind = 'manual_release')"
        )
    )
    connection.execute(sa.text("DELETE FROM download_tasks WHERE origin_kind = 'manual_release'"))
    op.drop_index("ix_download_tasks_origin_kind", table_name="download_tasks")
    with op.batch_alter_table("download_tasks") as batch:
        batch.drop_constraint("ck_download_task_origin", type_="check")
        batch.alter_column("decision_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("subscription_id", existing_type=sa.String(36), nullable=False)
        batch.drop_column("origin_kind")
