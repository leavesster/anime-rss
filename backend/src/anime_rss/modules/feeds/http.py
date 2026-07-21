from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from anime_rss.infrastructure.api import (
    PageCursor,
    PageLimit,
    page_response,
    requested_item_count,
)
from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.infrastructure.http import HttpFetchError
from anime_rss.modules.feeds.api import FeedConflictError, FeedNotFoundError, FeedService

router = APIRouter(prefix="/feeds", tags=["feeds"])


class FeedCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    interval_seconds: int = Field(default=600, ge=300, le=3600)
    headers: dict[str, str] = Field(default_factory=dict)


class FeedPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    interval_seconds: int | None = Field(default=None, ge=300, le=3600)
    headers: dict[str, str] | None = None


class FeedTestRequest(BaseModel):
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)


class FeedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url_redacted: str
    interval_seconds: int
    health: str
    consecutive_failures: int
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_fetch_at: datetime | None
    error_code: str | None
    version: int


class FeedEntryResponse(BaseModel):
    id: str
    feed_id: str
    title: str
    published_at: datetime | None
    link_redacted: str | None
    identity_strength: str
    release_status: str
    release_error_code: str | None
    first_seen_at: datetime


class FeedFetchResponse(BaseModel):
    id: str
    feed_id: str
    status: str
    http_status: int | None
    error_code: str | None
    entry_count: int
    new_entry_count: int
    started_at: datetime
    finished_at: datetime


class RefreshResponse(BaseModel):
    feed_id: str
    status: str
    entry_count: int
    new_entry_count: int
    health: str
    error_code: str | None
    dispatched_events: int


class FeedTestResponse(BaseModel):
    status: str
    entry_count: int
    preview_titles: list[str]
    error_code: str | None


class FeedHttpServices(Protocol):
    feeds: FeedService
    events: EventDispatcher


def _services(request: Request) -> FeedHttpServices:
    return cast(FeedHttpServices, request.app.state.services)


@router.post("", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
def create_feed(payload: FeedCreateRequest, request: Request) -> FeedResponse:
    try:
        feed = _services(request).feeds.create_feed(
            name=payload.name,
            url=str(payload.url),
            interval_seconds=payload.interval_seconds,
            headers=payload.headers,
        )
    except FeedConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FeedResponse.model_validate(feed)


@router.get("", response_model=list[FeedResponse])
def list_feeds(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[FeedResponse]:
    items = [FeedResponse.model_validate(feed) for feed in _services(request).feeds.list_feeds()]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.patch("/{feed_id}", response_model=FeedResponse)
def update_feed(
    feed_id: str,
    payload: FeedPatchRequest,
    request: Request,
    if_match: Annotated[int, Header()],
) -> FeedResponse:
    try:
        feed = _services(request).feeds.update_feed(
            feed_id,
            name=payload.name,
            url=str(payload.url) if payload.url is not None else None,
            interval_seconds=payload.interval_seconds,
            headers=payload.headers,
            expected_version=if_match,
        )
    except FeedNotFoundError as error:
        raise HTTPException(status_code=404, detail="feed not found") from error
    except FeedConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        code = 409 if str(error) == "feed version conflict" else 422
        raise HTTPException(status_code=code, detail=str(error)) from error
    return FeedResponse.model_validate(feed)


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed(feed_id: str, request: Request, if_match: Annotated[int, Header()]) -> Response:
    try:
        _services(request).feeds.delete_feed(feed_id, expected_version=if_match)
    except FeedNotFoundError as error:
        raise HTTPException(status_code=404, detail="feed not found") from error
    except FeedConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=FeedTestResponse)
def test_feed(payload: FeedTestRequest, request: Request) -> FeedTestResponse:
    result = _services(request).feeds.test_feed(url=str(payload.url), headers=payload.headers)
    return FeedTestResponse.model_validate(asdict(result))


@router.post("/{feed_id}/refresh", response_model=RefreshResponse)
def refresh_feed(feed_id: str, request: Request) -> RefreshResponse:
    services = _services(request)
    try:
        result = services.feeds.refresh_feed(feed_id)
    except FeedNotFoundError as error:
        raise HTTPException(status_code=404, detail="feed not found") from error
    try:
        dispatched = services.events.dispatch_until_idle()
    except HttpFetchError:
        dispatched = 0
    return RefreshResponse.model_validate({**asdict(result), "dispatched_events": dispatched})


@router.get("/{feed_id}/entries", response_model=list[FeedEntryResponse])
def list_feed_entries(
    feed_id: str,
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[FeedEntryResponse]:
    try:
        entries = _services(request).feeds.list_entries(
            feed_id, limit=requested_item_count(cursor, limit)
        )
    except FeedNotFoundError as error:
        raise HTTPException(status_code=404, detail="feed not found") from error
    items = [FeedEntryResponse.model_validate(asdict(entry)) for entry in entries]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.get("/{feed_id}/fetches", response_model=list[FeedFetchResponse])
def list_feed_fetches(
    feed_id: str,
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[FeedFetchResponse]:
    try:
        fetches = _services(request).feeds.list_fetches(
            feed_id, limit=requested_item_count(cursor, limit)
        )
    except FeedNotFoundError as error:
        raise HTTPException(status_code=404, detail="feed not found") from error
    items = [FeedFetchResponse.model_validate(asdict(fetch)) for fetch in fetches]
    return page_response(items, response, cursor=cursor, limit=limit)
