from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast


class SubscriptionState(StrEnum):
    FOLLOWING = "following"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class PreferenceRules:
    allowed_groups: tuple[str, ...] = ()
    allowed_subtitles: tuple[str, ...] = (
        "zh-Hans+zh-Hant",
        "zh-Hans",
        "zh-Hant",
    )
    allowed_resolutions: tuple[str, ...] = ("1080p", "720p")
    allowed_codecs: tuple[str, ...] = ("HEVC", "AVC", "AV1")
    allowed_content_kinds: tuple[str, ...] = ("episode",)
    preferred_groups: tuple[str, ...] = ()
    preferred_subtitles: tuple[str, ...] = (
        "zh-Hans+zh-Hant",
        "zh-Hans",
        "zh-Hant",
    )
    preferred_resolutions: tuple[str, ...] = ("1080p", "720p")
    preferred_codecs: tuple[str, ...] = ("HEVC", "AVC", "AV1")
    fallback_wait_minutes: int = 120

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "PreferenceRules":
        if value is None:
            return cls()
        defaults = cls()

        def strings(key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
            raw: object = value.get(key)
            if not isinstance(raw, list | tuple):
                return fallback
            items = cast(list[object] | tuple[object, ...], raw)
            return tuple(item for item in items if isinstance(item, str))

        wait = value.get("fallback_wait_minutes", 120)
        return cls(
            allowed_groups=strings("allowed_groups", defaults.allowed_groups),
            allowed_subtitles=strings("allowed_subtitles", defaults.allowed_subtitles),
            allowed_resolutions=strings("allowed_resolutions", defaults.allowed_resolutions),
            allowed_codecs=strings("allowed_codecs", defaults.allowed_codecs),
            allowed_content_kinds=strings("allowed_content_kinds", defaults.allowed_content_kinds),
            preferred_groups=strings("preferred_groups", defaults.preferred_groups),
            preferred_subtitles=strings("preferred_subtitles", defaults.preferred_subtitles),
            preferred_resolutions=strings("preferred_resolutions", defaults.preferred_resolutions),
            preferred_codecs=strings("preferred_codecs", defaults.preferred_codecs),
            fallback_wait_minutes=(min(max(wait, 0), 10080) if isinstance(wait, int) else 120),
        )


_TRANSITIONS = {
    SubscriptionState.FOLLOWING: {
        SubscriptionState.PAUSED,
        SubscriptionState.COMPLETED,
        SubscriptionState.ARCHIVED,
    },
    SubscriptionState.PAUSED: {
        SubscriptionState.FOLLOWING,
        SubscriptionState.COMPLETED,
        SubscriptionState.ARCHIVED,
    },
    SubscriptionState.COMPLETED: {
        SubscriptionState.FOLLOWING,
        SubscriptionState.ARCHIVED,
    },
    SubscriptionState.ARCHIVED: {SubscriptionState.PAUSED},
}


def validate_state_transition(current: SubscriptionState, target: SubscriptionState) -> None:
    if target == current:
        return
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"invalid subscription transition: {current} -> {target}")
