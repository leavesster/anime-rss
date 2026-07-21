import json
import logging
import re
import sys
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_causation_id: ContextVar[str | None] = ContextVar("causation_id", default=None)
_context_fields: ContextVar[dict[str, Any] | None] = ContextVar("log_context_fields", default=None)
_managed_handlers: list[logging.Handler] = []
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "headers",
    "password",
    "secret",
    "token",
    "url",
}
_URL_PATTERN = re.compile(r"https?://[^\s\"']+")


def new_correlation_id() -> str:
    return str(uuid4())


def normalize_correlation_id(value: str | None) -> str:
    if value is None:
        return new_correlation_id()
    try:
        return str(UUID(value))
    except ValueError:
        return new_correlation_id()


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def current_causation_id() -> str | None:
    return _causation_id.get()


@contextmanager
def observation_context(
    *,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    **fields: Any,
) -> Generator[str]:
    resolved_correlation_id = correlation_id or current_correlation_id() or new_correlation_id()
    correlation_token = _correlation_id.set(resolved_correlation_id)
    causation_token = _causation_id.set(causation_id)
    fields_token = _context_fields.set({**(_context_fields.get() or {}), **fields})
    try:
        yield resolved_correlation_id
    finally:
        _context_fields.reset(fields_token)
        _causation_id.reset(causation_token)
        _correlation_id.reset(correlation_token)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"structured_fields": fields})


def log_exception(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.exception(event, extra={"structured_fields": fields})


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": _redact_text(record.getMessage()),
            "logger": record.name,
        }
        correlation_id = current_correlation_id()
        causation_id = current_causation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if causation_id is not None:
            payload["causation_id"] = causation_id
        payload.update(
            _redact(
                {
                    **(_context_fields.get() or {}),
                    **cast(dict[str, Any], getattr(record, "structured_fields", {})),
                }
            )
        )
        if record.exc_info is not None:
            payload["exception"] = _redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)


class HealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            return record.args[2] not in {"/api/v1/health/live", "/api/v1/health/ready"}
        return True


def configure_logging(*, data_dir: Path, level: str = "INFO", retention_days: int = 14) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonLogFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(
        TimedRotatingFileHandler(
            log_dir / "application.jsonl",
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
            utc=True,
        )
    )
    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    _managed_handlers.clear()
    root.setLevel(level.upper())
    for handler in handlers:
        root.addHandler(handler)
        _managed_handlers.append(handler)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, HealthAccessFilter) for item in access_logger.filters):
        access_logger.addFilter(HealthAccessFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def shutdown_logging() -> None:
    root = logging.getLogger()
    for handler in _managed_handlers:
        root.removeHandler(handler)
        handler.close()
    _managed_handlers.clear()


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and any(fragment in key.lower() for fragment in _SENSITIVE_KEYS):
        if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            return _redact_url(value)
        return "<redacted>"
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(item_key): _redact(item, key=str(item_key)) for item_key, item in mapping.items()
        }
    if isinstance(value, (list, tuple)):
        values = cast(list[object] | tuple[object, ...], value)
        return [_redact(item) for item in values]
    return value


def _redact_url(value: str) -> str:
    parts = urlsplit(value)
    query = urlencode(
        [(key, "<redacted>") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _redact_text(value: str) -> str:
    return _URL_PATTERN.sub(lambda match: _redact_url(match.group(0)), value)
