from typing import Any

from sqlalchemy.orm import Session

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
