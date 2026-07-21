from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

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
    cover_url: str | None
    source: str
    titles: list[AnimeTitleResponse]
    created_at: datetime
    updated_at: datetime


class LocalAnimeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class AliasCreateRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


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
def list_anime(request: Request) -> list[AnimeResponse]:
    return [AnimeResponse.model_validate(asdict(item)) for item in _service(request).list_anime()]


@router.post("/anime", response_model=AnimeResponse, status_code=status.HTTP_201_CREATED)
def create_local_anime(payload: LocalAnimeCreateRequest, request: Request) -> AnimeResponse:
    try:
        anime = _service(request).create_local(title=payload.title, aliases=payload.aliases)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AnimeResponse.model_validate(asdict(anime))


@router.post("/anime/{anime_id}/aliases", response_model=AnimeResponse)
def add_alias(anime_id: str, payload: AliasCreateRequest, request: Request) -> AnimeResponse:
    try:
        anime = _service(request).add_alias(anime_id, payload.alias)
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
