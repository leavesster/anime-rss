import json
import unicodedata
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any

from anime_rss.modules.recognition.domain import (
    MAX_SERIES_KEY_LENGTH,
    PARSER_VERSION,
    MatchConfidence,
    normalize_series_key,
    parse_release_title,
)

FIXTURE_PATH = Path(__file__).parents[3] / "parser-fixtures" / "title-rules.v2.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _contract(title: str) -> dict[str, Any]:
    result = asdict(parse_release_title(title))
    result["content_kind"] = result["content_kind"].value
    result["confidence"] = result["confidence"].value
    return result


def test_versioned_golden_matrix_expands_to_at_least_300_complete_snapshots() -> None:
    fixture = _fixture()
    matrix = fixture["matrix"]
    combinations = list(
        product(
            matrix["groups"],
            matrix["series"],
            matrix["episodes"],
            matrix["profiles"],
        )
    )

    assert fixture["schema_version"] == 1
    assert fixture["parser_version"] == PARSER_VERSION
    assert len(combinations) >= fixture["minimum_expanded_cases"]

    for group, series, episode, profile in combinations:
        title = f"{group['source']} {series['source']}{episode['source']}{profile['source']}"
        expected = {
            "parser_version": PARSER_VERSION,
            "source_title": unicodedata.normalize("NFKC", title).strip()[:4096],
            "release_group": group["expected"],
            "series_title": series["normalized"],
            "series_key": series["key"],
            "season": episode["season"],
            "episode_start": episode["start"],
            "episode_end": episode["end"],
            "episode_key": episode["key"],
            "resolution": profile["resolution"],
            "video_codec": profile["codec"],
            "subtitle_language": profile["subtitles"],
            "revision": episode["revision"],
            "content_kind": "episode",
            "confidence": "high",
            "reason_code": "parsed_group_series_episode",
        }

        assert _contract(title) == expected, title


def test_focused_golden_cases_cover_ambiguous_and_malformed_shapes() -> None:
    for case in _fixture()["focused_cases"]:
        actual = _contract(case["title"])
        for field, expected in case["expected"].items():
            assert actual[field] == expected, f"{case['name']}: {field}"


def _unicode_samples() -> list[str]:
    codepoints = (
        0x0000,
        0x0009,
        0x0020,
        0x007F,
        0x00DF,
        0x0130,
        0x0301,
        0x03A9,
        0x0661,
        0x200D,
        0x3000,
        0x4E2D,
        0x30A2,
        0xFF21,
        0x1F642,
        0xD800,
        0xDC00,
        0xFDD0,
        0x10FFFF,
    )
    samples: list[str] = []
    for index in range(512):
        body = "".join(
            chr(codepoints[(index * 7 + offset * 11) % len(codepoints)])
            for offset in range(index % 19 + 1)
        )
        episode = index % 999 + 1
        revision = index % 999 + 1
        match index % 4:
            case 0:
                samples.append(body)
            case 1:
                samples.append(f"[Group] {body} - {episode:03d}V{revision}")
            case 2:
                samples.append(f"【字幕組】 {body} S01E{episode:03d}V{revision} [1080p HEVC]")
            case _:
                samples.append(f"{body} / Alternate - {episode:03d} [720p AVC][简繁]")
    return samples


def test_unicode_properties_are_deterministic_normalized_and_persistence_bounded() -> None:
    for title in _unicode_samples():
        normalized_title = unicodedata.normalize("NFKC", title)
        parsed = parse_release_title(title)

        assert parsed == parse_release_title(title)
        assert parsed == parse_release_title(normalized_title)
        assert parsed.source_title == normalized_title.strip()[:4096]
        assert len(parsed.source_title) <= 4096
        assert parsed.release_group is None or len(parsed.release_group) <= 120
        assert parsed.series_title is None or len(parsed.series_title) <= 300
        assert parsed.series_key is None or len(parsed.series_key) <= MAX_SERIES_KEY_LENGTH
        assert 1 <= parsed.revision <= 999

        if parsed.series_title is not None:
            assert parsed.series_key == (normalize_series_key(parsed.series_title) or None)
        if parsed.episode_end is not None:
            assert parsed.episode_key == f"{parsed.episode_start}-{parsed.episode_end}"
        if parsed.confidence == MatchConfidence.HIGH:
            assert parsed.release_group and parsed.series_key and parsed.episode_key


def test_oversized_casefold_and_revision_inputs_stay_within_storage_contracts() -> None:
    expanded_key = parse_release_title(f"[Group] {'ß' * 300} - 01")
    oversized_source = parse_release_title("X" * 5000)
    oversized_revision = parse_release_title(f"[Group] Example - 01V{'9' * 3000}")

    assert expanded_key.series_key == "ss" * 150
    assert len(expanded_key.series_key) == MAX_SERIES_KEY_LENGTH
    assert len(oversized_source.source_title) == 4096
    assert oversized_revision.episode_key is None
    assert oversized_revision.revision == 1
