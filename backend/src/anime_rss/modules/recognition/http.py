from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from anime_rss.infrastructure.api import (
    PageCursor,
    PageLimit,
    page_response,
    requested_item_count,
)
from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.modules.recognition.api import (
    CandidateNotFoundError,
    RecognitionService,
    ReleaseDismissError,
    ReleaseRemapError,
)

router = APIRouter(prefix="/recognition", tags=["recognition"])


class CandidateResponse(BaseModel):
    id: str
    release_id: str
    source_title: str
    series_title: str
    title_variants: list[str]
    series_key: str
    anime_id: str | None
    catalog_match_status: str
    catalog_match_method: str | None
    catalog_match_key: str | None
    season: int | None
    episode_start: str
    episode_end: str | None
    episode_key: str
    release_group: str | None
    resolution: str | None
    video_codec: str | None
    subtitle_language: str | None
    revision: int
    content_kind: str
    confidence: str
    recognition_eligible: bool
    first_seen_at: datetime
    supersedes_candidate_id: str | None
    superseded_by_candidate_id: str | None
    superseded_at: datetime | None
    source_url: str | None = None


class EpisodeGroupResponse(BaseModel):
    key: str
    series_title: str
    series_key: str
    series_identity: str
    anime_id: str | None
    catalog_match_status: str
    season: int | None
    episode_key: str
    candidate_count: int
    candidates: list[CandidateResponse]
    latest_seen_at: datetime


class UnmatchedReleaseResponse(BaseModel):
    id: str
    release_id: str
    source_title: str
    confidence: str
    reason_code: str
    parsed_at: datetime
    source_url: str | None = None


class RecognitionRerunResponse(BaseModel):
    attempt_id: str
    release_id: str
    parser_version: str
    parsed_at: datetime
    confidence: str
    reason_code: str
    candidate_id: str | None
    previous_candidate_id: str | None
    candidate_changed: bool
    candidate_adopted: bool


class RecognitionHttpServices(Protocol):
    recognition: RecognitionService
    events: EventDispatcher


class ReleaseRemapRequest(BaseModel):
    series_title: str = Field(min_length=1, max_length=300)
    episode_start: str = Field(min_length=1, max_length=24)
    episode_end: str | None = Field(default=None, max_length=24)
    season: int | None = Field(default=None, ge=0, le=99)
    release_group: str | None = Field(default=None, max_length=120)


@router.get("/episode-groups", response_model=list[EpisodeGroupResponse])
def list_episode_groups(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[EpisodeGroupResponse]:
    services = cast(RecognitionHttpServices, request.app.state.services)
    groups = services.recognition.list_episode_groups(limit=requested_item_count(cursor, limit))
    items = [EpisodeGroupResponse.model_validate(asdict(group)) for group in groups]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.get("/unmatched", response_model=list[UnmatchedReleaseResponse])
def list_unmatched(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[UnmatchedReleaseResponse]:
    services = cast(RecognitionHttpServices, request.app.state.services)
    releases = services.recognition.list_unmatched(limit=requested_item_count(cursor, limit))
    items = [UnmatchedReleaseResponse.model_validate(asdict(release)) for release in releases]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.post("/releases/{release_id}/dismiss", status_code=204)
def dismiss_release(release_id: str, request: Request) -> None:
    services = cast(RecognitionHttpServices, request.app.state.services)
    try:
        services.recognition.dismiss_release(release_id)
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail="release not found") from error
    except ReleaseDismissError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/candidates/{candidate_id}/confirm", response_model=CandidateResponse)
def confirm_candidate(candidate_id: str, request: Request) -> CandidateResponse:
    services = cast(RecognitionHttpServices, request.app.state.services)
    try:
        candidate = services.recognition.confirm_candidate(candidate_id)
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail="candidate not found") from error
    services.events.dispatch_until_idle()
    return CandidateResponse.model_validate(asdict(candidate))


@router.post("/releases/{release_id}/remap", response_model=CandidateResponse)
def remap_release(
    release_id: str, payload: ReleaseRemapRequest, request: Request
) -> CandidateResponse:
    services = cast(RecognitionHttpServices, request.app.state.services)
    try:
        candidate = services.recognition.remap_release(
            release_id,
            series_title=payload.series_title,
            episode_start=payload.episode_start,
            episode_end=payload.episode_end,
            season=payload.season,
            release_group=payload.release_group,
        )
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail="release not found") from error
    except ReleaseRemapError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    services.events.dispatch_until_idle()
    return CandidateResponse.model_validate(asdict(candidate))


@router.post("/releases/{release_id}/rerun", response_model=RecognitionRerunResponse)
def rerun_release(release_id: str, request: Request) -> RecognitionRerunResponse:
    services = cast(RecognitionHttpServices, request.app.state.services)
    try:
        result = services.recognition.rerun_release(release_id)
    except CandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail="release not found") from error
    services.events.dispatch_until_idle()
    return RecognitionRerunResponse.model_validate(asdict(result))
