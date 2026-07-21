from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from anime_rss.modules.selection.api import SelectionService

router = APIRouter(prefix="/selection", tags=["selection"])


class EpisodeSlotResponse(BaseModel):
    id: str
    subscription_id: str
    anime_title: str
    episode_key: str
    state: str
    fallback_deadline: datetime | None
    best_candidate_id: str | None
    selected_decision_id: str | None
    version: int
    updated_at: datetime


class DecisionResponse(BaseModel):
    id: str
    subscription_id: str
    anime_title: str
    episode_key: str
    candidate_id: str
    release_id: str
    kind: str
    reason: dict[str, Any]
    candidate_snapshot: dict[str, Any]
    created_at: datetime


class PreviewCandidateResponse(BaseModel):
    candidate_id: str
    source_title: str
    release_group: str | None
    eligible: bool
    preferred: bool
    rank: list[int | str]
    first_loss_field: str | None
    rejection_reasons: list[str]


class BackfillPreviewResponse(BaseModel):
    episode_key: str
    selected_candidate_id: str | None
    candidates: list[PreviewCandidateResponse]


class BackfillCommitRequest(BaseModel):
    episode_keys: list[str] = Field(min_length=1, max_length=100)


class CommandResultResponse(BaseModel):
    processed: int


class SelectionHttpServices(Protocol):
    selection: SelectionService


def _service(request: Request) -> SelectionService:
    return cast(SelectionHttpServices, request.app.state.services).selection


@router.get("/episodes", response_model=list[EpisodeSlotResponse])
def list_episode_slots(request: Request, limit: int = 200) -> list[EpisodeSlotResponse]:
    return [
        EpisodeSlotResponse.model_validate(asdict(item))
        for item in _service(request).list_slots(limit=limit)
    ]


@router.get("/decisions", response_model=list[DecisionResponse])
def list_decisions(request: Request, limit: int = 200) -> list[DecisionResponse]:
    return [
        DecisionResponse.model_validate(asdict(item))
        for item in _service(request).list_decisions(limit=limit)
    ]


@router.post("/process-due", response_model=CommandResultResponse)
def process_due(request: Request) -> CommandResultResponse:
    return CommandResultResponse(processed=_service(request).process_due())


@router.get(
    "/subscriptions/{subscription_id}/backfill-preview",
    response_model=list[BackfillPreviewResponse],
)
def preview_backfill(subscription_id: str, request: Request) -> list[BackfillPreviewResponse]:
    try:
        previews = _service(request).preview_backfill(subscription_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [BackfillPreviewResponse.model_validate(asdict(item)) for item in previews]


@router.post(
    "/subscriptions/{subscription_id}/backfill-commit",
    response_model=CommandResultResponse,
)
def commit_backfill(
    subscription_id: str,
    payload: BackfillCommitRequest,
    request: Request,
) -> CommandResultResponse:
    try:
        processed = _service(request).commit_backfill(subscription_id, payload.episode_keys)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return CommandResultResponse(processed=processed)
