import pytest
from anime_rss.modules.recognition.domain import (
    ContentKind,
    MatchConfidence,
    parse_release_title,
)


@pytest.mark.parametrize(
    ("title", "group", "episode", "resolution", "codec", "subtitles"),
    [
        (
            "[Nix-Raws] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "S01E02 [CR WEB-DL 1080p AVC AAC][简繁内封]",
            "Nix-Raws",
            "2",
            "1080p",
            "AVC",
            "zh-Hans+zh-Hant",
        ),
        (
            "[黒ネズミたち] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "- 02 (ABEMA 1920x1080 AVC AAC MKV)",
            "黒ネズミたち",
            "2",
            "1080p",
            "AVC",
            None,
        ),
    ],
)
def test_real_feed_shapes_are_grouped_by_series_and_episode(
    title: str,
    group: str,
    episode: str,
    resolution: str,
    codec: str,
    subtitles: str | None,
) -> None:
    parsed = parse_release_title(title)

    assert parsed.release_group == group
    assert parsed.series_title == "无自觉圣女今天也无意识地释放力量"
    assert parsed.series_key == "无自觉圣女今天也无意识地释放力量"
    assert parsed.season in {None, 1}
    assert parsed.episode_key == episode
    assert parsed.resolution == resolution
    assert parsed.video_codec == codec
    assert parsed.subtitle_language == subtitles
    assert parsed.confidence == MatchConfidence.HIGH


def test_decimal_range_and_revision_are_canonical() -> None:
    decimal = parse_release_title("[Group] Example Anime - 07.50V2 [1080p HEVC][CHS]")
    episode_range = parse_release_title("[Group] Example Anime - 01-02 [720p x264]")

    assert decimal.episode_key == "7.5"
    assert decimal.revision == 2
    assert decimal.video_codec == "HEVC"
    assert decimal.subtitle_language == "zh-Hans"
    assert episode_range.episode_key == "1-2"
    assert episode_range.episode_end == "2"


def test_unsupported_and_unparsed_titles_remain_explainable() -> None:
    batch = parse_release_title("[Group] Example Anime Complete Batch [1080p]")

    assert batch.content_kind == ContentKind.BATCH
    assert batch.confidence == MatchConfidence.LOW
    assert batch.reason_code == "episode_not_found"
    assert batch.episode_key is None
