from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.adapters import BangumiAnime, CatalogProviderError
from anime_rss.modules.catalog.domain import normalize_title_key as _normalize_title_key
from anime_rss.modules.catalog.persistence import (
    AnimeRecord,
    AnimeTitleRecord,
    MetadataCacheRecord,
)


class CatalogProvider(Protocol):
    def search(self, query: str, *, limit: int = 12) -> list[BangumiAnime]: ...

    def get(self, bangumi_id: int) -> BangumiAnime: ...


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
    titles: list[AnimeTitle]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    items: list[BangumiAnime]
    stale: bool


class AnimeNotFoundError(LookupError):
    pass


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
            anime_id = record.id
        return self.get_anime(anime_id)

    def add_alias(self, anime_id: str, alias: str) -> Anime:
        value = alias.strip()
        normalized = normalize_title_key(value)
        if not normalized:
            raise ValueError("alias is required")
        with self._session_factory.begin() as session:
            if session.get(AnimeRecord, anime_id) is None:
                raise AnimeNotFoundError(anime_id)
            session.execute(
                insert(AnimeTitleRecord)
                .values(
                    id=new_id(),
                    anime_id=anime_id,
                    title=value[:300],
                    normalized=normalized[:300],
                    kind="alias",
                    source="user",
                    created_at=self._clock(),
                )
                .on_conflict_do_nothing(index_elements=["anime_id", "normalized"])
            )
            record_event(
                session,
                event_type="catalog.alias_added",
                entity_type="anime",
                entity_id=anime_id,
                payload={"alias": value[:300]},
            )
        return self.get_anime(anime_id)

    def update_schedule(
        self,
        anime_id: str,
        *,
        air_date: str | None,
        episode_count: int | None,
        airing_weekday: int | None,
        airing_time: str | None,
        schedule_timezone: str,
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
            record.air_date = air_date
            record.episode_count = episode_count
            record.airing_weekday = airing_weekday
            record.airing_time = airing_time
            record.schedule_timezone = schedule_timezone
            record.schedule_source = "manual"
            record.schedule_updated_at = now
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
