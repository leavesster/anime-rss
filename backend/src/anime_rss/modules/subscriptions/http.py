from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from anime_rss.infrastructure.api import PageCursor, PageLimit, page_response
from anime_rss.infrastructure.events import EventDispatcher
from anime_rss.modules.catalog.api import AnimeNotFoundError
from anime_rss.modules.subscriptions.api import (
    PreferenceProfile,
    Subscription,
    SubscriptionConflictError,
    SubscriptionNotFoundError,
    SubscriptionService,
)
from anime_rss.modules.subscriptions.domain import PreferenceRules, SubscriptionState

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class PreferenceRulesModel(BaseModel):
    allowed_groups: list[str] = Field(default_factory=list, max_length=50)
    allowed_subtitles: list[str] = Field(
        default_factory=lambda: ["zh-Hans+zh-Hant", "zh-Hans", "zh-Hant"],
        max_length=20,
    )
    allowed_resolutions: list[str] = Field(default_factory=lambda: ["1080p", "720p"], max_length=20)
    allowed_codecs: list[str] = Field(default_factory=lambda: ["HEVC", "AVC", "AV1"], max_length=20)
    allowed_content_kinds: list[str] = Field(default_factory=lambda: ["episode"])
    preferred_groups: list[str] = Field(default_factory=list, max_length=50)
    preferred_subtitles: list[str] = Field(
        default_factory=lambda: ["zh-Hans+zh-Hant", "zh-Hans", "zh-Hant"],
        max_length=20,
    )
    preferred_resolutions: list[str] = Field(
        default_factory=lambda: ["1080p", "720p"], max_length=20
    )
    preferred_codecs: list[str] = Field(
        default_factory=lambda: ["HEVC", "AVC", "AV1"], max_length=20
    )
    fallback_wait_minutes: int = Field(default=120, ge=0, le=10080)

    def to_domain(self) -> PreferenceRules:
        return PreferenceRules.from_dict(self.model_dump())


class SubscriptionCreateRequest(BaseModel):
    anime_id: str
    aliases: list[str] = Field(default_factory=list, max_length=50)
    rules: PreferenceRulesModel | None = None
    use_global_rules: bool | None = None
    save_path: str | None = Field(default=None, max_length=1024)


class SubscriptionPatchRequest(BaseModel):
    state: SubscriptionState | None = None
    aliases: list[str] | None = Field(default=None, max_length=50)
    rules: PreferenceRulesModel | None = None
    use_global_rules: bool | None = None
    save_path: str | None = Field(default=None, max_length=1024)


class SubscriptionResponse(BaseModel):
    id: str
    anime_id: str
    anime_title: str
    state: str
    match_keys: list[str]
    rules: PreferenceRulesModel
    uses_global_rules: bool
    activation_at: datetime
    save_path: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class SubscriptionHttpServices(Protocol):
    subscriptions: SubscriptionService
    events: EventDispatcher


def _service(request: Request) -> SubscriptionService:
    return cast(SubscriptionHttpServices, request.app.state.services).subscriptions


def _response(value: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(asdict(value))


class PreferenceProfileResponse(BaseModel):
    id: str
    name: str
    rules: PreferenceRulesModel
    version: int
    updated_at: datetime | None


def _profile_response(value: PreferenceProfile) -> PreferenceProfileResponse:
    return PreferenceProfileResponse.model_validate(asdict(value))


@router.get("", response_model=list[SubscriptionResponse])
def list_subscriptions(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[SubscriptionResponse]:
    items = [_response(item) for item in _service(request).list_subscriptions()]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(
    payload: SubscriptionCreateRequest, request: Request
) -> SubscriptionResponse:
    try:
        value = _service(request).create_subscription(
            anime_id=payload.anime_id,
            rules=payload.rules.to_domain() if payload.rules is not None else None,
            use_global_rules=payload.use_global_rules,
            aliases=payload.aliases,
            save_path=payload.save_path,
        )
    except AnimeNotFoundError as error:
        raise HTTPException(status_code=404, detail="anime not found") from error
    except SubscriptionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    cast(SubscriptionHttpServices, request.app.state.services).events.dispatch_until_idle()
    return _response(value)


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
def update_subscription(
    subscription_id: str,
    payload: SubscriptionPatchRequest,
    request: Request,
    if_match: Annotated[int, Header()],
) -> SubscriptionResponse:
    try:
        value = _service(request).update_subscription(
            subscription_id,
            state=payload.state,
            rules=payload.rules.to_domain() if payload.rules is not None else None,
            use_global_rules=payload.use_global_rules,
            aliases=payload.aliases,
            save_path=payload.save_path,
            expected_version=if_match,
        )
    except SubscriptionNotFoundError as error:
        raise HTTPException(status_code=404, detail="subscription not found") from error
    except SubscriptionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (AnimeNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    cast(SubscriptionHttpServices, request.app.state.services).events.dispatch_until_idle()
    return _response(value)


@router.get("/preferences/global", response_model=PreferenceProfileResponse)
def get_global_preferences(request: Request) -> PreferenceProfileResponse:
    return _profile_response(_service(request).get_global_preferences())


@router.put("/preferences/global", response_model=PreferenceProfileResponse)
def update_global_preferences(
    payload: PreferenceRulesModel,
    request: Request,
    if_match: Annotated[int, Header()],
) -> PreferenceProfileResponse:
    try:
        profile = _service(request).update_global_preferences(
            payload.to_domain(), expected_version=if_match
        )
    except SubscriptionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _profile_response(profile)
