"""Prevent duplicate feeds and preserve recognition remap history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_feed_mapping"
down_revision: str | None = "0010_guided_setup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("feed_feeds") as batch:
        batch.add_column(sa.Column("url_fingerprint", sa.String(64), nullable=True))
    op.create_index(
        "uq_feed_url_fingerprint",
        "feed_feeds",
        ["url_fingerprint"],
        unique=True,
    )

    with op.batch_alter_table("match_candidates") as batch:
        batch.drop_constraint("uq_match_candidate_release", type_="unique")
        batch.drop_constraint("uq_match_candidates_attempt_id", type_="unique")
        batch.add_column(sa.Column("supersedes_candidate_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("superseded_by_candidate_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("superseded_at", sa.String(32), nullable=True))
    for name in ("attempt_id", "supersedes_candidate_id", "superseded_by_candidate_id"):
        op.create_index(f"ix_match_candidates_{name}", "match_candidates", [name])
    op.create_index(
        "uq_match_candidate_active_release",
        "match_candidates",
        ["release_id"],
        unique=True,
        sqlite_where=sa.text("superseded_by_candidate_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_match_candidate_active_release", table_name="match_candidates")
    for name in ("superseded_by_candidate_id", "supersedes_candidate_id", "attempt_id"):
        op.drop_index(f"ix_match_candidates_{name}", table_name="match_candidates")
    with op.batch_alter_table("match_candidates") as batch:
        batch.drop_column("superseded_at")
        batch.drop_column("superseded_by_candidate_id")
        batch.drop_column("supersedes_candidate_id")
        batch.create_unique_constraint("uq_match_candidates_attempt_id", ["attempt_id"])
        batch.create_unique_constraint("uq_match_candidate_release", ["release_id"])

    op.drop_index("uq_feed_url_fingerprint", table_name="feed_feeds")
    with op.batch_alter_table("feed_feeds") as batch:
        batch.drop_column("url_fingerprint")
