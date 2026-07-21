from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil, floor
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.api import Anime
from anime_rss.modules.schedule.persistence import ExpectedEpisodeRecord
from anime_rss.modules.selection.api import Decision, EpisodeSlot
from anime_rss.modules.subscriptions.api import Subscription
from anime_rss.modules.system.api import InstanceSettings


class CatalogQueries(Protocol):
    def list_anime(self) -> list[Anime]: ...


class SubscriptionQueries(Protocol):
    def list_subscriptions(self) -> list[Subscription]: ...


class SelectionQueries(Protocol):
    def list_slots(
        self, *, subscription_id: str | None = None, limit: int = 200
    ) -> list[EpisodeSlot]: ...

    def list_decisions(
        self, *, subscription_id: str | None = None, limit: int = 200
    ) -> list[Decision]: ...


class SettingsQueries(Protocol):
    def get(self) -> InstanceSettings: ...


@dataclass(frozen=True, slots=True)
class ExpectedEpisode:
    id: str
    subscription_id: str
    anime_id: str
    anime_title: str
    episode_key: str
    expected_at: datetime
    local_date: str
    local_time: str
    state: str
    has_acceptable_candidate: bool
    schedule_source: str
    missing_notified_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CalendarDay:
    date: str
    episodes: list[ExpectedEpisode]


@dataclass(frozen=True, slots=True)
class ScheduleSyncResult:
    generated: int
    acquired: int
    missing: int
    notifications: int


