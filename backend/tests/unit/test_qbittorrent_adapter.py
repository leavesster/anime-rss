import httpx
import pytest
from anime_rss.modules.downloads.adapters import QbittorrentClient
from anime_rss.modules.downloads.domain import (
    DownloaderConnection,
    DownloaderError,
    Submission,
)

HASH = "0123456789abcdef0123456789abcdef01234567"
CONNECTION = DownloaderConnection("http://qb.test", "admin", "secret")


def test_torrent_upload_lookup_and_completed_cancel() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=x; Path=/"})
        if request.url.path == "/api/v2/torrents/add":
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert b'filename="0123456789abcdef0123456789abcdef01234567.torrent"' in request.content
            assert b"torrent-content" in request.content
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    {
                        "hash": HASH.upper(),
                        "state": "pausedUP",
                        "progress": 1,
                        "save_path": "/complete",
                        "category": "anime",
                        "tags": "rss, done",
                    }
                ],
            )
        raise AssertionError("completed torrent must not be deleted")

    client = QbittorrentClient(transport=httpx.MockTransport(handler))
    client.submit(
        CONNECTION,
        Submission(HASH, "torrent", b"torrent-content", "/complete", "anime", ("rss",)),
    )
    task = client.lookup(CONNECTION, HASH)
    canceled = client.cancel_incomplete(CONNECTION, HASH)

    assert task is not None
    assert task.info_hash == HASH
    assert task.tags == ("rss", "done")
    assert canceled == task
    assert not any(request.url.path == "/api/v2/torrents/delete" for request in requests)


def test_authentication_and_transient_response_errors_are_classified() -> None:
    auth_client = QbittorrentClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, text="Fails."))
    )
    with pytest.raises(DownloaderError, match="authentication_failed") as auth_error:
        auth_client.test(CONNECTION)
    assert auth_error.value.transient is False

    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(503)

    unavailable_client = QbittorrentClient(transport=httpx.MockTransport(unavailable))
    with pytest.raises(DownloaderError, match="upstream_unavailable") as upstream_error:
        unavailable_client.lookup(CONNECTION, HASH)
    assert upstream_error.value.transient is True


def test_reverse_proxy_base_path_is_preserved() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/qb/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/qb/api/v2/app/version":
            return httpx.Response(200, text="v5.0.4")
        if request.url.path == "/qb/api/v2/app/webapiVersion":
            return httpx.Response(200, text="2.11.2")
        raise AssertionError(request.url.path)

    client = QbittorrentClient(transport=httpx.MockTransport(handler))
    compatibility = client.test(DownloaderConnection("http://qb.test/qb", "admin", "secret"))
    assert compatibility.application_version == "v5.0.4"
    assert compatibility.web_api_version == "2.11.2"
    assert paths == [
        "/qb/api/v2/auth/login",
        "/qb/api/v2/app/version",
        "/qb/api/v2/app/webapiVersion",
    ]


@pytest.mark.parametrize(
    ("application_version", "web_api_version"),
    [("v4.6.7", "2.9.3"), ("v5.0.4", "2.11.2")],
)
def test_supported_qbittorrent_versions_are_explicit(
    application_version: str, web_api_version: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/app/version":
            return httpx.Response(200, text=application_version)
        if request.url.path == "/api/v2/app/webapiVersion":
            return httpx.Response(200, text=web_api_version)
        raise AssertionError(request.url.path)

    compatibility = QbittorrentClient(transport=httpx.MockTransport(handler)).test(CONNECTION)
    assert compatibility.application_version == application_version
    assert compatibility.web_api_version == web_api_version


@pytest.mark.parametrize(
    ("application_version", "web_api_version"),
    [("v4.5.5", "2.8.3"), ("v6.0.0", "3.0.0"), ("not-a-version", "2.11.4")],
)
def test_unsupported_or_malformed_qbittorrent_versions_are_rejected(
    application_version: str, web_api_version: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/app/version":
            return httpx.Response(200, text=application_version)
        if request.url.path == "/api/v2/app/webapiVersion":
            return httpx.Response(200, text=web_api_version)
        raise AssertionError(request.url.path)

    client = QbittorrentClient(transport=httpx.MockTransport(handler))
    expected = (
        "invalid_version_response"
        if application_version == "not-a-version"
        else "unsupported_qbittorrent_version"
    )
    with pytest.raises(DownloaderError, match=expected):
        client.test(CONNECTION)
