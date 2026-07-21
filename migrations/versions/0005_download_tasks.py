"""Add encrypted qBittorrent configuration and reconciled download tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_download_tasks"
down_revision: str | None = "0004_subscription_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("adapter", sa.String(32), nullable=False),
        sa.Column("base_url_redacted", sa.String(2048), nullable=False),
        sa.Column("base_url_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("username_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("default_category", sa.String(120), nullable=True),
        sa.Column("default_tags", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_tested_at", sa.String(32), nullable=True),
        sa.Column("last_success_at", sa.String(32), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "download_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("info_hash", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=True),
        sa.Column("adapter", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("requested_save_path", sa.String(1024), nullable=True),
        sa.Column("actual_save_path", sa.String(1024), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("observed_once", sa.Boolean(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("supersedes_decision_id", sa.String(36), nullable=True),
        sa.Column("superseded_by_decision_id", sa.String(36), nullable=True),
        sa.Column("superseded_at", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.String(32), nullable=True),
        sa.Column("last_observed_at", sa.String(32), nullable=True),
        sa.Column("operation_started_at", sa.String(32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "state IN ('planned','retrying','submitting','submitted','downloading',"
            "'paused','completed','failed','externally_removed','canceling','superseded')",
            name="ck_download_task_state",
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["select_decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("decision_id", name="uq_download_task_decision"),
        sa.UniqueConstraint("idempotency_key", name="uq_download_task_idempotency"),
    )
    for name in (
        "decision_id",
        "release_id",
        "subscription_id",
        "info_hash",
        "external_id",
        "state",
        "cancellation_requested",
        "next_retry_at",
    ):
        op.create_index(f"ix_download_tasks_{name}", "download_tasks", [name])
    op.create_table(
        "download_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["download_tasks.id"], ondelete="CASCADE"),
    )
    for name in ("task_id", "operation", "status"):
        op.create_index(f"ix_download_attempts_{name}", "download_attempts", [name])


def downgrade() -> None:
    op.drop_table("download_attempts")
    op.drop_table("download_tasks")
    op.drop_table("download_configs")
