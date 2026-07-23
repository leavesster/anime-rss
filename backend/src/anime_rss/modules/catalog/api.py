import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.kernel.titles import anime_title_key, title_variant_signature
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.adapters import BangumiAnime, CatalogProviderError
from anime_rss.modules.catalog.domain import normalize_title_key as _normalize_title_key
from anime_rss.modules.catalog.persistence import (
    AnimeRecord,
    AnimeTitleBindingRecord,
    AnimeTitleRecord,
    MetadataCacheRecord,
)

__all__ = ["CatalogProviderError", "CatalogService"]


class CatalogProvider(Protocol):
    def search(self, query: str, *, limit: int = 12) -> list[BangumiAnime]: ...

    def get(self, bangumi_id: int) -> BangumiAnime: ...

    def list_season(self, start_date: str, end_date: str) -> list[BangumiAnime]: ...


@dataclass(frozen=True, slots=True)
class AnimeTitle:
    title: str
    normalized: str
    kind: str
    source: str


@dataclass(frozen=True, slots=True)
class Anime:
    id: str
    bangumi_id: int | None
    primary_title: str
    title_zh: str | None
    title_ja: str | None
    title_en: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    airing_weekday: int | None
    airing_time: str | None
    schedule_timezone: str | None
    schedule_source: str | None
    schedule_updated_at: datetime | None
    cover_url: str | None
    source: str
    version: int
    titles: list[AnimeTitle]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    items: list[BangumiAnime]
    stale: bool


@dataclass(frozen=True, slots=True)
class CatalogSeasonResult:
    items: list[BangumiAnime]
    fetched_at: datetime
    stale: bool


@dataclass(frozen=True, slots=True)
class CatalogTitleMatch:
    status: str
    anime_id: str | None
    matched_key: str | None
    method: str | None


@dataclass(frozen=True, slots=True)
class CatalogTitleBindingConflict:
    suggested_anime_id: str
    evidence_titles: list[str]


class AnimeNotFoundError(LookupError):
    pass


_EXPLICIT_SEASON = re.compile(
    r"(?i)(?:season\s*0*\d{1,2}|\d+(?:st|nd|rd|th)\s+season|"
    r"\bS0*\d{1,2}\b|\b(?:II|III|IV|V|VI|VII|VIII|IX|X)\b|"
    r"第\s*[一二三四五六七八九十\d]+\s*季)"
)


def normalize_title_key(value: str) -> str:
    return _normalize_title_key(value)


