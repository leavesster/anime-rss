from dataclasses import asdict
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

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
def list_releases(request: Request, limit: int = 100) -> list[ReleaseResponse]:
    services = cast(ReleaseHttpServices, request.app.state.services)
    releases = services.releases.list_releases(limit=min(max(limit, 1), 500))
    return [ReleaseResponse.model_validate(asdict(release)) for release in releases]
