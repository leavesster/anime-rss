"""Associate recognition candidates with stable catalog anime identities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_candidate_catalog_identity"
down_revision: str | None = "0020_recognition_dismissals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_title_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key_kind", sa.String(16), nullable=False),
        sa.Column("match_key", sa.String(300), nullable=False),
        sa.Column("anime_id", sa.String(36), nullable=False),
        sa.Column("source_title", sa.String(300), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["anime_id"], ["catalog_anime.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_kind", "match_key", name="uq_catalog_title_binding_key"),
    )
    op.create_index("ix_catalog_title_bindings_match_key", "catalog_title_bindings", ["match_key"])
    op.create_index("ix_catalog_title_bindings_anime_id", "catalog_title_bindings", ["anime_id"])
    with op.batch_alter_table("match_candidates") as batch:
        batch.add_column(sa.Column("anime_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "catalog_match_status",
                sa.String(16),
                nullable=False,
                server_default="unmatched",
            )
        )
        batch.add_column(sa.Column("catalog_match_method", sa.String(32), nullable=True))
        batch.add_column(sa.Column("catalog_match_key", sa.String(300), nullable=True))
    op.create_index("ix_match_candidates_anime_id", "match_candidates", ["anime_id"])
    op.create_index(
        "ix_match_candidates_catalog_match_status",
        "match_candidates",
        ["catalog_match_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_candidates_catalog_match_status", table_name="match_candidates")
    op.drop_index("ix_match_candidates_anime_id", table_name="match_candidates")
    with op.batch_alter_table("match_candidates") as batch:
        batch.drop_column("catalog_match_key")
        batch.drop_column("catalog_match_method")
        batch.drop_column("catalog_match_status")
        batch.drop_column("anime_id")
    op.drop_table("catalog_title_bindings")
