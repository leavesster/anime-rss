import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import overload
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MIN_REFRESH_SECONDS = 5 * 60
MAX_REFRESH_SECONDS = 60 * 60
MAX_TITLE_CHARS = 4096


class FeedHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    TRANSIENT_FAILURE = "transient_failure"
    DEGRADED = "degraded"
    AUTH_FAILED = "auth_failed"


class FeedSourceType(StrEnum):
    AGGREGATE = "aggregate"
    SINGLE_ANIME = "single_anime"


class FeedIdentityStrength(StrEnum):
    STRONG = "strong"
    WEAK = "weak"


@dataclass(frozen=True, slots=True)
class NormalizedFeedEntry:
    source_guid: str | None
    guid_hash: str
    identity_strength: FeedIdentityStrength
    title_raw: str
    title_normalized: str
    published_at: datetime | None
    link: str | None
    torrent_reference: str | None


@dataclass(frozen=True, slots=True)
class RetryPlan:
    health: FeedHealth
    next_fetch_at: datetime | None
    consecutive_failures: int


def validate_refresh_interval(seconds: int) -> None:
    if not MIN_REFRESH_SECONDS <= seconds <= MAX_REFRESH_SECONDS:
        raise ValueError(
            f"refresh interval must be between {MIN_REFRESH_SECONDS} and "
            f"{MAX_REFRESH_SECONDS} seconds"
        )


def normalize_title(value: str) -> str:
    without_controls = "".join(
        character
        for character in value
        if character in "\t\n\r" or not unicodedata.category(character).startswith("C")
    )
    normalized = unicodedata.normalize("NFKC", without_controls).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized[:MAX_TITLE_CHARS]


def build_entry_identity(
    *, source_guid: str | None, link: str | None, title: str, published_at: datetime | None
) -> tuple[str, FeedIdentityStrength]:
    if source_guid and source_guid.strip():
        identity = source_guid.strip()
        strength = FeedIdentityStrength.STRONG
    else:
        published = published_at.isoformat() if published_at else ""
        identity = "\x1f".join((link or "", title, published))
        strength = FeedIdentityStrength.WEAK
    return hashlib.sha256(identity.encode("utf-8")).hexdigest(), strength


@overload
def redact_url(value: str) -> str: ...


@overload
def redact_url(value: None) -> None: ...


def redact_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parts.port}" if parts.port is not None else ""
    username = "***@" if parts.username is not None else ""
    netloc = f"{username}{hostname}{port}"
    redacted_path = "/***" if parts.path not in {"", "/"} else parts.path
    redacted_query = urlencode(
        [(key, "***") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    )
    return urlunsplit((parts.scheme, netloc, redacted_path, redacted_query, ""))


def public_entry_url(value: str | None) -> str | None:
    """Return a navigable RSS item URL without credentials, query data, or fragments."""
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    hostname = parts.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit((parts.scheme, f"{hostname}{port}", parts.path or "/", "", ""))


def plan_transient_retry(
    *, now: datetime, previous_failures: int, jitter_seconds: int
) -> RetryPlan:
    failures = previous_failures + 1
    base_seconds = min(60 * (2 ** (failures - 1)), MAX_REFRESH_SECONDS)
    bounded_jitter = max(0, min(jitter_seconds, max(1, base_seconds // 5)))
    return RetryPlan(
        health=FeedHealth.TRANSIENT_FAILURE if failures < 3 else FeedHealth.DEGRADED,
        next_fetch_at=now + timedelta(seconds=base_seconds + bounded_jitter),
        consecutive_failures=failures,
    )
