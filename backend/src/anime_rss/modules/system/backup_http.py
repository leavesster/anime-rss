import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from anime_rss.config import Settings
from anime_rss.infrastructure.api import PageCursor, PageLimit, page_response
from anime_rss.modules.system.backup import BackupError, BackupService

router = APIRouter(prefix="/system/backups", tags=["backups"])


class BackupResponse(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime
    reason: str


class RestoreResponse(BaseModel):
    backup_filename: str
    created_at: datetime
    restart_required: bool


class BackupHttpServices(Protocol):
    backups: BackupService


def _service(request: Request) -> BackupService:
    return cast(BackupHttpServices, request.app.state.services).backups


@router.get("", response_model=list[BackupResponse])
def list_backups(
    request: Request,
    response: Response,
    limit: PageLimit = 100,
    cursor: PageCursor = None,
) -> list[BackupResponse]:
    items = [
        BackupResponse.model_validate(asdict(item)) for item in _service(request).list_backups()
    ]
    return page_response(items, response, cursor=cursor, limit=limit)


@router.post("", response_model=BackupResponse)
def create_backup(request: Request) -> BackupResponse:
    try:
        result = _service(request).create_backup()
    except BackupError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return BackupResponse.model_validate(asdict(result))


@router.get("/{filename}", response_class=FileResponse)
def download_backup(filename: str, request: Request) -> FileResponse:
    try:
        path = _service(request).backup_path(filename)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except BackupError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/restore/stage", response_model=RestoreResponse)
async def stage_restore(request: Request) -> RestoreResponse:
    settings: Settings = request.app.state.settings
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.backup_max_restore_bytes:
        raise HTTPException(status_code=413, detail="backup archive is too large")
    with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as temporary:
        path = Path(temporary.name)
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.backup_max_restore_bytes:
                    raise HTTPException(status_code=413, detail="backup archive is too large")
                temporary.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    try:
        result = _service(request).stage_restore(path)
    except BackupError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        path.unlink(missing_ok=True)
    return RestoreResponse.model_validate(asdict(result))
