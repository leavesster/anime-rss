from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from anime_rss.modules.schedule.api import ScheduleService

router = APIRouter(prefix="/schedule", tags=["schedule"])


class ExpectedEpisodeResponse(BaseModel):
    id: str
    subscription_id: str
    anime_id: str
    anime_title: str
    episode_key: str
    expected_at: datetime
    local_date: str
    local_time: str
    state: str
    has_acceptable_candidate: bool
    schedule_source: str
    missing_notified_at: datetime | None
    updated_at: datetime


class CalendarDayResponse(BaseModel):
    date: str
    episodes: list[ExpectedEpisodeResponse]


class ScheduleSyncResponse(BaseModel):
    generated: int
    acquired: int
    missing: int
    notifications: int


class ScheduleHttpServices(Protocol):
    schedule: ScheduleService


def _service(request: Request) -> ScheduleService:
    return cast(ScheduleHttpServices, request.app.state.services).schedule


@router.get("/calendar", response_model=list[CalendarDayResponse])
def calendar(request: Request, days: int = 8) -> list[CalendarDayResponse]:
    try:
        items = _service(request).calendar(days=days)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return [CalendarDayResponse.model_validate(asdict(item)) for item in items]


@router.get("/anime/{anime_id}/episodes", response_model=list[ExpectedEpisodeResponse])
def anime_history(
    anime_id: str, request: Request, limit: int = 200
) -> list[ExpectedEpisodeResponse]:
    return [
        ExpectedEpisodeResponse.model_validate(asdict(item))
        for item in _service(request).anime_history(anime_id, limit=limit)
    ]


@router.get("/missing", response_model=list[ExpectedEpisodeResponse])
def missing(request: Request, limit: int = 100) -> list[ExpectedEpisodeResponse]:
    return [
        ExpectedEpisodeResponse.model_validate(asdict(item))
        for item in _service(request).list_missing(limit=limit)
    ]


@router.post("/sync", response_model=ScheduleSyncResponse)
def synchronize(request: Request) -> ScheduleSyncResponse:
    return ScheduleSyncResponse.model_validate(asdict(_service(request).synchronize()))
