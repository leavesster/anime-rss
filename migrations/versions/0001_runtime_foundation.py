"""Create audit, integration-event, and durable-job tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_runtime_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])

    op.create_table(
        "runtime_integration_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_runtime_integration_events_name", "runtime_integration_events", ["name"])
    op.create_table(
        "runtime_integration_event_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("consumer", sa.String(120), nullable=False),
        sa.Column("processed_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["runtime_integration_events.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("event_id", "consumer", name="uq_event_consumer"),
    )
    op.create_index(
        "ix_runtime_integration_event_deliveries_event_id",
        "runtime_integration_event_deliveries",
        ["event_id"],
    )

    op.create_table(
        "runtime_scheduled_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_kind", sa.String(80), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_until", sa.String(32), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("job_kind", "dedupe_key", name="uq_scheduled_job"),
    )
    op.create_index("ix_runtime_scheduled_jobs_job_kind", "runtime_scheduled_jobs", ["job_kind"])
    op.create_index("ix_runtime_scheduled_jobs_due_at", "runtime_scheduled_jobs", ["due_at"])
    op.create_index(
        "ix_runtime_scheduled_jobs_lease_until", "runtime_scheduled_jobs", ["lease_until"]
    )


def downgrade() -> None:
    op.drop_table("runtime_scheduled_jobs")
    op.drop_table("runtime_integration_event_deliveries")
    op.drop_table("runtime_integration_events")
    op.drop_table("audit_events")
