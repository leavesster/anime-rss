from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_REDIRECT_HEADERS = {"accept", "user-agent", "if-none-match", "if-modified-since"}


class HttpFetchError(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.transient = transient


@dataclass(frozen=True, slots=True)
class HttpResult:
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None


class SafeHttpClient:
    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
        max_response_bytes: int = 10 * 1024 * 1024,
        max_redirects: int = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
        self._max_response_bytes = max_response_bytes
        self._max_redirects = max_redirects

    def close(self) -> None:
        self._client.close()

    def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> HttpResult:
        current_url = self._validate_url(url)
        current_headers = dict(headers or {})
        current_headers.setdefault(
            "Accept", "application/atom+xml, application/rss+xml, application/xml, text/xml"
        )
        current_headers.setdefault("User-Agent", "anime-rss-service/0.1")
        if etag:
            current_headers["If-None-Match"] = etag
        if last_modified:
            current_headers["If-Modified-Since"] = last_modified

        for redirect_number in range(self._max_redirects + 1):
            try:
                with self._client.stream("GET", current_url, headers=current_headers) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        if redirect_number == self._max_redirects:
                            raise HttpFetchError("too_many_redirects", transient=False)
                        location = response.headers.get("location")
                        if not location:
                            raise HttpFetchError("redirect_without_location", transient=False)
                        next_url = self._validate_url(urljoin(current_url, location))
                        current_headers = self._headers_for_redirect(
                            current_url, next_url, current_headers
                        )
                        current_url = next_url
                        continue

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self._max_response_bytes:
                        raise HttpFetchError("response_too_large", transient=False)

                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_response_bytes:
                            raise HttpFetchError("response_too_large", transient=False)

                    return HttpResult(
                        status_code=response.status_code,
                        body=bytes(body),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                    )
            except httpx.TimeoutException as error:
                raise HttpFetchError("request_timeout", transient=True) from error
            except httpx.NetworkError as error:
                raise HttpFetchError("network_error", transient=True) from error
            except ValueError as error:
                raise HttpFetchError("invalid_content_length", transient=False) from error

        raise AssertionError("redirect loop did not terminate")

    @staticmethod
    def _validate_url(value: str) -> str:
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError as error:
            raise HttpFetchError("unsupported_url", transient=False) from error
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise HttpFetchError("unsupported_url", transient=False)
        if port is not None and not 1 <= port <= 65535:
            raise HttpFetchError("unsupported_url", transient=False)
        return value

    @staticmethod
    def _headers_for_redirect(
        current_url: str, next_url: str, headers: dict[str, str]
    ) -> dict[str, str]:
        current = urlsplit(current_url)
        following = urlsplit(next_url)
        if current.scheme == "https" and following.scheme == "http":
            raise HttpFetchError("https_downgrade_redirect", transient=False)
        if (current.scheme, current.hostname, current.port) == (
            following.scheme,
            following.hostname,
            following.port,
        ):
            return headers
        return {
            key: value for key, value in headers.items() if key.lower() in _SAFE_REDIRECT_HEADERS
        }
