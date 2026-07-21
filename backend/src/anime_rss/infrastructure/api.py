import base64
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import JSON, CheckConstraint, LargeBinary, String, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.time import Clock, utc_now

MAX_PAGE_SIZE = 200
MAX_CURSOR_OFFSET = 10_000
IDEMPOTENCY_TTL = timedelta(hours=24)
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
PageCursor = Annotated[str | None, Query(max_length=100)]


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    details: Any | None = None
    correlation_id: str
    detail: str


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if len(cursor) > 100:
        raise HTTPException(status_code=422, detail="invalid pagination cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        offset = payload["offset"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="invalid pagination cursor") from error
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= MAX_CURSOR_OFFSET
    ):
        raise HTTPException(status_code=422, detail="invalid pagination cursor")
    return offset


def requested_item_count(cursor: str | None, limit: int) -> int:
    offset = cursor_offset(cursor)
    return offset + min(max(limit, 1), MAX_PAGE_SIZE) + 1


def page[T](items: Sequence[T], *, cursor: str | None, limit: int) -> CursorPage[T]:
    offset = cursor_offset(cursor)
    page_size = min(max(limit, 1), MAX_PAGE_SIZE)
    selected = list(items[offset : offset + page_size])
    has_more = len(items) > offset + page_size
    return CursorPage(
        items=selected,
        next_cursor=_encode_cursor(offset + page_size) if has_more else None,
    )


def page_response[T](
    items: Sequence[T],
    response: Response,
    *,
    cursor: str | None,
    limit: int,
) -> list[T]:
    result = page(items, cursor=cursor, limit=limit)
    response.headers["X-Page-Limit"] = str(min(max(limit, 1), MAX_PAGE_SIZE))
    if result.next_cursor is not None:
        response.headers["X-Next-Cursor"] = result.next_cursor
    return result.items


def correlation_id_for(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "unknown"))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        code=code,
        message=message,
        details=jsonable_encoder(details),
        correlation_id=correlation_id_for(request),
        detail=message,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(), headers=headers)


def enrich_openapi_contract(schema: dict[str, Any]) -> None:
    excluded_idempotency_paths = {
        "/api/v1/auth/setup",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/system/backups/restore/stage",
    }
    paths_value = schema.get("paths")
    if not isinstance(paths_value, dict):
        return
    paths = cast(dict[str, object], paths_value)
    for path, path_item_value in paths.items():
        if not isinstance(path_item_value, dict):
            continue
        path_item = cast(dict[str, object], path_item_value)
        for method, operation_value in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"} or not isinstance(
                operation_value, dict
            ):
                continue
            operation = cast(dict[str, object], operation_value)
            parameters_value = operation.setdefault("parameters", [])
            parameters: list[object] = []
            if isinstance(parameters_value, list):
                parameters = cast(list[object], parameters_value)
                for parameter_value in parameters:
                    parameter = (
                        cast(dict[str, object], parameter_value)
                        if isinstance(parameter_value, dict)
                        else None
                    )
                    if (
                        parameter is not None
                        and str(parameter.get("name", "")).lower() == "if-match"
                    ):
                        parameter["name"] = "If-Match"
                        parameter["required"] = True
                if (
                    method in {"post", "put", "patch", "delete"}
                    and path not in (excluded_idempotency_paths)
                    and not any(
                        isinstance(parameter_value, dict)
                        and str(cast(dict[str, object], parameter_value).get("name", "")).lower()
                        == "idempotency-key"
                        for parameter_value in parameters
                    )
                ):
                    parameters.append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": False,
                            "description": "Replays a successful mutation for 24 hours.",
                            "schema": {
                                "type": "string",
                                "minLength": 8,
                                "maxLength": 200,
                                "pattern": _KEY_PATTERN.pattern,
                            },
                        }
                    )
            if method == "get" and any(
                isinstance(parameter_value, dict)
                and cast(dict[str, object], parameter_value).get("name") == "cursor"
                for parameter_value in parameters
            ):
                responses_value = operation.get("responses")
                responses = (
                    cast(dict[str, object], responses_value)
                    if isinstance(responses_value, dict)
                    else {}
                )
                success_value = responses.get("200")
                if isinstance(success_value, dict):
                    success = cast(dict[str, object], success_value)
                    headers_value = success.setdefault("headers", {})
                    if not isinstance(headers_value, dict):
                        continue
                    headers = cast(dict[str, object], headers_value)
                    headers["X-Next-Cursor"] = {
                        "description": "Opaque cursor for the next page; absent on the last page.",
                        "schema": {"type": "string"},
                    }
                    headers["X-Page-Limit"] = {
                        "description": "Effective page size.",
                        "schema": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE},
                    }


