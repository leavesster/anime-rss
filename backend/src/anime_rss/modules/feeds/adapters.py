import calendar
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from urllib.parse import urlsplit

import feedparser  # pyright: ignore[reportMissingTypeStubs]

from anime_rss.modules.feeds.domain import (
    NormalizedFeedEntry,
    build_entry_identity,
    normalize_title,
)


class FeedParseError(ValueError):
    pass


class FeedDocumentParser:
    _SUPPORTED_VERSIONS: ClassVar[set[str]] = {
        "atom10",
        "rss20",
        "rss10",
        "rss090",
        "rss091",
        "rss092",
    }

    def parse(self, body: bytes) -> list[NormalizedFeedEntry]:
        document = cast(
            Any,
            feedparser.parse(body),  # pyright: ignore[reportUnknownMemberType]
        )
        if document.version not in self._SUPPORTED_VERSIONS:
            raise FeedParseError("unsupported_feed_format")
        if document.bozo and not document.entries:
            raise FeedParseError("malformed_feed")
        return [self._normalize_entry(entry) for entry in document.entries]

    def _normalize_entry(self, entry: Any) -> NormalizedFeedEntry:
        title_raw = str(entry.get("title", ""))[:4096]
        title_normalized = normalize_title(title_raw)
        published_at = self._publication_time(entry)
        link = self._entry_link(entry)
        torrent_reference = self._torrent_reference(entry)
        source_guid_value = entry.get("id") or entry.get("guid")
        source_guid = str(source_guid_value)[:2048] if source_guid_value else None
        guid_hash, strength = build_entry_identity(
            source_guid=source_guid,
            link=link,
            title=title_normalized,
            published_at=published_at,
        )
        return NormalizedFeedEntry(
            source_guid=source_guid,
            guid_hash=guid_hash,
            identity_strength=strength,
            title_raw=title_raw,
            title_normalized=title_normalized,
            published_at=published_at,
            link=link,
            torrent_reference=torrent_reference,
        )

    @staticmethod
    def _publication_time(entry: Any) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed is None:
            return None
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)

    @staticmethod
    def _entry_link(entry: Any) -> str | None:
        value = entry.get("link")
        return str(value)[:4096] if value else None

    @staticmethod
    def _has_torrent_path(value: str) -> bool:
        try:
            return urlsplit(value).path.lower().endswith(".torrent")
        except ValueError:
            return False

    @staticmethod
    def _torrent_reference(entry: Any) -> str | None:
        links = list(entry.get("links", []))
        for link in links:
            href = str(link.get("href", ""))
            content_type = str(link.get("type", "")).lower()
            relation = str(link.get("rel", "")).lower()
            if href.startswith("magnet:"):
                return href
            if content_type == "application/x-bittorrent" or (
                relation == "enclosure" and FeedDocumentParser._has_torrent_path(href)
            ):
                return href
        link = FeedDocumentParser._entry_link(entry)
        if link and (link.startswith("magnet:") or FeedDocumentParser._has_torrent_path(link)):
            return link
        return None
