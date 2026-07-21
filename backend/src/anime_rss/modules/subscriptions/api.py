from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.api import Anime, normalize_title_key
from anime_rss.modules.subscriptions.domain import (
    PreferenceRules,
    SubscriptionState,
    validate_state_transition,
)
from anime_rss.modules.subscriptions.persistence import (
    SubscriptionEpochRecord,
    SubscriptionRecord,
)


class AnimeCatalog(Protocol):
    def get_anime(self, anime_id: str) -> Anime: ...


@dataclass(frozen=True, slots=True)
class Subscription:
    id: str
    anime_id: str
    anime_title: str
    state: str
    match_keys: list[str]
    rules: PreferenceRules
    activation_at: datetime
    save_path: str | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SelectionSubscription:
    id: str
    anime_id: str
    anime_title: str
    state: str
    match_keys: frozenset[str]
    rules: PreferenceRules
    activation_at: datetime


class SubscriptionNotFoundError(LookupError):
    pass


class SubscriptionConflictError(RuntimeError):
    pass


class SubscriptionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        catalog: AnimeCatalog,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._catalog = catalog
        self._clock = clock

    def create_subscription(
        self,
        *,
        anime_id: str,
        rules: PreferenceRules | None = None,
        aliases: list[str] | None = None,
        save_path: str | None = None,
    ) -> Subscription:
        anime = self._catalog.get_anime(anime_id)
        now = self._clock()
        match_keys = self._match_keys(anime, aliases or [])
        subscription_id = new_id()
        with self._session_factory.begin() as session:
            if session.scalar(
                select(SubscriptionRecord.id).where(SubscriptionRecord.anime_id == anime_id)
            ):
                raise SubscriptionConflictError("anime already has a subscription")
            session.add(
                SubscriptionRecord(
                    id=subscription_id,
                    anime_id=anime_id,
                    anime_title=anime.primary_title,
                    state=SubscriptionState.FOLLOWING.value,
                    match_keys=match_keys,
                    rules=(rules or PreferenceRules()).to_dict(),
                    activation_at=now,
                    save_path=self._clean_path(save_path),
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                SubscriptionEpochRecord(
                    id=new_id(),
                    subscription_id=subscription_id,
                    started_at=now,
                    reason="created",
                )
            )
            record_event(
                session,
                event_type="subscription.created",
                entity_type="subscription",
                entity_id=subscription_id,
                payload={"anime_id": anime_id, "activation_at": now.isoformat()},
            )
        return self.get_subscription(subscription_id)

    def update_subscription(
        self,
        subscription_id: str,
        *,
        state: SubscriptionState | None = None,
        rules: PreferenceRules | None = None,
        aliases: list[str] | None = None,
        save_path: str | None = None,
        expected_version: int | None = None,
    ) -> Subscription:
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(SubscriptionRecord, subscription_id)
            if record is None:
                raise SubscriptionNotFoundError(subscription_id)
            if expected_version is not None and record.version != expected_version:
                raise SubscriptionConflictError("subscription version conflict")
            current = SubscriptionState(record.state)
            target = state or current
            validate_state_transition(current, target)
            if target != current:
                self._transition_epoch(session, record, current, target, now)
                record.state = target.value
            if rules is not None:
                record.rules = rules.to_dict()
            if aliases is not None:
                anime = self._catalog.get_anime(record.anime_id)
                record.match_keys = self._match_keys(anime, aliases)
            if save_path is not None:
                record.save_path = self._clean_path(save_path)
            record.version += 1
            record.updated_at = now
            record_event(
                session,
                event_type="subscription.updated",
                entity_type="subscription",
                entity_id=subscription_id,
                payload={"state": record.state, "version": record.version},
            )
        return self.get_subscription(subscription_id)

    def list_subscriptions(self) -> list[Subscription]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(SubscriptionRecord).order_by(
                        SubscriptionRecord.updated_at.desc(), SubscriptionRecord.id
                    )
                )
            )
            return [self._to_subscription(record) for record in records]

    def get_subscription(self, subscription_id: str) -> Subscription:
        with self._session_factory() as session:
            record = session.get(SubscriptionRecord, subscription_id)
            if record is None:
                raise SubscriptionNotFoundError(subscription_id)
            return self._to_subscription(record)

    def get_for_selection(self, subscription_id: str) -> SelectionSubscription | None:
        try:
            subscription = self.get_subscription(subscription_id)
        except SubscriptionNotFoundError:
            return None
        return self._to_selection(subscription)

    def list_matching_for_selection(self, series_key: str) -> list[SelectionSubscription]:
        return [
            self._to_selection(subscription)
            for subscription in self.list_subscriptions()
            if series_key in subscription.match_keys
        ]

    @staticmethod
    def _match_keys(anime: Anime, aliases: list[str]) -> list[str]:
        values = [title.normalized for title in anime.titles]
        values.extend(normalize_title_key(alias) for alias in aliases)
        return sorted({value for value in values if value})

    @staticmethod
    def _clean_path(value: str | None) -> str | None:
        if value is None:
            return None
        path = value.strip()
        if not path:
            return None
        if not path.startswith("/") or "\x00" in path:
            raise ValueError("save path must be absolute")
        return path[:1024]

    @staticmethod
    def _transition_epoch(
        session: Session,
        record: SubscriptionRecord,
        current: SubscriptionState,
        target: SubscriptionState,
        now: datetime,
    ) -> None:
        if current == SubscriptionState.FOLLOWING:
            session.execute(
                update(SubscriptionEpochRecord)
                .where(
                    SubscriptionEpochRecord.subscription_id == record.id,
                    SubscriptionEpochRecord.ended_at.is_(None),
                )
                .values(ended_at=now)
            )
        if target == SubscriptionState.FOLLOWING:
            record.activation_at = now
            session.add(
                SubscriptionEpochRecord(
                    id=new_id(),
                    subscription_id=record.id,
                    started_at=now,
                    reason="resumed",
                )
            )

    @staticmethod
    def _to_subscription(record: SubscriptionRecord) -> Subscription:
        return Subscription(
            id=record.id,
            anime_id=record.anime_id,
            anime_title=record.anime_title,
            state=record.state,
            match_keys=list(record.match_keys),
            rules=PreferenceRules.from_dict(record.rules),
            activation_at=record.activation_at,
            save_path=record.save_path,
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_selection(subscription: Subscription) -> SelectionSubscription:
        return SelectionSubscription(
            id=subscription.id,
            anime_id=subscription.anime_id,
            anime_title=subscription.anime_title,
            state=subscription.state,
            match_keys=frozenset(subscription.match_keys),
            rules=subscription.rules,
            activation_at=subscription.activation_at,
        )
