import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, cast

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.infrastructure.observability import (
    current_causation_id,
    current_correlation_id,
    new_correlation_id,
    observation_context,
)
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now

logger = logging.getLogger(__name__)


class IntegrationEventRecord(Base):
    __tablename__ = "runtime_integration_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
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
    correlation_id: str = ""
    causation_id: str | None = None


def append_event(
    session: Session,
    *,
    name: str,
    payload: dict[str, Any],
    version: int = 1,
) -> str:
    record = IntegrationEventRecord(
        name=name,
        version=version,
        payload=payload,
        correlation_id=current_correlation_id() or new_correlation_id(),
        causation_id=current_causation_id(),
    )
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

    def dispatch_pending(self, *, limit: int = 100, event_names: set[str] | None = None) -> int:
        delivered = 0
        for event_name, registrations in self._handlers.items():
            if event_names is not None and event_name not in event_names:
                continue
            for registration in registrations:
                remaining = limit - delivered
                if remaining <= 0:
                    return delivered
                records = self._pending_for_consumer(
                    event_name, registration.consumer, limit=remaining
                )
                for record in records:
                    event = IntegrationEvent(
                        id=record.id,
                        name=record.name,
                        version=record.version,
                        payload=record.payload,
                        correlation_id=record.correlation_id or new_correlation_id(),
                        causation_id=record.causation_id,
                        occurred_at=record.occurred_at,
                    )
                    with observation_context(
                        correlation_id=event.correlation_id,
                        causation_id=event.id,
                        module=registration.consumer.split(".", 1)[0],
                        operation=event.name,
                    ):
                        started_at = perf_counter()
                        try:
                            registration.handler(event)
                        except Exception:
                            logger.exception(
                                "integration_event.failed",
                                extra={
                                    "structured_fields": {
                                        "event_id": event.id,
                                        "consumer": registration.consumer,
                                        "duration_ms": round(
                                            (perf_counter() - started_at) * 1000, 2
                                        ),
                                        "outcome": "failed",
                                    }
                                },
                            )
                            raise
                        logger.info(
                            "integration_event.delivered",
                            extra={
                                "structured_fields": {
                                    "event_id": event.id,
                                    "consumer": registration.consumer,
                                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                                    "outcome": "success",
                                }
                            },
                        )
                    self._mark_delivered(event.id, registration.consumer)
                    delivered += 1
        return delivered

    def dispatch_until_idle(
        self,
        *,
        batch_size: int = 100,
        max_deliveries: int = 1000,
        event_names: set[str] | None = None,
    ) -> int:
        total = 0
        while total < max_deliveries:
            delivered = self.dispatch_pending(
                limit=min(batch_size, max_deliveries - total), event_names=event_names
            )
            total += delivered
            if delivered == 0:
                break
        return total

    def prune_delivered(self, *, before: datetime) -> int:
        removable: list[str] = []
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(IntegrationEventRecord)
                    .where(IntegrationEventRecord.occurred_at < before)
                    .order_by(IntegrationEventRecord.occurred_at)
                )
            )
            for record in records:
                expected = len(self._handlers.get(record.name, []))
                delivered_consumers = set(
                    session.scalars(
                        select(IntegrationEventDeliveryRecord.consumer).where(
                            IntegrationEventDeliveryRecord.event_id == record.id
                        )
                    )
                )
                registered_consumers = {
                    registration.consumer for registration in self._handlers.get(record.name, [])
                }
                if expected == 0 or registered_consumers.issubset(delivered_consumers):
                    removable.append(record.id)
        if not removable:
            return 0
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(IntegrationEventRecord).where(IntegrationEventRecord.id.in_(removable))
                ),
            )
            return result.rowcount

    def _pending_for_consumer(
        self, event_name: str, consumer: str, *, limit: int
    ) -> list[IntegrationEventRecord]:
        with self._session_factory() as session:
            delivered = select(IntegrationEventDeliveryRecord.id).where(
                IntegrationEventDeliveryRecord.event_id == IntegrationEventRecord.id,
                IntegrationEventDeliveryRecord.consumer == consumer,
            )
            statement = (
                select(IntegrationEventRecord)
                .where(IntegrationEventRecord.name == event_name, ~delivered.exists())
                .order_by(IntegrationEventRecord.occurred_at, IntegrationEventRecord.id)
                .limit(limit)
            )
            return list(session.scalars(statement))

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
