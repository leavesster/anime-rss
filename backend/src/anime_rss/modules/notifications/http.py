from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, HttpUrl

from anime_rss.infrastructure.api import (
    PageCursor,
    PageLimit,
    page_response,
    requested_item_count,
)
from anime_rss.modules.notifications.adapters import WebhookError
from anime_rss.modules.notifications.api import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationConfigRequest(BaseModel):
    webhook_enabled: bool = False
    webhook_url: HttpUrl | None = None
    bearer_token: str | None = Field(default=None, max_length=2000)


class NotificationConfigResponse(BaseModel):
    webhook_enabled: bool
    webhook_url_redacted: str | None
    bearer_token_configured: bool
    version: int
    last_tested_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None


class NotificationResponse(BaseModel):
    id: str
    kind: str
    level: str
    title: str
    message: str
    entity_type: str | None
    entity_id: str | None
    read_at: datetime | None
    delivery_state: str | None
    delivery_error_code: str | None
    created_at: datetime


class DeliveryCycleResponse(BaseModel):
    delivered: int
    failed: int


class NotificationHttpServices(Protocol):
    notifications: NotificationService


def _service(request: Request) -> NotificationService:
    return cast(NotificationHttpServices, request.app.state.services).notifications


@router.get("/config", response_model=NotificationConfigResponse | None)
def get_config(request: Request) -> NotificationConfigResponse | None:
    value = _service(request).get_config()
    return NotificationConfigResponse.model_validate(asdict(value)) if value else None


@router.put("/config", response_model=NotificationConfigResponse)
def configure(
    payload: NotificationConfigRequest,
    request: Request,
    if_match: Annotated[int, Header()],
) -> NotificationConfigResponse:
    try:
        value = _service(request).configure(
            webhook_enabled=payload.webhook_enabled,
            webhook_url=str(payload.webhook_url) if payload.webhook_url else None,
            bearer_token=payload.bearer_token,
            expected_version=if_match,
        )
    except ValueError as error:
        status = 409 if str(error) == "notification config version conflict" else 422
        raise HTTPException(status_code=status, detail=str(error)) from error
    return NotificationConfigResponse.model_validate(asdict(value))


@router.post("/config/test", status_code=204)
def test_webhook(request: Request) -> None:
    try:
        _service(request).test_webhook()
    except (WebhookError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[NotificationResponse]:
    items = [
        NotificationResponse.model_validate(asdict(item))
        for item in _service(request).list_notifications(limit=requested_item_count(cursor, limit))
    ]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(notification_id: str, request: Request) -> NotificationResponse:
    try:
        value = _service(request).mark_read(notification_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return NotificationResponse.model_validate(asdict(value))


@router.post("/process", response_model=DeliveryCycleResponse)
def process_deliveries(request: Request) -> DeliveryCycleResponse:
    return DeliveryCycleResponse.model_validate(asdict(_service(request).process_deliveries()))
