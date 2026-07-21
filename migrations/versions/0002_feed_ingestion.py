"""Create feed ingestion and release identity tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_feed_ingestion"
down_revision: str | None = "0001_runtime_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feed_feeds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("url_redacted", sa.String(2048), nullable=False),
        sa.Column("endpoint_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("headers_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("last_modified", sa.String(512), nullable=True),
        sa.Column("health", sa.String(40), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.String(32), nullable=True),
        sa.Column("last_success_at", sa.String(32), nullable=True),
        sa.Column("next_fetch_at", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "interval_seconds >= 300 AND interval_seconds <= 3600", name="ck_feed_interval"
        ),
    )
    op.create_index("ix_feed_feeds_next_fetch_at", "feed_feeds", ["next_fetch_at"])
    op.create_table(
        "feed_fetches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feed_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("new_entry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["feed_feeds.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_feed_fetches_feed_id", "feed_fetches", ["feed_id"])
    op.create_index("ix_feed_fetches_status", "feed_fetches", ["status"])
    op.create_table(
        "feed_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feed_id", sa.String(36), nullable=False),
        sa.Column("source_guid", sa.String(2048), nullable=True),
        sa.Column("guid_hash", sa.String(64), nullable=False),
        sa.Column("identity_strength", sa.String(16), nullable=False),
        sa.Column("title_raw", sa.String(4096), nullable=False),
        sa.Column("title_normalized", sa.String(4096), nullable=False),
        sa.Column("published_at", sa.String(32), nullable=True),
        sa.Column("link_redacted", sa.String(2048), nullable=True),
        sa.Column("torrent_reference_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("release_status", sa.String(32), nullable=False),
        sa.Column("release_error_code", sa.String(80), nullable=True),
        sa.Column("first_seen_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["feed_feeds.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feed_id", "guid_hash", name="uq_feed_entry_guid"),
    )
    op.create_index("ix_feed_entries_feed_id", "feed_entries", ["feed_id"])
    op.create_index("ix_feed_entries_first_seen_at", "feed_entries", ["first_seen_at"])

    op.create_table(
        "release_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_kind", sa.String(16), nullable=False),
        sa.Column("identity_value", sa.String(80), nullable=False),
        sa.Column("btih", sa.String(40), nullable=True),
        sa.Column("btmh", sa.String(68), nullable=True),
        sa.Column("automation_eligible", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("identity_kind", "identity_value", name="uq_release_identity"),
    )
    op.create_index("ix_release_releases_btih", "release_releases", ["btih"])
    op.create_index("ix_release_releases_btmh", "release_releases", ["btmh"])
    op.create_index("ix_release_releases_first_seen_at", "release_releases", ["first_seen_at"])
    op.create_table(
        "release_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("feed_entry_id", sa.String(36), nullable=False),
        sa.Column("observed_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feed_entry_id"], ["feed_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("release_id", "feed_entry_id", name="uq_release_source"),
    )
    op.create_index("ix_release_sources_release_id", "release_sources", ["release_id"])
    op.create_index("ix_release_sources_feed_entry_id", "release_sources", ["feed_entry_id"])
    op.create_table(
        "release_payloads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("feed_entry_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feed_entry_id"], ["feed_entries.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("release_id", "sha256", name="uq_release_payload"),
    )
    op.create_index("ix_release_payloads_release_id", "release_payloads", ["release_id"])
    op.create_index("ix_release_payloads_feed_entry_id", "release_payloads", ["feed_entry_id"])


def downgrade() -> None:
    op.drop_table("release_payloads")
    op.drop_table("release_sources")
    op.drop_table("release_releases")
    op.drop_table("feed_entries")
    op.drop_table("feed_fetches")
    op.drop_table("feed_feeds")
