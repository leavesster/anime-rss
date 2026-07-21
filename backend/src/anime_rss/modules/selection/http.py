from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from anime_rss.modules.selection.api import (
    SelectionCommandError,
    SelectionConflictError,
    SelectionService,
)

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
    confirmation_reason: dict[str, Any] | None
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
    coverage_status: str
    covered_episode_keys: list[str]
    already_covered_episode_keys: list[str]


class BackfillPreviewResponse(BaseModel):
    episode_key: str
    selected_candidate_id: str | None
    candidates: list[PreviewCandidateResponse]


class BackfillCommitRequest(BaseModel):
    episode_keys: list[str] = Field(min_length=1, max_length=100)


class CommandResultResponse(BaseModel):
    processed: int


class CandidateSelectRequest(BaseModel):
    replace_existing: bool = False
    override_filters: bool = False


class DecisionCommandResponse(BaseModel):
    decision_id: str


class ManualActionResponse(BaseModel):
    id: str
    subscription_id: str
    slot_id: str | None
    episode_key: str
    candidate_id: str | None
    release_id: str | None
    action: str
    reason: dict[str, Any]
    created_at: datetime


class SelectionHttpServices(Protocol):
    selection: SelectionService


def _service(request: Request) -> SelectionService:
    return cast(SelectionHttpServices, request.app.state.services).selection


@router.get("/episodes", response_model=list[EpisodeSlotResponse])
def list_episode_slots(
    request: Request, subscription_id: str | None = None, limit: int = 200
) -> list[EpisodeSlotResponse]:
    return [
        EpisodeSlotResponse.model_validate(asdict(item))
        for item in _service(request).list_slots(subscription_id=subscription_id, limit=limit)
    ]


@router.get("/decisions", response_model=list[DecisionResponse])
def list_decisions(
    request: Request, subscription_id: str | None = None, limit: int = 200
) -> list[DecisionResponse]:
    return [
        DecisionResponse.model_validate(asdict(item))
        for item in _service(request).list_decisions(subscription_id=subscription_id, limit=limit)
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


def _manual_command_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, SelectionConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


@router.post(
    "/subscriptions/{subscription_id}/candidates/{candidate_id}/select",
    response_model=DecisionCommandResponse,
)
def select_candidate(
    subscription_id: str,
    candidate_id: str,
    payload: CandidateSelectRequest,
    request: Request,
) -> DecisionCommandResponse:
    try:
        decision_id = _service(request).select_candidate(
            subscription_id,
            candidate_id,
            replace_existing=payload.replace_existing,
            override_filters=payload.override_filters,
        )
    except (LookupError, SelectionConflictError, SelectionCommandError) as error:
        raise _manual_command_error(error) from error
    return DecisionCommandResponse(decision_id=decision_id)


@router.post(
    "/subscriptions/{subscription_id}/candidates/{candidate_id}/reject",
    response_model=ManualActionResponse,
)
def reject_candidate(
    subscription_id: str, candidate_id: str, request: Request
) -> ManualActionResponse:
    try:
        action = _service(request).reject_candidate(subscription_id, candidate_id)
    except (LookupError, SelectionConflictError, SelectionCommandError) as error:
        raise _manual_command_error(error) from error
    return ManualActionResponse.model_validate(asdict(action))


@router.post(
    "/subscriptions/{subscription_id}/episodes/{episode_key}/reset",
    response_model=ManualActionResponse,
)
def reset_episode(subscription_id: str, episode_key: str, request: Request) -> ManualActionResponse:
    try:
        action = _service(request).reset_episode(subscription_id, episode_key)
    except (LookupError, SelectionConflictError, SelectionCommandError) as error:
        raise _manual_command_error(error) from error
    return ManualActionResponse.model_validate(asdict(action))


@router.post(
    "/subscriptions/{subscription_id}/episodes/{episode_key}/acquired-elsewhere",
    response_model=ManualActionResponse,
)
def mark_acquired_elsewhere(
    subscription_id: str, episode_key: str, request: Request
) -> ManualActionResponse:
    try:
        action = _service(request).mark_acquired_elsewhere(subscription_id, episode_key)
    except (LookupError, SelectionConflictError, SelectionCommandError) as error:
        raise _manual_command_error(error) from error
    return ManualActionResponse.model_validate(asdict(action))


@router.get("/manual-actions", response_model=list[ManualActionResponse])
def list_manual_actions(
    request: Request, subscription_id: str | None = None, limit: int = 200
) -> list[ManualActionResponse]:
    return [
        ManualActionResponse.model_validate(asdict(item))
        for item in _service(request).list_manual_actions(
            subscription_id=subscription_id, limit=limit
        )
    ]
