from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.api import Anime, CatalogSeasonResult
from anime_rss.modules.seasonal.persistence import SeasonalDecisionRecord
from anime_rss.modules.subscriptions.api import (
    Subscription,
    SubscriptionState,
)


class SeasonalCatalog(Protocol):
    def list_season(
        self, start_date: str, end_date: str, *, force_refresh: bool = False
    ) -> CatalogSeasonResult: ...

    def import_bangumi(self, bangumi_id: int) -> Anime: ...

    def get_by_bangumi_id(self, bangumi_id: int) -> Anime | None: ...


class SeasonalSubscriptions(Protocol):
    def list_subscriptions(self) -> list[Subscription]: ...

    def create_subscription(self, *, anime_id: str) -> Subscription: ...

    def update_subscription(
        self,
        subscription_id: str,
        *,
        state: SubscriptionState | None = None,
        expected_version: int | None = None,
    ) -> Subscription: ...


@dataclass(frozen=True, slots=True)
class SeasonalAnime:
    bangumi_id: int
    name: str
    name_cn: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    cover_url: str | None
    platform: str | None
    popularity: int
    rating_score: float | None
    rating_total: int
    status: str
    anime_id: str | None
    subscription_id: str | None


@dataclass(frozen=True, slots=True)
class SeasonalOverview:
    year: int
    quarter: int
    title: str
    fetched_at: datetime
    stale: bool
    items: list[SeasonalAnime]


@dataclass(frozen=True, slots=True)
class SeasonalAction:
    bangumi_id: int
    status: str
    anime_id: str | None
    subscription_id: str | None


