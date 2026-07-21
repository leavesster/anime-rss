from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from anime_rss.modules.system.api import InstanceSettingsService

router = APIRouter(prefix="/system/settings", tags=["system"])


class InstanceSettingsResponse(BaseModel):
    timezone: str
    interface_language: str
    missing_episode_grace_hours: int
    setup_completed_steps: list[str]
    setup_completed: bool
    version: int
    updated_at: datetime | None


class InstanceSettingsUpdateRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=80)
    interface_language: str = Field(min_length=1, max_length=16)
    missing_episode_grace_hours: int = Field(ge=1, le=168)


class SettingsHttpServices(Protocol):
    settings: InstanceSettingsService


def _service(request: Request) -> InstanceSettingsService:
    return cast(SettingsHttpServices, request.app.state.services).settings


@router.get("", response_model=InstanceSettingsResponse)
def get_settings(request: Request) -> InstanceSettingsResponse:
    return InstanceSettingsResponse.model_validate(asdict(_service(request).get()))


@router.put("", response_model=InstanceSettingsResponse)
def update_settings(
    payload: InstanceSettingsUpdateRequest,
    request: Request,
    if_match: int = Header(alias="If-Match"),
) -> InstanceSettingsResponse:
    try:
        settings = _service(request).update(
            timezone=payload.timezone,
            interface_language=payload.interface_language,
            missing_episode_grace_hours=payload.missing_episode_grace_hours,
            expected_version=if_match,
        )
    except ValueError as error:
        status = 409 if "version conflict" in str(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from error
    return InstanceSettingsResponse.model_validate(asdict(settings))