class CatalogService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: CatalogProvider,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._clock = clock

    def create_local(self, *, title: str, aliases: list[str] | None = None) -> Anime:
        primary = title.strip()
        if not primary or not normalize_title_key(primary):
            raise ValueError("anime title is required")
        now = self._clock()
        anime_id = new_id()
        with self._session_factory.begin() as session:
            session.add(
                AnimeRecord(
                    id=anime_id,
                    primary_title=primary[:300],
                    title_zh=primary[:300],
                    source="local",
                    created_at=now,
                    updated_at=now,
                )
            )
            self._replace_titles(
                session,
                anime_id,
                [(primary, "primary", "local")]
                + [(alias, "alias", "user") for alias in aliases or []],
            )
            record_event(
                session,
                event_type="catalog.anime_created",
                entity_type="anime",
                entity_id=anime_id,
                payload={"source": "local"},
            )
            append_event(
                session,
                name="CatalogTitlesChanged.v1",
                payload={"anime_id": anime_id},
            )
        return self.get_anime(anime_id)

    def import_bangumi(self, bangumi_id: int) -> Anime:
        external = self._provider.get(bangumi_id)
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(AnimeRecord).where(AnimeRecord.bangumi_id == external.bangumi_id)
            )
            if record is None:
                record = AnimeRecord(id=new_id(), created_at=now)
                session.add(record)
            else:
                record.version += 1
            record.bangumi_id = external.bangumi_id
            record.primary_title = external.name_cn or external.name
            record.title_zh = external.name_cn
            record.title_ja = external.name
            record.summary = external.summary
            record.air_date = external.air_date
            record.episode_count = external.episode_count
            record.airing_weekday = external.airing_weekday
            record.airing_time = external.airing_time
            record.schedule_timezone = "Asia/Tokyo"
            record.schedule_source = "bangumi"
            record.schedule_updated_at = now
            record.cover_url = external.cover_url
            record.source = "bangumi"
            record.updated_at = now
            session.flush()
            titles = [
                (record.primary_title, "primary", "bangumi"),
                (external.name, "ja", "bangumi"),
            ]
            if external.name_cn:
                titles.append((external.name_cn, "zh", "bangumi"))
            titles.extend((alias, "alias", "bangumi") for alias in external.aliases)
            self._replace_titles(session, record.id, titles)
            record_event(
                session,
                event_type="catalog.anime_imported",
                entity_type="anime",
                entity_id=record.id,
                payload={"provider": "bangumi", "bangumi_id": external.bangumi_id},
            )
            append_event(
                session,
                name="CatalogTitlesChanged.v1",
                payload={"anime_id": record.id},
            )
            anime_id = record.id
        return self.get_anime(anime_id)

    def add_alias(self, anime_id: str, alias: str, *, expected_version: int) -> Anime:
        value = alias.strip()
        normalized = normalize_title_key(value)
        if not normalized:
            raise ValueError("alias is required")
        with self._session_factory.begin() as session:
            record = session.get(AnimeRecord, anime_id)
            if record is None:
                raise AnimeNotFoundError(anime_id)
            if record.version != expected_version:
                raise ValueError("anime version conflict")
            existing = session.scalar(
                select(AnimeTitleRecord.id).where(
                    AnimeTitleRecord.anime_id == anime_id,
                    AnimeTitleRecord.normalized == normalized[:300],
                )
            )
            if existing is not None:
                return self.get_anime(anime_id)
            session.add(
                AnimeTitleRecord(
                    id=new_id(),
                    anime_id=anime_id,
                    title=value[:300],
                    normalized=normalized[:300],
                    kind="alias",
                    source="user",
                    created_at=self._clock(),
                )
            )
            record.version += 1
            record.updated_at = self._clock()
            record_event(
                session,
                event_type="catalog.alias_added",
                entity_type="anime",
                entity_id=anime_id,
                payload={"alias": value[:300]},
            )
            append_event(
                session,
                name="CatalogTitlesChanged.v1",
                payload={"anime_id": anime_id},
            )
        return self.get_anime(anime_id)

    def add_aliases(self, anime_id: str, aliases: list[str]) -> Anime:
        cleaned = [alias.strip()[:300] for alias in aliases if normalize_title_key(alias)]
        if not cleaned:
            return self.get_anime(anime_id)
        changed = False
        with self._session_factory.begin() as session:
            record = session.get(AnimeRecord, anime_id)
            if record is None:
                raise AnimeNotFoundError(anime_id)
            existing = set(
                session.scalars(
                    select(AnimeTitleRecord.normalized).where(AnimeTitleRecord.anime_id == anime_id)
                )
            )
            for alias in cleaned:
                normalized = normalize_title_key(alias)[:300]
                if normalized in existing:
                    continue
                existing.add(normalized)
                changed = True
                session.add(
                    AnimeTitleRecord(
                        id=new_id(),
                        anime_id=anime_id,
                        title=alias,
                        normalized=normalized,
                        kind="alias",
                        source="user",
                        created_at=self._clock(),
                    )
                )
            if changed:
                record.version += 1
                record.updated_at = self._clock()
                append_event(
                    session,
                    name="CatalogTitlesChanged.v1",
                    payload={"anime_id": anime_id},
                )
                record_event(
                    session,
                    event_type="catalog.aliases_added",
                    entity_type="anime",
                    entity_id=anime_id,
                    payload={"alias_count": len(cleaned)},
                )
        return self.get_anime(anime_id)

    def bind_title(self, anime_id: str, title: str) -> Anime:
        return self.bind_titles(anime_id, [title])

    def bind_titles(self, anime_id: str, titles: list[str]) -> Anime:
        values = list(
            dict.fromkeys(title.strip()[:300] for title in titles if normalize_title_key(title))
        )
        if not values:
            raise ValueError("at least one title is required")
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(AnimeRecord, anime_id)
            if record is None:
                raise AnimeNotFoundError(anime_id)

            if len(values) == 1:
                value = values[0]
                normalized = normalize_title_key(value)[:300]
                semantic = anime_title_key(value)[:300]
                keys = [("exact", normalized)]
                if semantic:
                    keys.append(("semantic", semantic))
            else:
                keys = [("variant_set", title_variant_signature(values))]

            source_title = " / ".join(values)[:300]
            for key_kind, match_key in keys:
                session.execute(
                    insert(AnimeTitleBindingRecord)
                    .values(
                        id=new_id(),
                        key_kind=key_kind,
                        match_key=match_key,
                        anime_id=anime_id,
                        source_title=source_title,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["key_kind", "match_key"],
                        set_={
                            "anime_id": anime_id,
                            "source_title": source_title,
                            "updated_at": now,
                        },
                    )
                )

            existing_titles = list(
                session.scalars(
                    select(AnimeTitleRecord).where(AnimeTitleRecord.anime_id == anime_id)
                )
            )
            existing_normalized = {item.normalized for item in existing_titles}
            target_semantic_keys = {anime_title_key(item.title) for item in existing_titles}
            aliases = (
                values
                if len(values) == 1
                else [value for value in values if anime_title_key(value) in target_semantic_keys]
            )
            for value in aliases:
                normalized = normalize_title_key(value)[:300]
                if normalized in existing_normalized:
                    continue
                existing_normalized.add(normalized)
                session.add(
                    AnimeTitleRecord(
                        id=new_id(),
                        anime_id=anime_id,
                        title=value,
                        normalized=normalized,
                        kind="alias",
                        source="user",
                        created_at=now,
                    )
                )
            record.version += 1
            record.updated_at = now
            append_event(
                session,
                name="CatalogTitlesChanged.v1",
                payload={"anime_id": anime_id},
            )
            record_event(
                session,
                event_type="catalog.titles_bound",
                entity_type="anime",
                entity_id=anime_id,
                payload={
                    "titles": values,
                    "keys": [key_kind for key_kind, _ in keys],
                },
            )
        return self.get_anime(anime_id)

    def resolve_title(self, title: str) -> CatalogTitleMatch:
        return self.resolve_titles([title])

    def find_title_binding_conflict(
        self, titles: list[str], current_anime_id: str
    ) -> CatalogTitleBindingConflict | None:
        """Find strong catalog evidence that a manual binding points at the wrong season."""
        values = list(
            dict.fromkeys(title.strip() for title in titles if _EXPLICIT_SEASON.search(title))
        )
        if not values:
            return None
        normalized_titles = {normalize_title_key(title)[:300]: title for title in values}
        with self._session_factory() as session:
            rows = list(
                session.execute(
                    select(AnimeTitleRecord.anime_id, AnimeTitleRecord.normalized).where(
                        AnimeTitleRecord.normalized.in_(normalized_titles)
                    )
                )
            )
        matches_by_key: dict[str, set[str]] = {}
        for anime_id, normalized in rows:
            matches_by_key.setdefault(normalized, set()).add(anime_id)
        evidence_by_anime: dict[str, list[str]] = {}
        for normalized, title in normalized_titles.items():
            anime_ids = matches_by_key.get(normalized, set())
            if len(anime_ids) != 1:
                continue
            anime_id = next(iter(anime_ids))
            if anime_id == current_anime_id:
                continue
            evidence_by_anime.setdefault(anime_id, []).append(title)
        if len(evidence_by_anime) != 1:
            return None
        suggested_anime_id, evidence_titles = next(iter(evidence_by_anime.items()))
        return CatalogTitleBindingConflict(suggested_anime_id, evidence_titles)

    def resolve_titles(self, titles: list[str]) -> CatalogTitleMatch:
        values = list(dict.fromkeys(title.strip() for title in titles if anime_title_key(title)))
        if not values:
            return CatalogTitleMatch("unmatched", None, None, None)
        signature = title_variant_signature(values)
        if len(values) > 1:
            with self._session_factory() as session:
                binding = session.scalar(
                    select(AnimeTitleBindingRecord).where(
                        AnimeTitleBindingRecord.key_kind == "variant_set",
                        AnimeTitleBindingRecord.match_key == signature,
                    )
                )
            if binding is not None:
                conflict = self.find_title_binding_conflict(values, binding.anime_id)
                if conflict is not None:
                    return CatalogTitleMatch(
                        "matched",
                        conflict.suggested_anime_id,
                        normalize_title_key(conflict.evidence_titles[0])[:300],
                        "exact_season",
                    )
                return CatalogTitleMatch(
                    "matched", binding.anime_id, signature, "manual_variant_set"
                )

        matches = [self._resolve_single_title(title) for title in values]
        if any(match.status == "ambiguous" for match in matches):
            return CatalogTitleMatch("ambiguous", None, signature, "variant_set")
        matched = [match for match in matches if match.anime_id is not None]
        anime_ids = {match.anime_id for match in matched}
        if len(anime_ids) > 1:
            return CatalogTitleMatch("ambiguous", None, signature, "variant_set")
        if len(anime_ids) == 1:
            first = matched[0]
            return CatalogTitleMatch("matched", first.anime_id, first.matched_key, first.method)
        return CatalogTitleMatch("unmatched", None, signature, None)

    def _resolve_single_title(self, title: str) -> CatalogTitleMatch:
        normalized = normalize_title_key(title)[:300]
        if not normalized:
            return CatalogTitleMatch("unmatched", None, None, None)
        with self._session_factory() as session:
            semantic = anime_title_key(title)[:300]
            exact_binding = session.scalar(
                select(AnimeTitleBindingRecord).where(
                    AnimeTitleBindingRecord.key_kind == "exact",
                    AnimeTitleBindingRecord.match_key == normalized,
                )
            )
            if exact_binding is not None:
                return CatalogTitleMatch(
                    "matched", exact_binding.anime_id, normalized, "manual_exact"
                )
            semantic_binding = session.scalar(
                select(AnimeTitleBindingRecord).where(
                    AnimeTitleBindingRecord.key_kind.in_(["semantic", "chinese_canonical"]),
                    AnimeTitleBindingRecord.match_key == semantic,
                )
            )
            if semantic_binding is not None:
                return CatalogTitleMatch(
                    "matched",
                    semantic_binding.anime_id,
                    semantic,
                    "manual_semantic",
                )
            exact_ids = set(
                session.scalars(
                    select(AnimeTitleRecord.anime_id).where(
                        AnimeTitleRecord.normalized == normalized
                    )
                )
            )
            if len(exact_ids) == 1:
                return CatalogTitleMatch("matched", exact_ids.pop(), normalized, "exact")
            if len(exact_ids) > 1:
                return CatalogTitleMatch("ambiguous", None, normalized, "exact")

            if not semantic:
                return CatalogTitleMatch("unmatched", None, normalized, None)
            semantic_ids = {
                anime_id
                for anime_id, candidate_title in session.execute(
                    select(AnimeTitleRecord.anime_id, AnimeTitleRecord.title)
                )
                if anime_title_key(candidate_title)[:300] == semantic
            }
        if len(semantic_ids) == 1:
            return CatalogTitleMatch("matched", semantic_ids.pop(), semantic, "semantic")
        if len(semantic_ids) > 1:
            return CatalogTitleMatch("ambiguous", None, semantic, "semantic")
        return CatalogTitleMatch("unmatched", None, semantic, None)

    def update_schedule(
        self,
        anime_id: str,
        *,
        air_date: str | None,
        episode_count: int | None,
        airing_weekday: int | None,
        airing_time: str | None,
        schedule_timezone: str,
        expected_version: int,
    ) -> Anime:
        from datetime import date, time
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        if air_date is not None:
            try:
                date.fromisoformat(air_date)
            except ValueError as error:
                raise ValueError("air date must use YYYY-MM-DD") from error
        if episode_count is not None and not 1 <= episode_count <= 1000:
            raise ValueError("episode count must be between 1 and 1000")
        if airing_weekday is not None and not 0 <= airing_weekday <= 6:
            raise ValueError("airing weekday must be between 0 and 6")
        if airing_time is not None:
            try:
                time.fromisoformat(airing_time)
            except ValueError as error:
                raise ValueError("airing time must use HH:MM") from error
            airing_time = airing_time[:5]
        try:
            ZoneInfo(schedule_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("unknown schedule timezone") from error
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(AnimeRecord, anime_id)
            if record is None:
                raise AnimeNotFoundError(anime_id)
            if record.version != expected_version:
                raise ValueError("anime version conflict")
            unchanged = (
                record.air_date == air_date
                and record.episode_count == episode_count
                and record.airing_weekday == airing_weekday
                and record.airing_time == airing_time
                and record.schedule_timezone == schedule_timezone
                and record.schedule_source == "manual"
            )
            if unchanged:
                return self.get_anime(anime_id)
            record.air_date = air_date
            record.episode_count = episode_count
            record.airing_weekday = airing_weekday
            record.airing_time = airing_time
            record.schedule_timezone = schedule_timezone
            record.schedule_source = "manual"
            record.schedule_updated_at = now
            record.version += 1
            record.updated_at = now
            record_event(
                session,
                event_type="catalog.schedule_updated",
                entity_type="anime",
                entity_id=anime_id,
                payload={"source": "manual"},
            )
        return self.get_anime(anime_id)

    def search_bangumi(self, query: str) -> CatalogSearchResult:
        value = query.strip()
        if len(value) < 2:
            raise ValueError("search query must contain at least 2 characters")
        request_key = f"bangumi:search:{normalize_title_key(value)}"
        now = self._clock()
        with self._session_factory() as session:
            cached = session.scalar(
                select(MetadataCacheRecord).where(MetadataCacheRecord.request_key == request_key)
            )
            if cached is not None and cached.expires_at > now:
                return CatalogSearchResult(
                    items=[BangumiAnime(**item) for item in cached.payload], stale=False
                )
        try:
            items = self._provider.search(value)
        except CatalogProviderError:
            if cached is None:
                raise
            return CatalogSearchResult(
                items=[BangumiAnime(**item) for item in cached.payload], stale=True
            )
        payload = [asdict(item) for item in items]
        with self._session_factory.begin() as session:
            session.execute(
                insert(MetadataCacheRecord)
                .values(
                    id=new_id(),
                    provider="bangumi",
                    request_key=request_key,
                    payload=payload,
                    fetched_at=now,
                    expires_at=now + timedelta(hours=6),
                )
                .on_conflict_do_update(
                    index_elements=["request_key"],
                    set_={
                        "payload": payload,
                        "fetched_at": now,
                        "expires_at": now + timedelta(hours=6),
                    },
                )
            )
        return CatalogSearchResult(items=items, stale=False)

    def list_season(
        self,
        start_date: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> CatalogSeasonResult:
        request_key = f"bangumi:season:v2:{start_date}:{end_date}"
        now = self._clock()
        with self._session_factory() as session:
            cached = session.scalar(
                select(MetadataCacheRecord).where(MetadataCacheRecord.request_key == request_key)
            )
            if cached is not None and cached.expires_at > now and not force_refresh:
                return CatalogSeasonResult(
                    items=[BangumiAnime(**item) for item in cached.payload],
                    fetched_at=cached.fetched_at,
                    stale=False,
                )
        try:
            items = self._provider.list_season(start_date, end_date)
        except CatalogProviderError:
            if cached is None:
                raise
            return CatalogSeasonResult(
                items=[BangumiAnime(**item) for item in cached.payload],
                fetched_at=cached.fetched_at,
                stale=True,
            )
        payload = [asdict(item) for item in items]
        with self._session_factory.begin() as session:
            session.execute(
                insert(MetadataCacheRecord)
                .values(
                    id=new_id(),
                    provider="bangumi",
                    request_key=request_key,
                    payload=payload,
                    fetched_at=now,
                    expires_at=now + timedelta(hours=24),
                )
                .on_conflict_do_update(
                    index_elements=["request_key"],
                    set_={
                        "payload": payload,
                        "fetched_at": now,
                        "expires_at": now + timedelta(hours=24),
                    },
                )
            )
        return CatalogSeasonResult(items=items, fetched_at=now, stale=False)

    def list_anime(self) -> list[Anime]:
        with self._session_factory() as session:
            ids = list(
                session.scalars(
                    select(AnimeRecord.id).order_by(AnimeRecord.updated_at.desc(), AnimeRecord.id)
                )
            )
        return [self.get_anime(anime_id) for anime_id in ids]

    def get_anime(self, anime_id: str) -> Anime:
        with self._session_factory() as session:
            record = session.get(AnimeRecord, anime_id)
            if record is None:
                raise AnimeNotFoundError(anime_id)
            titles = list(
                session.scalars(
                    select(AnimeTitleRecord)
                    .where(AnimeTitleRecord.anime_id == anime_id)
                    .order_by(AnimeTitleRecord.kind, AnimeTitleRecord.title)
                )
            )
            return Anime(
                id=record.id,
                bangumi_id=record.bangumi_id,
                primary_title=record.primary_title,
                title_zh=record.title_zh,
                title_ja=record.title_ja,
                title_en=record.title_en,
                summary=record.summary,
                air_date=record.air_date,
                episode_count=record.episode_count,
                airing_weekday=record.airing_weekday,
                airing_time=record.airing_time,
                schedule_timezone=record.schedule_timezone,
                schedule_source=record.schedule_source,
                schedule_updated_at=record.schedule_updated_at,
                cover_url=record.cover_url,
                source=record.source,
                version=record.version,
                titles=[
                    AnimeTitle(
                        title=item.title,
                        normalized=item.normalized,
                        kind=item.kind,
                        source=item.source,
                    )
                    for item in titles
                ],
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    def get_by_bangumi_id(self, bangumi_id: int) -> Anime | None:
        with self._session_factory() as session:
            anime_id = session.scalar(
                select(AnimeRecord.id).where(AnimeRecord.bangumi_id == bangumi_id)
            )
        return self.get_anime(anime_id) if anime_id is not None else None

    @staticmethod
    def _replace_titles(
        session: Session,
        anime_id: str,
        titles: list[tuple[str, str, str]],
    ) -> None:
        session.execute(delete(AnimeTitleRecord).where(AnimeTitleRecord.anime_id == anime_id))
        seen: set[str] = set()
        for title, kind, source in titles:
            normalized = normalize_title_key(title)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            session.add(
                AnimeTitleRecord(
                    id=new_id(),
                    anime_id=anime_id,
                    title=title.strip()[:300],
                    normalized=normalized[:300],
                    kind=kind,
                    source=source,
                )
            )
