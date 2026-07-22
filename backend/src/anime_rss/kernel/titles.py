import hashlib
import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from importlib.resources import files
from typing import Protocol, cast

from opencc import OpenCC  # pyright: ignore[reportMissingTypeStubs]


class _TitleConverter(Protocol):
    def convert(self, value: str) -> str: ...


_TRADITIONAL_TO_SIMPLIFIED = cast(_TitleConverter, OpenCC("t2s"))

_SEASON_SUFFIX = re.compile(
    r"(?ix)"
    r"(?:season\s*0*(?P<season>\d{1,2})|第\s*0*(?P<number>\d{1,2})\s*季|"
    r"第\s*(?P<chinese>[一二三四五六七八九十])\s*季)$"
)
_NUMERIC_SEASON_SUFFIX = re.compile(r"(?P<body>.*(?:\s|[^\x00-\x7f]))0*(?P<season>\d{1,2})$")
_ROMAN_SEASON_SUFFIX = re.compile(
    r"(?i)(?P<body>.*(?:\s|[^\x00-\x7f]))(?P<season>i|ii|iii|iv|v|vi|vii|viii|ix|x)$"
)
_ROMAN_SEASONS = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
}
_CHINESE_SEASONS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@lru_cache(maxsize=1)
def _japanese_variant_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    dictionary = files("opencc").joinpath("dictionary", "JPVariants.txt")
    for line in dictionary.read_text(encoding="utf-8").splitlines():
        traditional, japanese_variants = line.split("\t", maxsplit=1)
        for japanese in japanese_variants.split():
            mapping.setdefault(japanese, traditional)
    return mapping


def _japanese_to_traditional(value: str) -> str:
    mapping = _japanese_variant_map()
    return "".join(mapping.get(character, character) for character in value)


def normalize_title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


@lru_cache(maxsize=4096)
def canonical_chinese_title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    traditional = _japanese_to_traditional(normalized)
    simplified = _TRADITIONAL_TO_SIMPLIFIED.convert(traditional)
    return "".join(character for character in simplified if character.isalnum())


def anime_title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    traditional = _japanese_to_traditional(normalized)
    simplified = _TRADITIONAL_TO_SIMPLIFIED.convert(traditional)
    season: int | None = None
    body = simplified

    suffix = _SEASON_SUFFIX.search(simplified)
    if suffix is not None and suffix.start() > 0:
        numeric_season = suffix.group("season") or suffix.group("number")
        season = (
            int(numeric_season)
            if numeric_season is not None
            else _CHINESE_SEASONS[suffix.group("chinese")]
        )
        body = simplified[: suffix.start()].rstrip()
    else:
        numeric = _NUMERIC_SEASON_SUFFIX.fullmatch(simplified)
        if numeric is not None and numeric.group("body").strip():
            season = int(numeric.group("season"))
            body = numeric.group("body").rstrip()
        else:
            roman = _ROMAN_SEASON_SUFFIX.fullmatch(simplified)
            if roman is not None and roman.group("body").strip():
                season = _ROMAN_SEASONS[roman.group("season").casefold()]
                body = roman.group("body").rstrip()

    key = "".join(character for character in body if character.isalnum())
    if season is not None and key:
        return f"{key}season{season}"
    return key


def title_variant_signature(titles: Sequence[str]) -> str:
    keys = sorted({key for title in titles if (key := anime_title_key(title))})
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()
