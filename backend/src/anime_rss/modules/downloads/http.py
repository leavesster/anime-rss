from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.modules.downloads.api import (
    DownloadConfigNotFoundError,
    DownloadService,
    DownloadTaskNotFoundError,
)
from anime_rss.modules.downloads.domain import DownloaderError

router = APIRouter(prefix="/downloads", tags=["downloads"])


class DownloadConfigRequest(BaseModel):
    base_url: HttpUrl
    username: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    default_save_path: str | None = Field(default=None, max_length=1024)
    default_category: str | None = Field(default=None, max_length=120)
    default_tags: list[str] = Field(default_factory=list, max_length=20)


class DownloadConfigResponse(BaseModel):
    adapter: str
    base_url_redacted: str
    username: str
    default_save_path: str | None
    default_category: str | None
    default_tags: list[str]
    password_configured: bool
    version: int
    last_tested_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None


class DownloadConnectionResponse(BaseModel):
    status: str
    version: str


class DownloadTaskResponse(BaseModel):
    id: str
    decision_id: str
    release_id: str
    subscription_id: str
    info_hash: str
    state: str
    requested_save_path: str | None
    actual_save_path: str | None
    category: str | None
    tags: list[str]
    progress: float
    stale: bool
    error_code: str | None
    attempt_count: int
    next_retry_at: datetime | None
    last_observed_at: datetime | None
    supersedes_decision_id: str | None
    superseded_by_decision_id: str | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DownloadCycleResponse(BaseModel):
    cancellations: int
    submissions: int
    reconciled: int
    dispatched_events: int


class DownloadHttpServices(Protocol):
    downloads: DownloadService
    events: EventDispatcher


def _services(request: Request) -> DownloadHttpServices:
    return cast(DownloadHttpServices, request.app.state.services)


@router.get("/config", response_model=DownloadConfigResponse | None)
def get_download_config(request: Request) -> DownloadConfigResponse | None:
    config = _services(request).downloads.get_config()
    return DownloadConfigResponse.model_validate(asdict(config)) if config else None


@router.put("/config", response_model=DownloadConfigResponse)
def configure_downloads(
    payload: DownloadConfigRequest,
    request: Request,
    if_match: Annotated[int | None, Header()] = None,
) -> DownloadConfigResponse:
    try:
        config = _services(request).downloads.configure(
            base_url=str(payload.base_url),
            username=payload.username,
            password=payload.password,
            default_save_path=payload.default_save_path,
            default_category=payload.default_category,
            default_tags=payload.default_tags,
            expected_version=if_match,
        )
    except ValueError as error:
        code = 409 if str(error) == "download config version conflict" else 422
        raise HTTPException(status_code=code, detail=str(error)) from error
    return DownloadConfigResponse.model_validate(asdict(config))


@router.post("/config/test", response_model=DownloadConnectionResponse)
def test_download_connection(request: Request) -> DownloadConnectionResponse:
    try:
        version = _services(request).downloads.test_connection()
    except DownloadConfigNotFoundError as error:
        raise HTTPException(status_code=409, detail="qBittorrent is not configured") from error
    except DownloaderError as error:
        raise HTTPException(status_code=502, detail=error.code) from error
    return DownloadConnectionResponse(status="connected", version=version)


@router.get("/tasks", response_model=list[DownloadTaskResponse])
def list_download_tasks(request: Request, limit: int = 200) -> list[DownloadTaskResponse]:
    tasks = _services(request).downloads.list_tasks(limit=min(max(limit, 1), 500))
    return [DownloadTaskResponse.model_validate(asdict(task)) for task in tasks]


@router.post("/tasks/{task_id}/retry", response_model=DownloadTaskResponse)
def retry_download_task(task_id: str, request: Request) -> DownloadTaskResponse:
    try:
        task = _services(request).downloads.retry_task(task_id)
    except DownloadTaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="download task not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return DownloadTaskResponse.model_validate(asdict(task))


@router.post("/process", response_model=DownloadCycleResponse)
def process_downloads(request: Request) -> DownloadCycleResponse:
    services = _services(request)
    dispatched = services.events.dispatch_until_idle(
        event_names={"DownloadRequested.v1", "DownloadCancellationRequested.v1"}
    )
    result = services.downloads.process_cycle()
    return DownloadCycleResponse(
        **asdict(result),
        dispatched_events=dispatched,
    )
