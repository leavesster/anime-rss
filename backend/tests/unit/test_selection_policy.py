from datetime import UTC, datetime

import pytest
from anime_rss.modules.selection.domain import (
    CandidateFacts,
    EpisodeSpanError,
    SelectionRules,
    episode_span,
    evaluate_candidate,
    first_comparison_field,
    parse_episode_span,
)


def _rules() -> SelectionRules:
    return SelectionRules(
        allowed_groups=(),
        allowed_subtitles=("zh-Hans+zh-Hant", "zh-Hans"),
        allowed_resolutions=("1080p", "720p"),
        allowed_codecs=("HEVC", "AVC"),
        allowed_content_kinds=("episode",),
        preferred_groups=("Nix-Raws", "Other"),
        preferred_subtitles=("zh-Hans+zh-Hant", "zh-Hans"),
        preferred_resolutions=("1080p", "720p"),
        preferred_codecs=("HEVC", "AVC"),
        fallback_wait_minutes=120,
    )


def _candidate(**overrides: object) -> CandidateFacts:
    values: dict[str, object] = {
        "candidate_id": "candidate",
        "release_id": "release",
        "release_group": "Nix-Raws",
        "subtitle_language": "zh-Hans+zh-Hant",
        "resolution": "1080p",
        "video_codec": "HEVC",
        "content_kind": "episode",
        "confidence": "high",
        "recognition_eligible": True,
        "revision": 1,
        "first_seen_at": datetime(2026, 7, 21, tzinfo=UTC),
    }
    values.update(overrides)
    return CandidateFacts(**values)  # pyright: ignore[reportArgumentType]


def test_preferred_candidate_requires_every_configured_first_choice() -> None:
    preferred = evaluate_candidate(_candidate(), _rules())
    fallback = evaluate_candidate(_candidate(video_codec="AVC"), _rules())

    assert preferred.eligible is True
    assert preferred.preferred is True
    assert fallback.eligible is True
    assert fallback.preferred is False
    assert first_comparison_field(preferred, fallback) == "codec"


def test_unknown_subtitle_is_hard_rejected_and_never_promoted() -> None:
    rejected = evaluate_candidate(_candidate(subtitle_language=None), _rules())

    assert rejected.eligible is False
    assert rejected.preferred is False
    failed = [item["field"] for item in rejected.hard_filter_results if not item["passed"]]
    assert failed == ["subtitle"]


def test_episode_ranges_expand_to_stable_scaled_atomic_coverage() -> None:
    span = episode_span("01", "3")
    decimal_span = episode_span("7.5", "8")

    assert span.key == "1-3"
    assert span.covered_keys == ("1", "2", "3")
    assert span.covered_millis == (1000, 2000, 3000)
    assert decimal_span.covered_keys == ("7.5", "8")
    assert parse_episode_span("01.500").key == "1.5"


def test_episode_spans_reject_unsafe_precision_and_reversed_ranges() -> None:
    with pytest.raises(EpisodeSpanError, match="three decimal"):
        episode_span("1.0001")
    with pytest.raises(EpisodeSpanError, match="greater"):
        episode_span("2", "1")
