from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from anime_rss.modules.recognition.api import RecognitionService

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
