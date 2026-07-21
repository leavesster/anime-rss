"""Add atomic episode-span coverage and overlap evidence."""

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "0015_episode_coverage"
down_revision: str | None = "0014_schedule_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _span(key: str) -> list[tuple[str, int]]:
    parts = key.split("-", 1)
    try:
        start = Decimal(parts[0])
        end = Decimal(parts[1]) if len(parts) == 2 else start
    except InvalidOperation:
        return []
    if any(
        not isinstance(value.as_tuple().exponent, int) or value.as_tuple().exponent < -3
        for value in (start, end)
    ):
        return []
    start_millis = int(start * 1000)
    end_millis = int(end * 1000)
    if start_millis < 0 or end_millis < start_millis:
        return []
    values: list[tuple[str, int]] = []
    covered_values = list(range(start_millis, end_millis + 1, 1000))
    if covered_values[-1] != end_millis:
        covered_values.append(end_millis)
    for value in covered_values:
        rendered = format(Decimal(value) / 1000, "f").rstrip("0").rstrip(".")
        values.append((rendered, value))
    return values if len(values) <= 100 else []


def upgrade() -> None:
    op.add_column(
        "select_evaluations",
        sa.Column("coverage_status", sa.String(24), nullable=False, server_default="none"),
    )
    op.add_column(
        "select_evaluations",
        sa.Column("covered_episode_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "select_evaluations",
        sa.Column("already_covered_episode_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "select_episode_slots",
        sa.Column("confirmation_reason", sa.JSON(), nullable=True),
    )
    op.create_table(
        "select_episode_coverages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("covering_episode_key", sa.String(52), nullable=False),
        sa.Column("covered_episode_key", sa.String(52), nullable=False),
        sa.Column("covered_value_millis", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["sub_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "covered_episode_key",
            name="uq_selection_coverage_source_episode",
        ),
    )
    for name in (
        "subscription_id",
        "covering_episode_key",
        "covered_episode_key",
        "covered_value_millis",
        "source_type",
        "source_id",
    ):
        op.create_index(f"ix_select_episode_coverages_{name}", "select_episode_coverages", [name])

    connection = op.get_bind()
    sources = list(
        connection.execute(
            sa.text(
                "SELECT id, subscription_id, episode_key, 'decision' AS source_type, created_at "
                "FROM select_decisions UNION ALL "
                "SELECT id, subscription_id, episode_key, 'manual_action' AS source_type, "
                "created_at FROM select_manual_actions WHERE action = 'acquired_elsewhere'"
            )
        ).mappings()
    )
    coverage_table = sa.table(
        "select_episode_coverages",
        sa.column("id"),
        sa.column("subscription_id"),
        sa.column("covering_episode_key"),
        sa.column("covered_episode_key"),
        sa.column("covered_value_millis"),
        sa.column("source_type"),
        sa.column("source_id"),
        sa.column("created_at"),
    )
    for source in sources:
        for index, (covered_key, covered_value) in enumerate(_span(source["episode_key"])):
            connection.execute(
                coverage_table.insert().values(
                    id=str(uuid5(NAMESPACE_URL, f"episode-coverage:{source['id']}:{index}")),
                    subscription_id=source["subscription_id"],
                    covering_episode_key=source["episode_key"],
                    covered_episode_key=covered_key,
                    covered_value_millis=covered_value,
                    source_type=source["source_type"],
                    source_id=source["id"],
                    created_at=source["created_at"],
                )
            )


def downgrade() -> None:
    op.drop_table("select_episode_coverages")
    with op.batch_alter_table("select_episode_slots") as batch:
        batch.drop_column("confirmation_reason")
    with op.batch_alter_table("select_evaluations") as batch:
        batch.drop_column("already_covered_episode_keys")
        batch.drop_column("covered_episode_keys")
        batch.drop_column("coverage_status")
