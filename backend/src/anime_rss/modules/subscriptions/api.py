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
    PreferenceProfileRecord,
    SubscriptionEpochRecord,
    SubscriptionRecord,
)

__all__ = ["Subscription", "SubscriptionService", "SubscriptionState"]

GLOBAL_PROFILE_ID = "default"


class AnimeCatalog(Protocol):
    def get_anime(self, anime_id: str) -> Anime: ...

    def add_aliases(self, anime_id: str, aliases: list[str]) -> Anime: ...


@dataclass(frozen=True, slots=True)
class Subscription:
    id: str
    anime_id: str
    anime_title: str
    state: str
    match_keys: list[str]
    rules: PreferenceRules
    uses_global_rules: bool
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


@dataclass(frozen=True, slots=True)
class PreferenceProfile:
    id: str
    name: str
    rules: PreferenceRules
    version: int
    updated_at: datetime | None


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
        use_global_rules: bool | None = None,
        aliases: list[str] | None = None,
        save_path: str | None = None,
    ) -> Subscription:
        anime = self._catalog.add_aliases(anime_id, aliases or [])
        now = self._clock()
        match_keys = self._match_keys(anime, aliases or [])
        subscription_id = new_id()
        with self._session_factory.begin() as session:
            if session.scalar(
                select(SubscriptionRecord.id).where(SubscriptionRecord.anime_id == anime_id)
            ):
                raise SubscriptionConflictError("anime already has a subscription")
            inherit_global = rules is None if use_global_rules is None else use_global_rules
            if inherit_global and rules is not None:
                raise ValueError(
                    "global rules and subscription rule override are mutually exclusive"
                )
            effective_rules = (
                self._global_rules(session) if inherit_global else (rules or PreferenceRules())
            )
            session.add(
                SubscriptionRecord(
                    id=subscription_id,
                    anime_id=anime_id,
                    anime_title=anime.primary_title,
                    state=SubscriptionState.FOLLOWING.value,
                    match_keys=match_keys,
                    rules=effective_rules.to_dict(),
                    use_global_rules=inherit_global,
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
        use_global_rules: bool | None = None,
        aliases: list[str] | None = None,
        save_path: str | None = None,
        expected_version: int | None = None,
    ) -> Subscription:
        now = self._clock()
        alias_anime = None
        if aliases is not None:
            current_subscription = self.get_subscription(subscription_id)
            alias_anime = self._catalog.add_aliases(current_subscription.anime_id, aliases)
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
                record.use_global_rules = False
            if use_global_rules is not None:
                if use_global_rules and rules is not None:
                    raise ValueError(
                        "global rules and subscription rule override are mutually exclusive"
                    )
                if use_global_rules and not record.use_global_rules:
                    record.rules = self._global_rules(session).to_dict()
                record.use_global_rules = use_global_rules
            if aliases is not None:
                assert alias_anime is not None
                record.match_keys = self._match_keys(alias_anime, aliases)
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
            global_rules = self._global_rules(session)
            return [self._to_subscription(record, global_rules) for record in records]

    def get_subscription(self, subscription_id: str) -> Subscription:
        with self._session_factory() as session:
            record = session.get(SubscriptionRecord, subscription_id)
            if record is None:
                raise SubscriptionNotFoundError(subscription_id)
            return self._to_subscription(record, self._global_rules(session))

    def get_global_preferences(self) -> PreferenceProfile:
        with self._session_factory() as session:
            record = session.get(PreferenceProfileRecord, GLOBAL_PROFILE_ID)
            if record is None:
                return PreferenceProfile(
                    id=GLOBAL_PROFILE_ID,
                    name="Default",
                    rules=PreferenceRules(),
                    version=0,
                    updated_at=None,
                )
            return self._to_profile(record)

    def update_global_preferences(
        self,
        rules: PreferenceRules,
        *,
        expected_version: int | None = None,
    ) -> PreferenceProfile:
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(PreferenceProfileRecord, GLOBAL_PROFILE_ID)
            current_version = record.version if record is not None else 0
            if expected_version is not None and expected_version != current_version:
                raise SubscriptionConflictError("preference profile version conflict")
            if record is None:
                record = PreferenceProfileRecord(
                    id=GLOBAL_PROFILE_ID,
                    name="Default",
                    rules=rules.to_dict(),
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.rules = rules.to_dict()
                record.version += 1
                record.updated_at = now
            record_event(
                session,
                event_type="subscription.global_preferences_updated",
                entity_type="preference_profile",
                entity_id=GLOBAL_PROFILE_ID,
                payload={"version": record.version},
            )
        return self.get_global_preferences()

    def get_for_selection(self, subscription_id: str) -> SelectionSubscription | None:
        try:
            subscription = self.get_subscription(subscription_id)
        except SubscriptionNotFoundError:
            return None
        return self._to_selection(subscription)

    def list_matching_for_selection(self, anime_id: str) -> list[SelectionSubscription]:
        return [
            self._to_selection(subscription)
            for subscription in self.list_subscriptions()
            if anime_id == subscription.anime_id
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
    def _global_rules(session: Session) -> PreferenceRules:
        record = session.get(PreferenceProfileRecord, GLOBAL_PROFILE_ID)
        return PreferenceRules.from_dict(record.rules if record is not None else None)

    @staticmethod
    def _to_subscription(record: SubscriptionRecord, global_rules: PreferenceRules) -> Subscription:
        return Subscription(
            id=record.id,
            anime_id=record.anime_id,
            anime_title=record.anime_title,
            state=record.state,
            match_keys=list(record.match_keys),
            rules=(
                global_rules if record.use_global_rules else PreferenceRules.from_dict(record.rules)
            ),
            uses_global_rules=record.use_global_rules,
            activation_at=record.activation_at,
            save_path=record.save_path,
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_profile(record: PreferenceProfileRecord) -> PreferenceProfile:
        return PreferenceProfile(
            id=record.id,
            name=record.name,
            rules=PreferenceRules.from_dict(record.rules),
            version=record.version,
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
