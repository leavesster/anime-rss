from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.modules.audit.persistence import AuditEventRecord


def record_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    session.add(
        AuditEventRecord(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            correlation_id=correlation_id,
        )
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    correlation_id: str | None
    created_at: datetime


class AuditService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_events(self, *, limit: int = 100) -> list[AuditEvent]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(AuditEventRecord)
                    .order_by(AuditEventRecord.created_at.desc(), AuditEventRecord.id.desc())
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [
                AuditEvent(
                    id=item.id,
                    event_type=item.event_type,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    payload=item.payload,
                    correlation_id=item.correlation_id,
                    created_at=item.created_at,
                )
                for item in records
            ]
