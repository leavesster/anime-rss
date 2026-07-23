from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.modules.catalog.api import CatalogProviderError
from anime_rss.modules.seasonal.api import SeasonalAction, SeasonalOverview, SeasonalService
from anime_rss.modules.subscriptions.api import SubscriptionConflictError

router = APIRouter(prefix="/seasonal", tags=["seasonal"])


class SeasonalAnimeResponse(BaseModel):
    bangumi_id: int
    name: str
    name_cn: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    cover_url: str | None
    platform: str | None
    popularity: int
    rating_score: float | None
    rating_total: int
    status: str
    anime_id: str | None
    subscription_id: str | None


class SeasonalOverviewResponse(BaseModel):
    year: int
    quarter: int
    title: str
    fetched_at: datetime
    stale: bool
    items: list[SeasonalAnimeResponse]


class SeasonalActionResponse(BaseModel):
    bangumi_id: int
    status: str
    anime_id: str | None
    subscription_id: str | None


class SeasonalHttpServices(Protocol):
    seasonal: SeasonalService
    events: EventDispatcher


def _services(request: Request) -> SeasonalHttpServices:
    return cast(SeasonalHttpServices, request.app.state.services)


def _overview_response(value: SeasonalOverview) -> SeasonalOverviewResponse:
    return SeasonalOverviewResponse.model_validate(asdict(value))


def _action_response(value: SeasonalAction) -> SeasonalActionResponse:
    return SeasonalActionResponse.model_validate(asdict(value))


@router.get("", response_model=SeasonalOverviewResponse)
def get_seasonal_overview(
    request: Request,
    year: int | None = None,
    quarter: int | None = None,
) -> SeasonalOverviewResponse:
    try:
        return _overview_response(_services(request).seasonal.overview(year=year, quarter=quarter))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CatalogProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/refresh", response_model=SeasonalOverviewResponse)
def refresh_seasonal_overview(
    request: Request,
    year: int | None = None,
    quarter: int | None = None,
) -> SeasonalOverviewResponse:
    try:
        return _overview_response(
            _services(request).seasonal.overview(year=year, quarter=quarter, force_refresh=True)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CatalogProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/{bangumi_id}/follow", response_model=SeasonalActionResponse)
def follow_seasonal_anime(bangumi_id: int, request: Request) -> SeasonalActionResponse:
    try:
        action = _services(request).seasonal.follow(bangumi_id)
    except CatalogProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (SubscriptionConflictError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    _services(request).events.dispatch_until_idle()
    return _action_response(action)


@router.post("/{bangumi_id}/dismiss", response_model=SeasonalActionResponse)
def dismiss_seasonal_anime(bangumi_id: int, request: Request) -> SeasonalActionResponse:
    try:
        action = _services(request).seasonal.dismiss(bangumi_id)
    except (SubscriptionConflictError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    _services(request).events.dispatch_until_idle()
    return _action_response(action)


@router.post("/{bangumi_id}/watched", response_model=SeasonalActionResponse)
def mark_seasonal_anime_watched(bangumi_id: int, request: Request) -> SeasonalActionResponse:
    try:
        action = _services(request).seasonal.mark_watched(bangumi_id)
    except (SubscriptionConflictError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    _services(request).events.dispatch_until_idle()
    return _action_response(action)
