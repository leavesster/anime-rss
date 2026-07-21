import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

PARSER_VERSION = "title-rules.v1"


class MatchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ContentKind(StrEnum):
    EPISODE = "episode"
    BATCH = "batch"
    MOVIE = "movie"
    SPECIAL = "special"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ParsedReleaseTitle:
    parser_version: str
    source_title: str
    release_group: str | None
    series_title: str | None
    series_key: str | None
    season: int | None
    episode_start: str | None
    episode_end: str | None
    episode_key: str | None
    resolution: str | None
    video_codec: str | None
    subtitle_language: str | None
    revision: int
    content_kind: ContentKind
    confidence: MatchConfidence
    reason_code: str


_GROUP = re.compile(r"^\s*[\[【](?P<group>[^\]】]{1,120})[\]】]\s*")
_SEASON_EPISODE = re.compile(
    r"(?i)\bS(?P<season>\d{1,2})E(?P<start>\d{1,3}(?:\.\d+)?)"
    r"(?:\s*[-~]\s*(?:E)?(?P<end>\d{1,3}(?:\.\d+)?))?"
    r"(?:V(?P<revision>\d+))?\b"
)
_DASH_EPISODE = re.compile(
    r"(?:^|\s)[-\u2013\u2014]\s*(?P<start>\d{1,3}(?:\.\d+)?)"
    r"(?:\s*[-~]\s*(?P<end>\d{1,3}(?:\.\d+)?))?"
    r"(?:V(?P<revision>\d+))?(?=\s|$|\(|\[)",
    re.IGNORECASE,
)
_BRACKET_EPISODE = re.compile(
    r"[\[【](?P<start>\d{1,3}(?:\.\d+)?)"
    r"(?:\s*[-~]\s*(?P<end>\d{1,3}(?:\.\d+)?))?"
    r"(?:V(?P<revision>\d+))?[\]】]",
    re.IGNORECASE,
)


def canonical_episode_number(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    exponent = number.as_tuple().exponent
    if not number.is_finite() or number < 0 or not isinstance(exponent, int) or exponent < -3:
        return None
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def normalize_series_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _content_kind(title: str) -> ContentKind:
    upper = title.upper()
    if re.search(r"\b(BATCH|PACK|COLLECTION)\b|合集|全集", upper):
        return ContentKind.BATCH
    if re.search(r"\bMOVIE\b|剧场版|劇場版", upper):
        return ContentKind.MOVIE
    if re.search(r"\b(OVA|OAD|SPECIAL)\b|\bSP\d*\b|特别篇|特別篇", upper):
        return ContentKind.SPECIAL
    return ContentKind.EPISODE


def _resolution(title: str) -> str | None:
    upper = title.upper()
    match = re.search(r"\b(2160|1080|720|480)P\b", upper)
    if match:
        return f"{match.group(1)}p"
    dimensions = re.search(r"\b(3840X2160|1920X1080|1280X720|854X480)\b", upper)
    if dimensions:
        return {
            "3840X2160": "2160p",
            "1920X1080": "1080p",
            "1280X720": "720p",
            "854X480": "480p",
        }[dimensions.group(1)]
    return None


def _video_codec(title: str) -> str | None:
    upper = title.upper()
    if re.search(r"\b(HEVC|H[.]?265|X265)\b", upper):
        return "HEVC"
    if re.search(r"\b(AVC|H[.]?264|X264)\b", upper):
        return "AVC"
    if re.search(r"\bAV1\b", upper):
        return "AV1"
    return None


def _subtitle_language(title: str) -> str | None:
    upper = title.upper()
    simplified = bool(re.search(r"简|簡|CHS|GB", upper))
    traditional = bool(re.search(r"繁|CHT|BIG5", upper))
    if simplified and traditional:
        return "zh-Hans+zh-Hant"
    if simplified:
        return "zh-Hans"
    if traditional:
        return "zh-Hant"
    if re.search(r"\bRAW\b", upper):
        return "raw"
    return None


def parse_release_title(title: str) -> ParsedReleaseTitle:
    normalized = unicodedata.normalize("NFKC", title).strip()[:4096]
    group_match = _GROUP.match(normalized)
    release_group = group_match.group("group").strip() if group_match else None
    body_offset = group_match.end() if group_match else 0
    body = normalized[body_offset:].strip()

    episode_match = _SEASON_EPISODE.search(body)
    season = int(episode_match.group("season")) if episode_match else None
    if episode_match is None:
        episode_match = _DASH_EPISODE.search(body)
    if episode_match is None:
        episode_match = _BRACKET_EPISODE.search(body)

    start = canonical_episode_number(episode_match.group("start")) if episode_match else None
    end = canonical_episode_number(episode_match.groupdict().get("end")) if episode_match else None
    revision_text = episode_match.groupdict().get("revision") if episode_match else None
    revision = int(revision_text) if revision_text else 1
    episode_key = f"{start}-{end}" if start and end else start

    series_title = None
    series_key = None
    if episode_match:
        series_part = body[: episode_match.start()].strip(" \t-\u2013\u2014_/|")
        localized_title = next(
            (part.strip() for part in re.split(r"\s+/\s+", series_part) if part.strip()),
            "",
        )
        localized_title = re.sub(r"\s*[\[(【][^\])】]*$", "", localized_title).strip()
        if localized_title:
            series_title = localized_title[:300]
            series_key = normalize_series_key(series_title) or None

    content_kind = _content_kind(normalized)
    if series_key and episode_key and release_group:
        confidence = MatchConfidence.HIGH
        reason_code = "parsed_group_series_episode"
    elif series_key and episode_key:
        confidence = MatchConfidence.MEDIUM
        reason_code = "parsed_series_episode_without_group"
    elif not episode_key:
        confidence = MatchConfidence.LOW
        reason_code = "episode_not_found"
    else:
        confidence = MatchConfidence.LOW
        reason_code = "series_not_found"

    return ParsedReleaseTitle(
        parser_version=PARSER_VERSION,
        source_title=normalized,
        release_group=release_group,
        series_title=series_title,
        series_key=series_key,
        season=season,
        episode_start=start,
        episode_end=end,
        episode_key=episode_key,
        resolution=_resolution(normalized),
        video_codec=_video_codec(normalized),
        subtitle_language=_subtitle_language(normalized),
        revision=revision,
        content_kind=content_kind,
        confidence=confidence,
        reason_code=reason_code,
    )
