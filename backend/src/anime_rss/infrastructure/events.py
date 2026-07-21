from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now


class IntegrationEventRecord(Base):
    __tablename__ = "runtime_integration_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class IntegrationEventDeliveryRecord(Base):
    __tablename__ = "runtime_integration_event_deliveries"
    __table_args__ = (UniqueConstraint("event_id", "consumer", name="uq_event_consumer"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_integration_events.id", ondelete="CASCADE"), index=True
    )
    consumer: Mapped[str] = mapped_column(String(120))
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


@dataclass(frozen=True, slots=True)
class IntegrationEvent:
    id: str
    name: str
    version: int
    payload: dict[str, Any]
    occurred_at: datetime


def append_event(
    session: Session,
    *,
    name: str,
    payload: dict[str, Any],
    version: int = 1,
) -> str:
    record = IntegrationEventRecord(name=name, version=version, payload=payload)
    session.add(record)
    session.flush()
    return record.id


EventHandler = Callable[[IntegrationEvent], None]


@dataclass(frozen=True, slots=True)
class RegisteredHandler:
    consumer: str
    handler: EventHandler


class EventDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: dict[str, list[RegisteredHandler]],
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._handlers = handlers
        self._clock = clock

    def dispatch_pending(self, *, limit: int = 100) -> int:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(IntegrationEventRecord)
                    .order_by(IntegrationEventRecord.occurred_at, IntegrationEventRecord.id)
                    .limit(limit)
                )
            )

        delivered = 0
        for record in records:
            event = IntegrationEvent(
                id=record.id,
                name=record.name,
                version=record.version,
                payload=record.payload,
                occurred_at=record.occurred_at,
            )
            for registration in self._handlers.get(event.name, []):
                if self._already_delivered(event.id, registration.consumer):
                    continue
                registration.handler(event)
                self._mark_delivered(event.id, registration.consumer)
                delivered += 1
        return delivered

    def _already_delivered(self, event_id: str, consumer: str) -> bool:
        with self._session_factory() as session:
            statement = select(IntegrationEventDeliveryRecord.id).where(
                IntegrationEventDeliveryRecord.event_id == event_id,
                IntegrationEventDeliveryRecord.consumer == consumer,
            )
            return session.scalar(statement) is not None

    def _mark_delivered(self, event_id: str, consumer: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                insert(IntegrationEventDeliveryRecord)
                .values(
                    id=new_id(),
                    event_id=event_id,
                    consumer=consumer,
                    processed_at=self._clock(),
                )
                .on_conflict_do_nothing(index_elements=["event_id", "consumer"])
            )
