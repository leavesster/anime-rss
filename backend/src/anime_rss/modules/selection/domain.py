from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SelectionRules:
    allowed_groups: tuple[str, ...]
    allowed_subtitles: tuple[str, ...]
    allowed_resolutions: tuple[str, ...]
    allowed_codecs: tuple[str, ...]
    allowed_content_kinds: tuple[str, ...]
    preferred_groups: tuple[str, ...]
    preferred_subtitles: tuple[str, ...]
    preferred_resolutions: tuple[str, ...]
    preferred_codecs: tuple[str, ...]
    fallback_wait_minutes: int


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    candidate_id: str
    release_id: str
    release_group: str | None
    subtitle_language: str | None
    resolution: str | None
    video_codec: str | None
    content_kind: str
    confidence: str
    recognition_eligible: bool
    revision: int
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    eligible: bool
    preferred: bool
    hard_filter_results: list[dict[str, Any]]
    rank: tuple[int | str, ...]


_RANK_FIELDS = ("release_group", "subtitle", "resolution", "codec", "revision", "seen")


def _matches(value: str | None, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return True
    if value is None:
        return False
    normalized = value.casefold()
    return normalized in {item.casefold() for item in allowed}


def _rank(value: str | None, preferred: tuple[str, ...]) -> int:
    if not preferred:
        return 0
    if value is None:
        return len(preferred) + 1
    normalized = value.casefold()
    for index, item in enumerate(preferred):
        if normalized == item.casefold():
            return index
    return len(preferred)


def _is_first(value: str | None, preferred: tuple[str, ...]) -> bool:
    return not preferred or (value is not None and value.casefold() == preferred[0].casefold())


def evaluate_candidate(candidate: CandidateFacts, rules: SelectionRules) -> CandidateEvaluation:
    checks = [
        {
            "field": "identity",
            "passed": candidate.recognition_eligible,
            "reason": "recognized_release" if candidate.recognition_eligible else "not_eligible",
        },
        {
            "field": "confidence",
            "passed": candidate.confidence == "high",
            "reason": (
                "high_confidence" if candidate.confidence == "high" else "confidence_not_high"
            ),
        },
        {
            "field": "content_kind",
            "passed": _matches(candidate.content_kind, rules.allowed_content_kinds),
            "reason": "content_kind_allowed",
        },
        {
            "field": "release_group",
            "passed": _matches(candidate.release_group, rules.allowed_groups),
            "reason": "release_group_allowed",
        },
        {
            "field": "subtitle",
            "passed": _matches(candidate.subtitle_language, rules.allowed_subtitles),
            "reason": "subtitle_allowed",
        },
        {
            "field": "resolution",
            "passed": _matches(candidate.resolution, rules.allowed_resolutions),
            "reason": "resolution_allowed",
        },
        {
            "field": "codec",
            "passed": _matches(candidate.video_codec, rules.allowed_codecs),
            "reason": "codec_allowed",
        },
    ]
    eligible = all(bool(check["passed"]) for check in checks)
    preferred = eligible and all(
        (
            _is_first(candidate.release_group, rules.preferred_groups),
            _is_first(candidate.subtitle_language, rules.preferred_subtitles),
            _is_first(candidate.resolution, rules.preferred_resolutions),
            _is_first(candidate.video_codec, rules.preferred_codecs),
        )
    )
    rank: tuple[int | str, ...] = (
        _rank(candidate.release_group, rules.preferred_groups),
        _rank(candidate.subtitle_language, rules.preferred_subtitles),
        _rank(candidate.resolution, rules.preferred_resolutions),
        _rank(candidate.video_codec, rules.preferred_codecs),
        -candidate.revision,
        candidate.first_seen_at.isoformat(),
        candidate.release_id,
    )
    return CandidateEvaluation(
        eligible=eligible,
        preferred=preferred,
        hard_filter_results=checks,
        rank=rank,
    )


def first_comparison_field(winner: CandidateEvaluation, loser: CandidateEvaluation) -> str | None:
    for index, field in enumerate(_RANK_FIELDS):
        if winner.rank[index] != loser.rank[index]:
            return field
    if winner.rank[-1] != loser.rank[-1]:
        return "release_identity"
    return None
