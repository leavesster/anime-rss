from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from anime_rss.infrastructure.api import (
    PageCursor,
    PageLimit,
    page_response,
    requested_item_count,
)
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
def list_audit_events(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[AuditEventResponse]:
    service = cast(AuditHttpServices, request.app.state.services).audit
    items = [
        AuditEventResponse.model_validate(asdict(item))
        for item in service.list_events(limit=requested_item_count(cursor, limit))
    ]
    return page_response(items, response, cursor=cursor, limit=limit)
