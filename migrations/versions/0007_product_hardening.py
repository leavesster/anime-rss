"""Add administrator sessions and durable notifications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_product_hardening"
down_revision: str | None = "0006_operations_scheduler"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sys_admin_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("password_changed_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "sys_admin_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("last_seen_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_sys_admin_sessions_account_id", "sys_admin_sessions", ["account_id"])
    op.create_index(
        "ix_sys_admin_sessions_token_hash",
        "sys_admin_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index("ix_sys_admin_sessions_expires_at", "sys_admin_sessions", ["expires_at"])

    op.create_table(
        "notify_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("webhook_enabled", sa.Boolean(), nullable=False),
        sa.Column("webhook_url_redacted", sa.String(2048), nullable=True),
        sa.Column("webhook_url_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("bearer_token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_tested_at", sa.String(32), nullable=True),
        sa.Column("last_success_at", sa.String(32), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "notify_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=True),
        sa.Column("entity_id", sa.String(80), nullable=True),
        sa.Column("read_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_notify_notifications_source_event_id",
        "notify_notifications",
        ["source_event_id"],
        unique=True,
    )
    for name in ("kind", "level", "read_at", "created_at"):
        op.create_index(f"ix_notify_notifications_{name}", "notify_notifications", [name])
    op.create_table(
        "notify_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notification_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("delivered_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["notify_notifications.id"], ondelete="CASCADE"
        ),
    )
    for name in ("notification_id", "channel", "state", "next_attempt_at"):
        op.create_index(f"ix_notify_attempts_{name}", "notify_attempts", [name])


def downgrade() -> None:
    op.drop_table("notify_attempts")
    op.drop_table("notify_notifications")
    op.drop_table("notify_configs")
    op.drop_table("sys_admin_sessions")
    op.drop_table("sys_admin_accounts")