class SeasonalService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        catalog: SeasonalCatalog,
        subscriptions: SeasonalSubscriptions,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._catalog = catalog
        self._subscriptions = subscriptions
        self._clock = clock

    def overview(
        self,
        *,
        year: int | None = None,
        quarter: int | None = None,
        force_refresh: bool = False,
    ) -> SeasonalOverview:
        selected_year, selected_quarter = self._resolve_period(year, quarter)
        start, end = self._quarter_bounds(selected_year, selected_quarter)
        catalog_result = self._catalog.list_season(
            start.isoformat(), end.isoformat(), force_refresh=force_refresh
        )
        subscriptions = self._subscriptions.list_subscriptions()
        subscriptions_by_anime = {item.anime_id: item for item in subscriptions}
        with self._session_factory() as session:
            decision_records = session.scalars(select(SeasonalDecisionRecord)).all()
            decisions = {record.bangumi_id: record.decision for record in decision_records}

        items: list[SeasonalAnime] = []
        for item in catalog_result.items:
            anime = self._catalog.get_by_bangumi_id(item.bangumi_id)
            subscription = subscriptions_by_anime.get(anime.id) if anime is not None else None
            if subscription is not None and subscription.state != SubscriptionState.ARCHIVED.value:
                status = subscription.state
            elif item.bangumi_id in decisions:
                status = decisions[item.bangumi_id]
            elif subscription is not None:
                status = "dismissed"
            else:
                status = "undecided"
            items.append(
                SeasonalAnime(
                    bangumi_id=item.bangumi_id,
                    name=item.name,
                    name_cn=item.name_cn,
                    summary=item.summary,
                    air_date=item.air_date,
                    episode_count=item.episode_count,
                    cover_url=item.cover_url,
                    platform=item.platform,
                    popularity=item.popularity,
                    rating_score=item.rating_score,
                    rating_total=item.rating_total,
                    status=status,
                    anime_id=anime.id if anime is not None else None,
                    subscription_id=subscription.id if subscription is not None else None,
                )
            )
        return SeasonalOverview(
            year=selected_year,
            quarter=selected_quarter,
            title=f"{selected_year} 年 {start.month} 月新番",
            fetched_at=catalog_result.fetched_at,
            stale=catalog_result.stale,
            items=items,
        )

    def follow(self, bangumi_id: int) -> SeasonalAction:
        anime = self._catalog.import_bangumi(bangumi_id)
        subscription = next(
            (
                item
                for item in self._subscriptions.list_subscriptions()
                if item.anime_id == anime.id
            ),
            None,
        )
        if subscription is None:
            subscription = self._subscriptions.create_subscription(anime_id=anime.id)
        elif subscription.state == SubscriptionState.ARCHIVED.value:
            subscription = self._subscriptions.update_subscription(
                subscription.id,
                state=SubscriptionState.PAUSED,
                expected_version=subscription.version,
            )
            subscription = self._subscriptions.update_subscription(
                subscription.id,
                state=SubscriptionState.FOLLOWING,
                expected_version=subscription.version,
            )
        elif subscription.state != SubscriptionState.FOLLOWING.value:
            subscription = self._subscriptions.update_subscription(
                subscription.id,
                state=SubscriptionState.FOLLOWING,
                expected_version=subscription.version,
            )
        with self._session_factory.begin() as session:
            session.execute(
                delete(SeasonalDecisionRecord).where(
                    SeasonalDecisionRecord.bangumi_id == bangumi_id
                )
            )
            record_event(
                session,
                event_type="seasonal.followed",
                entity_type="bangumi_subject",
                entity_id=str(bangumi_id),
                payload={"anime_id": anime.id, "subscription_id": subscription.id},
            )
        return SeasonalAction(
            bangumi_id=bangumi_id,
            status=subscription.state,
            anime_id=anime.id,
            subscription_id=subscription.id,
        )

    def mark_watched(self, bangumi_id: int) -> SeasonalAction:
        now = self._clock()
        anime = self._catalog.get_by_bangumi_id(bangumi_id)
        subscription = next(
            (
                item
                for item in self._subscriptions.list_subscriptions()
                if anime is not None and item.anime_id == anime.id
            ),
            None,
        )
        if subscription is not None and subscription.state != SubscriptionState.ARCHIVED.value:
            subscription = self._subscriptions.update_subscription(
                subscription.id,
                state=SubscriptionState.ARCHIVED,
                expected_version=subscription.version,
            )
        with self._session_factory.begin() as session:
            session.execute(
                insert(SeasonalDecisionRecord)
                .values(
                    bangumi_id=bangumi_id,
                    decision="watched",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["bangumi_id"],
                    set_={"decision": "watched", "updated_at": now},
                )
            )
            record_event(
                session,
                event_type="seasonal.watched",
                entity_type="bangumi_subject",
                entity_id=str(bangumi_id),
                payload={"subscription_id": subscription.id if subscription else None},
            )
        return SeasonalAction(
            bangumi_id=bangumi_id,
            status="watched",
            anime_id=anime.id if anime is not None else None,
            subscription_id=subscription.id if subscription is not None else None,
        )

    def dismiss(self, bangumi_id: int) -> SeasonalAction:
        now = self._clock()
        anime = self._catalog.get_by_bangumi_id(bangumi_id)
        subscription = next(
            (
                item
                for item in self._subscriptions.list_subscriptions()
                if anime is not None and item.anime_id == anime.id
            ),
            None,
        )
        if subscription is not None and subscription.state != SubscriptionState.ARCHIVED.value:
            subscription = self._subscriptions.update_subscription(
                subscription.id,
                state=SubscriptionState.ARCHIVED,
                expected_version=subscription.version,
            )
        with self._session_factory.begin() as session:
            session.execute(
                insert(SeasonalDecisionRecord)
                .values(
                    bangumi_id=bangumi_id,
                    decision="dismissed",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["bangumi_id"],
                    set_={"decision": "dismissed", "updated_at": now},
                )
            )
            record_event(
                session,
                event_type="seasonal.dismissed",
                entity_type="bangumi_subject",
                entity_id=str(bangumi_id),
                payload={"subscription_id": subscription.id if subscription else None},
            )
        return SeasonalAction(
            bangumi_id=bangumi_id,
            status="dismissed",
            anime_id=anime.id if anime is not None else None,
            subscription_id=subscription.id if subscription is not None else None,
        )

    def _resolve_period(self, year: int | None, quarter: int | None) -> tuple[int, int]:
        today = self._clock().date()
        selected_year = year if year is not None else today.year
        selected_quarter = quarter if quarter is not None else (today.month - 1) // 3 + 1
        if not 2000 <= selected_year <= 2100:
            raise ValueError("year must be between 2000 and 2100")
        if not 1 <= selected_quarter <= 4:
            raise ValueError("quarter must be between 1 and 4")
        return selected_year, selected_quarter

    @staticmethod
    def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        if quarter == 4:
            return start, date(year + 1, 1, 1)
        return start, date(year, start_month + 3, 1)
