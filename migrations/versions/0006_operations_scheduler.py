"""Persist scheduler executions, heartbeats, and recognition corrections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_operations_scheduler"
down_revision: str | None = "0005_download_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_job_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("job_kind", sa.String(80), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column("worker_id", sa.String(120), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["runtime_scheduled_jobs.id"], ondelete="CASCADE"),
    )
    for name in ("job_id", "job_kind", "worker_id", "status", "started_at"):
        op.create_index(f"ix_runtime_job_runs_{name}", "runtime_job_runs", [name])

    op.create_table(
        "runtime_scheduler_state",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("worker_id", sa.String(120), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("last_cycle_started_at", sa.String(32), nullable=True),
        sa.Column("last_cycle_finished_at", sa.String(32), nullable=True),
        sa.Column("last_success_at", sa.String(32), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("next_wake_at", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_runtime_scheduler_state_state", "runtime_scheduler_state", ["state"])

    op.create_table(
        "match_manual_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["match_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["match_attempts.id"], ondelete="CASCADE"),
    )
    for name in ("candidate_id", "attempt_id", "action"):
        op.create_index(f"ix_match_manual_actions_{name}", "match_manual_actions", [name])


def downgrade() -> None:
    op.drop_table("match_manual_actions")
    op.drop_table("runtime_scheduler_state")
    op.drop_table("runtime_job_runs")
