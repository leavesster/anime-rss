from datetime import UTC, datetime

from anime_rss.modules.selection.domain import (
    CandidateFacts,
    SelectionRules,
    evaluate_candidate,
    first_comparison_field,
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
