from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from anime_rss.infrastructure.api import (
    PageCursor,
    PageLimit,
    page_response,
    requested_item_count,
)
from anime_rss.modules.releases.api import ReleaseService

router = APIRouter(prefix="/releases", tags=["releases"])


class ReleaseResponse(BaseModel):
    id: str
    identity_kind: str
    identity_value: str
    btih: str | None
    btmh: str | None
    automation_eligible: bool
    first_seen_at: datetime
    source_count: int


class ReleaseHttpServices(Protocol):
    releases: ReleaseService


@router.get("", response_model=list[ReleaseResponse])
def list_releases(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[ReleaseResponse]:
    services = cast(ReleaseHttpServices, request.app.state.services)
    releases = services.releases.list_releases(limit=requested_item_count(cursor, limit))
    items = [ReleaseResponse.model_validate(asdict(release)) for release in releases]
    return page_response(items, response, cursor=cursor, limit=limit)
