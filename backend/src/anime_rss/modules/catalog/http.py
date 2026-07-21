from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from anime_rss.infrastructure.api import PageCursor, PageLimit, page_response
from anime_rss.modules.catalog.adapters import CatalogProviderError
from anime_rss.modules.catalog.api import AnimeNotFoundError, CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


class AnimeTitleResponse(BaseModel):
    title: str
    normalized: str
    kind: str
    source: str


class AnimeResponse(BaseModel):
    id: str
    bangumi_id: int | None
    primary_title: str
    title_zh: str | None
    title_ja: str | None
    title_en: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    airing_weekday: int | None
    airing_time: str | None
    schedule_timezone: str | None
    schedule_source: str | None
    schedule_updated_at: datetime | None
    cover_url: str | None
    source: str
    version: int
    titles: list[AnimeTitleResponse]
    created_at: datetime
    updated_at: datetime


class LocalAnimeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class AliasCreateRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


class AnimeScheduleUpdateRequest(BaseModel):
    air_date: str | None = Field(default=None, max_length=10)
    episode_count: int | None = Field(default=None, ge=1, le=1000)
    airing_weekday: int | None = Field(default=None, ge=0, le=6)
    airing_time: str | None = Field(default=None, max_length=5)
    schedule_timezone: str = Field(default="Asia/Tokyo", min_length=1, max_length=80)


class BangumiAnimeResponse(BaseModel):
    bangumi_id: int
    name: str
    name_cn: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    cover_url: str | None
    aliases: list[str]


class CatalogSearchResponse(BaseModel):
    items: list[BangumiAnimeResponse]
    stale: bool


class CatalogHttpServices(Protocol):
    catalog: CatalogService


def _service(request: Request) -> CatalogService:
    return cast(CatalogHttpServices, request.app.state.services).catalog


@router.get("/anime", response_model=list[AnimeResponse])
def list_anime(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[AnimeResponse]:
    items = [AnimeResponse.model_validate(asdict(item)) for item in _service(request).list_anime()]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.post("/anime", response_model=AnimeResponse, status_code=status.HTTP_201_CREATED)
def create_local_anime(payload: LocalAnimeCreateRequest, request: Request) -> AnimeResponse:
    try:
        anime = _service(request).create_local(title=payload.title, aliases=payload.aliases)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AnimeResponse.model_validate(asdict(anime))


@router.post("/anime/{anime_id}/aliases", response_model=AnimeResponse)
def add_alias(
    anime_id: str,
    payload: AliasCreateRequest,
    request: Request,
    if_match: Annotated[int | None, Header()] = None,
) -> AnimeResponse:
    if if_match is None:
        raise HTTPException(status_code=428, detail="If-Match header is required")
    try:
        anime = _service(request).add_alias(anime_id, payload.alias, expected_version=if_match)
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except ValueError as error:
        status_code = 409 if str(error) == "anime version conflict" else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return AnimeResponse.model_validate(asdict(anime))


@router.put("/anime/{anime_id}/schedule", response_model=AnimeResponse)
def update_schedule(
    anime_id: str,
    payload: AnimeScheduleUpdateRequest,
    request: Request,
    if_match: Annotated[int, Header()],
) -> AnimeResponse:
    try:
        anime = _service(request).update_schedule(
            anime_id,
            air_date=payload.air_date,
            episode_count=payload.episode_count,
            airing_weekday=payload.airing_weekday,
            airing_time=payload.airing_time,
            schedule_timezone=payload.schedule_timezone,
            expected_version=if_match,
        )
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except ValueError as error:
        status_code = 409 if str(error) == "anime version conflict" else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return AnimeResponse.model_validate(asdict(anime))


@router.get("/bangumi/search", response_model=CatalogSearchResponse)
def search_bangumi(request: Request, query: str) -> CatalogSearchResponse:
    try:
        result = _service(request).search_bangumi(query)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CatalogProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return CatalogSearchResponse(
        items=[BangumiAnimeResponse.model_validate(asdict(item)) for item in result.items],
        stale=result.stale,
    )


@router.post("/bangumi/{bangumi_id}/import", response_model=AnimeResponse)
def import_bangumi(bangumi_id: int, request: Request) -> AnimeResponse:
    try:
        anime = _service(request).import_bangumi(bangumi_id)
    except CatalogProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AnimeResponse.model_validate(asdict(anime))
