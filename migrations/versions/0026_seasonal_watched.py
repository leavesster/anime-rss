"""Allow explicit watched decisions for seasonal anime."""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_seasonal_watched"
down_revision: str | None = "0025_seasonal_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("seasonal_decisions") as batch:
        batch.drop_constraint("ck_seasonal_decision", type_="check")
        batch.create_check_constraint(
            "ck_seasonal_decision",
            "decision IN ('dismissed', 'watched')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM seasonal_decisions WHERE decision = 'watched'")
    with op.batch_alter_table("seasonal_decisions") as batch:
        batch.drop_constraint("ck_seasonal_decision", type_="check")
        batch.create_check_constraint(
            "ck_seasonal_decision",
            "decision IN ('dismissed')",
        )
