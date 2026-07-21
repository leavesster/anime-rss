from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.modules.recognition.api import (
    CandidateNotFoundError,
    RecognitionService,
    ReleaseRemapError,
)

router = APIRouter(prefix="/recognition", tags=["recognition"])


class CandidateResponse(BaseModel):
    id: str
    release_id: str
    source_title: str
    series_title: str
    series_key: str
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


class EpisodeGroupResponse(BaseModel):
    key: str
    series_title: str
    series_key: str
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
def list_episode_groups(request: Request, limit: int = 100) -> list[EpisodeGroupResponse]:
    services = cast(RecognitionHttpServices, request.app.state.services)
    groups = services.recognition.list_episode_groups(limit=min(max(limit, 1), 500))
    return [EpisodeGroupResponse.model_validate(asdict(group)) for group in groups]


@router.get("/unmatched", response_model=list[UnmatchedReleaseResponse])
def list_unmatched(request: Request, limit: int = 100) -> list[UnmatchedReleaseResponse]:
    services = cast(RecognitionHttpServices, request.app.state.services)
    releases = services.recognition.list_unmatched(limit=min(max(limit, 1), 500))
    return [UnmatchedReleaseResponse.model_validate(asdict(release)) for release in releases]


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
