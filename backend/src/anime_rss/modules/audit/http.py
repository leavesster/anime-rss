from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from anime_rss.modules.audit.api import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    correlation_id: str | None
    created_at: datetime


class AuditHttpServices(Protocol):
    audit: AuditService


@router.get("/events", response_model=list[AuditEventResponse])
def list_audit_events(request: Request, limit: int = 100) -> list[AuditEventResponse]:
    service = cast(AuditHttpServices, request.app.state.services).audit
    return [
        AuditEventResponse.model_validate(asdict(item))
        for item in service.list_events(limit=min(max(limit, 1), 500))
    ]