class ScheduleService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        catalog: CatalogQueries,
        subscriptions: SubscriptionQueries,
        selection: SelectionQueries,
        settings: SettingsQueries,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._catalog = catalog
        self._subscriptions = subscriptions
        self._selection = selection
        self._settings = settings
        self._clock = clock

    def synchronize(self) -> ScheduleSyncResult:
        now = self._clock()
        settings = self._settings.get()
        anime_by_id = {anime.id: anime for anime in self._catalog.list_anime()}
        slots = {
            (slot.subscription_id, slot.episode_key): slot
            for slot in self._selection.list_slots(limit=500)
        }
        decisions = {
            (decision.subscription_id, decision.episode_key)
            for decision in self._selection.list_decisions(limit=500)
        }
        generated = acquired = missing = notifications = 0
        for subscription in self._subscriptions.list_subscriptions():
            self._deactivate_stale(subscription, now)
            if subscription.state not in {"following", "paused"}:
                continue
            anime = anime_by_id.get(subscription.anime_id)
            if anime is None:
                continue
            for episode_key, expected_at in self._expected_times(
                anime,
                activation_at=subscription.activation_at,
                horizon=now + timedelta(days=8),
            ):
                generated += 1
                slot = slots.get((subscription.id, episode_key))
                is_acquired = (subscription.id, episode_key) in decisions or (
                    slot is not None and slot.state in {"decided", "acquired_elsewhere"}
                )
                has_acceptable = is_acquired or (
                    slot is not None and slot.state == "waiting_fallback"
                )
                if is_acquired:
                    state = "acquired"
                    acquired += 1
                elif (
                    subscription.state == "following"
                    and not has_acceptable
                    and now >= expected_at + timedelta(hours=settings.missing_episode_grace_hours)
                ):
                    state = "missing"
                    missing += 1
                else:
                    state = "scheduled"
                if self._upsert(
                    subscription=subscription,
                    anime=anime,
                    episode_key=episode_key,
                    expected_at=expected_at,
                    state=state,
                    has_acceptable=has_acceptable,
                    now=now,
                ):
                    notifications += 1
        return ScheduleSyncResult(generated, acquired, missing, notifications)

    def _deactivate_stale(self, subscription: Subscription, now: datetime) -> None:
        with self._session_factory.begin() as session:
            records = list(
                session.scalars(
                    select(ExpectedEpisodeRecord).where(
                        ExpectedEpisodeRecord.subscription_id == subscription.id,
                        ExpectedEpisodeRecord.state != "acquired",
                    )
                )
            )
            for record in records:
                if subscription.state == "paused" and record.state == "missing":
                    record.state = "scheduled"
                    record.updated_at = now
                elif subscription.state in {"completed", "archived"} or (
                    subscription.state == "following"
                    and record.expected_at < subscription.activation_at
                ):
                    record.state = "inactive"
                    record.updated_at = now

    def calendar(self, *, days: int = 8) -> list[CalendarDay]:
        if not 1 <= days <= 31:
            raise ValueError("calendar days must be between 1 and 31")
        timezone = ZoneInfo(self._settings.get().timezone)
        today = self._clock().astimezone(timezone).date()
        start = datetime.combine(today, time.min, timezone).astimezone(UTC)
        end = datetime.combine(today + timedelta(days=days), time.min, timezone).astimezone(UTC)
        records = self._records_between(start, end)
        grouped: dict[str, list[ExpectedEpisode]] = {
            (today + timedelta(days=offset)).isoformat(): [] for offset in range(days)
        }
        for record in records:
            item = self._to_expected(record, timezone)
            grouped[item.local_date].append(item)
        return [CalendarDay(day, grouped[day]) for day in sorted(grouped)]

    def anime_history(self, anime_id: str, *, limit: int = 200) -> list[ExpectedEpisode]:
        timezone = ZoneInfo(self._settings.get().timezone)
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(ExpectedEpisodeRecord)
                    .where(ExpectedEpisodeRecord.anime_id == anime_id)
                    .order_by(ExpectedEpisodeRecord.expected_at.desc(), ExpectedEpisodeRecord.id)
                    .limit(min(max(limit, 1), 500))
                )
            )
        return [self._to_expected(record, timezone) for record in records]

    def list_missing(self, *, limit: int = 100) -> list[ExpectedEpisode]:
        timezone = ZoneInfo(self._settings.get().timezone)
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(ExpectedEpisodeRecord)
                    .where(ExpectedEpisodeRecord.state == "missing")
                    .order_by(ExpectedEpisodeRecord.expected_at.desc(), ExpectedEpisodeRecord.id)
                    .limit(min(max(limit, 1), 500))
                )
            )
        return [self._to_expected(record, timezone) for record in records]

    @staticmethod
    def _expected_times(
        anime: Anime, *, activation_at: datetime, horizon: datetime
    ) -> list[tuple[str, datetime]]:
        if anime.air_date is None or anime.airing_time is None:
            return []
        try:
            first_date = date.fromisoformat(anime.air_date)
            hour, minute = (int(part) for part in anime.airing_time.split(":", 1))
            source_timezone = ZoneInfo(anime.schedule_timezone or "Asia/Tokyo")
            first_local = datetime.combine(first_date, time(hour, minute), source_timezone)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            return []
        first_at = first_local.astimezone(UTC)
        activation_delta = (activation_at - first_at).total_seconds() / (7 * 86400)
        first_episode = max(1, ceil(activation_delta) + 1)
        horizon_delta = (horizon - first_at).total_seconds() / (7 * 86400)
        last_episode = floor(horizon_delta) + 1
        if anime.episode_count is not None:
            last_episode = min(last_episode, anime.episode_count)
        if last_episode < first_episode:
            return []
        return [
            (str(number), first_at + timedelta(days=7 * (number - 1)))
            for number in range(first_episode, last_episode + 1)
        ]

    def _upsert(
        self,
        *,
        subscription: Subscription,
        anime: Anime,
        episode_key: str,
        expected_at: datetime,
        state: str,
        has_acceptable: bool,
        now: datetime,
    ) -> bool:
        notified = False
        with self._session_factory.begin() as session:
            expected_episode_id = new_id()
            session.execute(
                insert(ExpectedEpisodeRecord)
                .values(
                    id=expected_episode_id,
                    subscription_id=subscription.id,
                    anime_id=anime.id,
                    anime_title=anime.primary_title,
                    episode_key=episode_key,
                    expected_at=expected_at,
                    state=state,
                    has_acceptable_candidate=has_acceptable,
                    schedule_source=anime.schedule_source or "manual",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["subscription_id", "episode_key"],
                    set_={
                        "anime_title": anime.primary_title,
                        "expected_at": expected_at,
                        "state": state,
                        "has_acceptable_candidate": has_acceptable,
                        "schedule_source": anime.schedule_source or "manual",
                        "updated_at": now,
                    },
                )
            )
            record = session.scalar(
                select(ExpectedEpisodeRecord).where(
                    ExpectedEpisodeRecord.subscription_id == subscription.id,
                    ExpectedEpisodeRecord.episode_key == episode_key,
                )
            )
            assert record is not None
            claim = cast(
                CursorResult[Any],
                session.execute(
                    update(ExpectedEpisodeRecord)
                    .where(
                        ExpectedEpisodeRecord.id == record.id,
                        ExpectedEpisodeRecord.missing_notified_at.is_(None),
                        ExpectedEpisodeRecord.state == "missing",
                    )
                    .values(missing_notified_at=now)
                ),
            )
            if state == "missing" and claim.rowcount:
                append_event(
                    session,
                    name="EpisodeMissing.v1",
                    payload={
                        "expected_episode_id": record.id,
                        "subscription_id": subscription.id,
                        "anime_id": anime.id,
                        "anime_title": anime.primary_title,
                        "episode_key": episode_key,
                        "expected_at": expected_at.isoformat(),
                    },
                )
                record_event(
                    session,
                    event_type="schedule.episode_missing",
                    entity_type="expected_episode",
                    entity_id=record.id,
                    payload={"episode_key": episode_key},
                )
                notified = True
        return notified

    def _records_between(self, start: datetime, end: datetime) -> list[ExpectedEpisodeRecord]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(ExpectedEpisodeRecord)
                    .where(
                        ExpectedEpisodeRecord.expected_at >= start,
                        ExpectedEpisodeRecord.expected_at < end,
                    )
                    .order_by(ExpectedEpisodeRecord.expected_at, ExpectedEpisodeRecord.anime_title)
                )
            )

    @staticmethod
    def _to_expected(record: ExpectedEpisodeRecord, timezone: ZoneInfo) -> ExpectedEpisode:
        local = record.expected_at.astimezone(timezone)
        return ExpectedEpisode(
            id=record.id,
            subscription_id=record.subscription_id,
            anime_id=record.anime_id,
            anime_title=record.anime_title,
            episode_key=record.episode_key,
            expected_at=record.expected_at,
            local_date=local.date().isoformat(),
            local_time=local.strftime("%H:%M"),
            state=record.state,
            has_acceptable_candidate=record.has_acceptable_candidate,
            schedule_source=record.schedule_source,
            missing_notified_at=record.missing_notified_at,
            updated_at=record.updated_at,
        )