class HttpIdempotencyRecord(Base):
    __tablename__ = "http_idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "state IN ('processing','completed')",
            name="ck_http_idempotency_state",
        ),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary(), nullable=True)
    response_headers: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    status_code: int
    body: bytes
    headers: dict[str, str]


class IdempotencyConflictError(RuntimeError):
    pass


class IdempotencyInProgressError(RuntimeError):
    pass


class HttpIdempotencyStore:
    def __init__(self, engine: Any, *, clock: Clock = utc_now) -> None:
        self._engine = engine
        self._clock = clock

    @staticmethod
    def validate_key(value: str) -> str:
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError("Idempotency-Key must be 8-200 URL-safe characters")
        return value

    @staticmethod
    def key_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def request_hash(request: Request, body: bytes) -> str:
        query = request.url.query.encode()
        payload = b"\n".join((request.method.encode(), request.url.path.encode(), query, body))
        return hashlib.sha256(payload).hexdigest()

    def claim(self, key: str, request_hash: str) -> IdempotencyReplay | None:
        now = self._clock()
        key_hash = self.key_hash(self.validate_key(key))
        try:
            with Session(self._engine) as session, session.begin():
                session.execute(
                    delete(HttpIdempotencyRecord).where(HttpIdempotencyRecord.expires_at <= now)
                )
                record = session.get(HttpIdempotencyRecord, key_hash)
                if record is None:
                    session.add(
                        HttpIdempotencyRecord(
                            key_hash=key_hash,
                            request_hash=request_hash,
                            state="processing",
                            expires_at=now + IDEMPOTENCY_TTL,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    return None
                return self._resolve(record, request_hash)
        except IntegrityError:
            with Session(self._engine) as session:
                record = session.scalar(
                    select(HttpIdempotencyRecord).where(HttpIdempotencyRecord.key_hash == key_hash)
                )
                if record is None:
                    raise
                return self._resolve(record, request_hash)

    @staticmethod
    def _resolve(record: HttpIdempotencyRecord, request_hash: str) -> IdempotencyReplay | None:
        if record.request_hash != request_hash:
            raise IdempotencyConflictError("Idempotency-Key was used for another request")
        if record.state == "processing":
            raise IdempotencyInProgressError("request with this Idempotency-Key is in progress")
        if record.status_code is None or record.response_body is None:
            raise RuntimeError("completed idempotency record is incomplete")
        return IdempotencyReplay(
            status_code=record.status_code,
            body=record.response_body,
            headers=record.response_headers or {},
        )

    def complete(
        self,
        key: str,
        request_hash: str,
        *,
        status_code: int,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        now = self._clock()
        with Session(self._engine) as session, session.begin():
            record = session.get(HttpIdempotencyRecord, self.key_hash(key))
            if record is None or record.request_hash != request_hash:
                raise RuntimeError("idempotency claim disappeared before completion")
            record.state = "completed"
            record.status_code = status_code
            record.response_body = body
            record.response_headers = headers
            record.updated_at = now

    def abandon(self, key: str, request_hash: str) -> None:
        with Session(self._engine) as session, session.begin():
            record = session.get(HttpIdempotencyRecord, self.key_hash(key))
            if record is not None and record.request_hash == request_hash:
                session.delete(record)
