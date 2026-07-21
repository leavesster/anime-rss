from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from anime_rss.config import Settings
from anime_rss.modules.system.auth import (
    AuthenticationError,
    AuthService,
    CreatedSession,
    SetupConflictError,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
SESSION_COOKIE = "anime_rss_session"
CSRF_COOKIE = "anime_rss_csrf"


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class AuthStatusResponse(BaseModel):
    enabled: bool
    setup_required: bool
    authenticated: bool
    username: str | None


class SessionResponse(BaseModel):
    username: str
    expires_at: datetime


class AuthHttpServices(Protocol):
    auth: AuthService


def _service(request: Request) -> AuthService:
    return cast(AuthHttpServices, request.app.state.services).auth


def _set_session_cookies(response: Response, created: CreatedSession, settings: Settings) -> None:
    max_age = max(
        0, int((created.expires_at - datetime.now(created.expires_at.tzinfo)).total_seconds())
    )
    response.set_cookie(
        SESSION_COOKIE,
        created.token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        created.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(request: Request) -> AuthStatusResponse:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return AuthStatusResponse(
            enabled=False, setup_required=False, authenticated=True, username=None
        )
    state = _service(request).status(request.cookies.get(SESSION_COOKIE))
    return AuthStatusResponse(
        enabled=True,
        setup_required=state.setup_required,
        authenticated=state.authenticated,
        username=state.username,
    )


@router.post("/setup", response_model=SessionResponse)
def setup(payload: CredentialsRequest, request: Request, response: Response) -> SessionResponse:
    try:
        created = _service(request).setup(username=payload.username, password=payload.password)
    except SetupConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _set_session_cookies(response, created, request.app.state.settings)
    return SessionResponse(username=created.username, expires_at=created.expires_at)


@router.post("/login", response_model=SessionResponse)
def login(payload: CredentialsRequest, request: Request, response: Response) -> SessionResponse:
    try:
        created = _service(request).login(username=payload.username, password=payload.password)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail="invalid credentials") from error
    _set_session_cookies(response, created, request.app.state.settings)
    return SessionResponse(username=created.username, expires_at=created.expires_at)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    _service(request).logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response
