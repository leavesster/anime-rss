"""Add durable HTTP idempotency response records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_http_contracts"
down_revision: str | None = "0016_manual_downloads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_anime") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=True))
    op.execute("UPDATE catalog_anime SET version = 1 WHERE version IS NULL")
    with op.batch_alter_table("catalog_anime") as batch:
        batch.alter_column("version", existing_type=sa.Integer(), nullable=False)
    op.create_table(
        "http_idempotency_records",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.LargeBinary(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "state IN ('processing','completed')",
            name="ck_http_idempotency_state",
        ),
    )
    op.create_index(
        "ix_http_idempotency_records_expires_at",
        "http_idempotency_records",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("http_idempotency_records")
    with op.batch_alter_table("catalog_anime") as batch:
        batch.drop_column("version")
