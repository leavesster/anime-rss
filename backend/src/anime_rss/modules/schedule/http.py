from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

from anime_rss.modules.catalog.api import AnimeNotFoundError
from anime_rss.modules.schedule.api import ScheduleOverrideConflictError, ScheduleService

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


class EpisodeScheduleOverrideRequest(BaseModel):
    expected_at: datetime | None = None
    cancelled: bool = False
    source: str = "manual"
    note: str | None = None


class EpisodeScheduleOverrideResponse(BaseModel):
    id: str
    anime_id: str
    episode_key: str
    expected_at: datetime | None
    cancelled: bool
    source: str
    note: str | None
    version: int
    created_at: datetime
    updated_at: datetime


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


@router.get(
    "/anime/{anime_id}/overrides",
    response_model=list[EpisodeScheduleOverrideResponse],
)
def list_overrides(
    anime_id: str,
    request: Request,
) -> list[EpisodeScheduleOverrideResponse]:
    try:
        items = _service(request).list_overrides(anime_id)
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    return [EpisodeScheduleOverrideResponse.model_validate(asdict(item)) for item in items]


@router.put(
    "/anime/{anime_id}/overrides/{episode_key}",
    response_model=EpisodeScheduleOverrideResponse,
)
def put_override(
    anime_id: str,
    episode_key: str,
    payload: EpisodeScheduleOverrideRequest,
    request: Request,
    if_match: Annotated[int | None, Header()] = None,
) -> EpisodeScheduleOverrideResponse:
    try:
        item = _service(request).put_override(
            anime_id,
            episode_key,
            expected_at=payload.expected_at,
            cancelled=payload.cancelled,
            source=payload.source,
            note=payload.note,
            expected_version=if_match,
        )
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except ScheduleOverrideConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return EpisodeScheduleOverrideResponse.model_validate(asdict(item))


@router.delete(
    "/anime/{anime_id}/overrides/{episode_key}",
    status_code=204,
)
def delete_override(
    anime_id: str,
    episode_key: str,
    request: Request,
    if_match: Annotated[int | None, Header()] = None,
) -> Response:
    try:
        _service(request).delete_override(
            anime_id,
            episode_key,
            expected_version=if_match,
        )
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except ScheduleOverrideConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(status_code=204)


@router.get("/missing", response_model=list[ExpectedEpisodeResponse])
def missing(request: Request, limit: int = 100) -> list[ExpectedEpisodeResponse]:
    return [
        ExpectedEpisodeResponse.model_validate(asdict(item))
        for item in _service(request).list_missing(limit=limit)
    ]


@router.post("/sync", response_model=ScheduleSyncResponse)
def synchronize(request: Request) -> ScheduleSyncResponse:
    return ScheduleSyncResponse.model_validate(asdict(_service(request).synchronize()))
