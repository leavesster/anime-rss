import httpx
import pytest
from anime_rss.infrastructure.http import HttpFetchError, SafeHttpClient


def test_cross_origin_redirect_strips_custom_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "private.test":
            return httpx.Response(302, headers={"Location": "https://cdn.test/feed.xml"})
        return httpx.Response(200, content=b"feed")

    client = SafeHttpClient(transport=httpx.MockTransport(handler))
    try:
        client.fetch(
            "https://private.test/rss",
            headers={"Authorization": "Bearer secret", "X-Api-Key": "private"},
        )
    finally:
        client.close()

    assert requests[0].headers["authorization"] == "Bearer secret"
    assert "authorization" not in requests[1].headers
    assert "x-api-key" not in requests[1].headers


def test_https_downgrade_redirect_is_rejected() -> None:
    handler = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "http://feed.test/rss"})
    )
    client = SafeHttpClient(transport=handler)
    try:
        with pytest.raises(HttpFetchError, match="https_downgrade_redirect"):
            client.fetch("https://feed.test/rss")
    finally:
        client.close()


def test_oversized_response_stops_at_the_configured_limit() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 101))
    client = SafeHttpClient(max_response_bytes=100, transport=handler)
    try:
        with pytest.raises(HttpFetchError, match="response_too_large"):
            client.fetch("https://feed.test/rss")
    finally:
        client.close()
