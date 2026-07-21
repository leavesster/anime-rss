"""Create deterministic recognition attempts and episode candidates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_release_recognition"
down_revision: str | None = "0002_feed_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("feed_entry_id", sa.String(36), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("source_title", sa.String(4096), nullable=False),
        sa.Column("release_group", sa.String(120), nullable=True),
        sa.Column("series_title", sa.String(300), nullable=True),
        sa.Column("series_key", sa.String(300), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode_start", sa.String(24), nullable=True),
        sa.Column("episode_end", sa.String(24), nullable=True),
        sa.Column("episode_key", sa.String(52), nullable=True),
        sa.Column("resolution", sa.String(16), nullable=True),
        sa.Column("video_codec", sa.String(16), nullable=True),
        sa.Column("subtitle_language", sa.String(40), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_kind", sa.String(24), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("parsed_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feed_entry_id"], ["feed_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feed_entry_id", name="uq_match_attempt_feed_entry"),
    )
    op.create_index("ix_match_attempts_release_id", "match_attempts", ["release_id"])
    op.create_index("ix_match_attempts_feed_entry_id", "match_attempts", ["feed_entry_id"])
    op.create_index("ix_match_attempts_series_key", "match_attempts", ["series_key"])
    op.create_index("ix_match_attempts_episode_key", "match_attempts", ["episode_key"])
    op.create_index("ix_match_attempts_confidence", "match_attempts", ["confidence"])

    op.create_table(
        "match_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("source_title", sa.String(4096), nullable=False),
        sa.Column("series_title", sa.String(300), nullable=False),
        sa.Column("series_key", sa.String(300), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode_start", sa.String(24), nullable=False),
        sa.Column("episode_end", sa.String(24), nullable=True),
        sa.Column("episode_key", sa.String(52), nullable=False),
        sa.Column("release_group", sa.String(120), nullable=True),
        sa.Column("resolution", sa.String(16), nullable=True),
        sa.Column("video_codec", sa.String(16), nullable=True),
        sa.Column("subtitle_language", sa.String(40), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_kind", sa.String(24), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("recognition_eligible", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["match_attempts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("release_id", name="uq_match_candidate_release"),
        sa.UniqueConstraint("attempt_id", name="uq_match_candidates_attempt_id"),
    )
    op.create_index("ix_match_candidates_release_id", "match_candidates", ["release_id"])
    op.create_index("ix_match_candidates_series_key", "match_candidates", ["series_key"])
    op.create_index("ix_match_candidates_episode_key", "match_candidates", ["episode_key"])
    op.create_index("ix_match_candidates_confidence", "match_candidates", ["confidence"])
    op.create_index("ix_match_candidates_first_seen_at", "match_candidates", ["first_seen_at"])


def downgrade() -> None:
    op.drop_table("match_candidates")
    op.drop_table("match_attempts")
