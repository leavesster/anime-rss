from datetime import UTC, datetime, timedelta

from anime_rss.modules.feeds.domain import (
    FeedHealth,
    build_entry_identity,
    normalize_title,
    plan_transient_retry,
    public_entry_url,
    redact_url,
)


def test_redact_url_removes_credentials_path_query_values_and_fragment() -> None:
    redacted = redact_url(
        "https://alice:secret@example.test/private-token/rss?token=abc&category=anime#private"
    )

    assert redacted == "https://***@example.test/***?token=%2A%2A%2A&category=%2A%2A%2A"
    assert "secret" not in redacted
    assert "private-token" not in redacted
    assert "abc" not in redacted
    assert "private" not in redacted


def test_public_entry_url_keeps_path_and_drops_sensitive_parts() -> None:
    assert (
        public_entry_url("https://alice:secret@example.test/releases/episode-1?token=abc#download")
        == "https://example.test/releases/episode-1"
    )
    assert public_entry_url("magnet:?xt=urn:btih:abc") is None


def test_title_normalization_is_bounded_and_deterministic() -> None:
    raw = "  [Group]\x00 Anime　Name  " + "x" * 5000

    normalized = normalize_title(raw)

    assert normalized.startswith("[Group] Anime Name")
    assert "\x00" not in normalized
    assert len(normalized) == 4096
    assert normalize_title(raw) == normalized


def test_guid_identity_is_strong_and_fallback_is_weak() -> None:
    strong_hash, strong = build_entry_identity(
        source_guid="entry-1", link=None, title="Title", published_at=None
    )
    weak_hash, weak = build_entry_identity(
        source_guid=None,
        link="https://example.test/one",
        title="Title",
        published_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert strong.value == "strong"
    assert weak.value == "weak"
    assert strong_hash != weak_hash


def test_retry_backoff_is_persistable_and_bounded() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)

    first = plan_transient_retry(now=now, previous_failures=0, jitter_seconds=3)
    degraded = plan_transient_retry(now=now, previous_failures=2, jitter_seconds=999)
    capped = plan_transient_retry(now=now, previous_failures=20, jitter_seconds=0)

    assert first.health is FeedHealth.TRANSIENT_FAILURE
    assert first.next_fetch_at == now + timedelta(seconds=63)
    assert degraded.health is FeedHealth.DEGRADED
    assert degraded.next_fetch_at == now + timedelta(seconds=240 + 48)
    assert capped.next_fetch_at == now + timedelta(hours=1)
