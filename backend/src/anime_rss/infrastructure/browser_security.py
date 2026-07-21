import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class BrowserSecurityError(ValueError):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _hostname(authority: str) -> str:
    if not authority or any(character.isspace() or ord(character) < 32 for character in authority):
        raise ValueError("invalid host header")
    parsed = urlsplit(f"//{authority}")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid host header")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("invalid host header") from error
    return parsed.hostname.rstrip(".").lower()


def _canonical_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trusted origins must be absolute HTTP origins")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("trusted origin has an invalid port") from error
    hostname = parsed.hostname.rstrip(".").lower()
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if parsed.scheme == "http" else 443
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{rendered_host}{port_suffix}"


def _matches_host(hostname: str, allowed: str) -> bool:
    normalized = allowed.rstrip(".").lower()
    if normalized.startswith("*."):
        suffix = normalized[1:]
        return hostname.endswith(suffix) and hostname != suffix[1:]
    return hostname == normalized


class BrowserOriginPolicy:
    def __init__(self, *, trusted_hosts: Sequence[str], trusted_origins: Sequence[str]) -> None:
        self._trusted_hosts = tuple(value for value in trusted_hosts if value)
        self._trusted_origins = frozenset(_canonical_origin(value) for value in trusted_origins)
        self._origin_hosts = frozenset(urlsplit(value).hostname for value in self._trusted_origins)

    def validate(self, request: Request) -> None:
        authority = request.headers.get("host", "")
        try:
            hostname = _hostname(authority)
        except ValueError as error:
            raise BrowserSecurityError(
                status_code=400,
                code="invalid_host",
                message="request Host header is invalid",
            ) from error
        if not self._host_allowed(hostname):
            raise BrowserSecurityError(
                status_code=400,
                code="untrusted_host",
                message="request Host is not trusted",
            )
        if request.method in SAFE_METHODS:
            return
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            raise BrowserSecurityError(
                status_code=403,
                code="cross_site_request_rejected",
                message="cross-site browser request rejected",
            )
        origin = request.headers.get("origin")
        if origin is None:
            return
        try:
            normalized_origin = _canonical_origin(origin)
        except ValueError as error:
            raise BrowserSecurityError(
                status_code=403,
                code="origin_mismatch",
                message="request Origin is not trusted",
            ) from error
        allowed_origins = self._trusted_origins or frozenset(
            {_canonical_origin(f"{request.url.scheme}://{authority}")}
        )
        if normalized_origin not in allowed_origins:
            raise BrowserSecurityError(
                status_code=403,
                code="origin_mismatch",
                message="request Origin is not trusted",
            )

    def _host_allowed(self, hostname: str) -> bool:
        try:
            ip_address(hostname)
        except ValueError:
            pass
        else:
            return True
        return hostname in self._origin_hosts or any(
            _matches_host(hostname, allowed) for allowed in self._trusted_hosts
        )


@dataclass(frozen=True, slots=True)
class RateLimit:
    attempts: int
    window_seconds: int


class RequestRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = 10_000,
    ) -> None:
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, key: str, policy: RateLimit) -> int | None:
        now = self._clock()
        cutoff = now - policy.window_seconds
        with self._lock:
            attempts = self._buckets.setdefault(key, deque())
            self._buckets.move_to_end(key)
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= policy.attempts:
                return max(1, math.ceil(attempts[0] + policy.window_seconds - now))
            attempts.append(now)
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
        return None
