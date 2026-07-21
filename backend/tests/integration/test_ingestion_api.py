import hashlib
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text

INFO_HASH = "0123456789abcdef0123456789abcdef01234567"


def _torrent() -> tuple[bytes, str]:
    info = b"d4:name4:Test12:piece lengthi16384e6:pieces20:" + (b"x" * 20) + b"e"
    payload = b"d8:announce14:https://t.test4:info" + info + b"e"
    return payload, hashlib.sha1(info, usedforsecurity=False).hexdigest()


def _rss(guid: str) -> bytes:
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title>
      <item><guid>{guid}</guid><title>[Group] Anime - 01</title>
      <enclosure url="magnet:?xt=urn:btih:{INFO_HASH}" type="application/x-bittorrent" />
      </item></channel></rss>""".encode()


def _app(tmp_path: Path, handler: httpx.MockTransport) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        master_key_file=tmp_path / "master.key",
    )
    app = create_app(settings, feed_transport=handler, jitter=lambda maximum: 0)
    return TestClient(app)


def test_same_release_from_two_feeds_is_stored_once(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        guid = "feed-one-entry" if request.url.host == "one.test" else "feed-two-entry"
        return httpx.Response(200, content=_rss(guid), headers={"ETag": f'"{guid}"'})

    with _app(tmp_path, httpx.MockTransport(handler)) as client:
        first = client.post(
            "/api/v1/feeds",
            json={"name": "One", "url": "https://one.test/rss?token=first-secret"},
        ).json()
        second = client.post(
            "/api/v1/feeds",
            json={"name": "Two", "url": "https://two.test/rss?token=second-secret"},
        ).json()

        assert "first-secret" not in first["url_redacted"]
        assert client.post(f"/api/v1/feeds/{first['id']}/refresh").status_code == 200
        assert client.post(f"/api/v1/feeds/{second['id']}/refresh").status_code == 200

        releases = client.get("/api/v1/releases").json()
        assert len(releases) == 1
        assert releases[0]["identity_value"] == INFO_HASH
        assert releases[0]["source_count"] == 2

        services: ServiceContainer = client.app.state.services
        with services.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM feed_entries")) == 2
            assert connection.scalar(text("SELECT count(*) FROM release_releases")) == 1
            assert connection.scalar(text("SELECT count(*) FROM release_sources")) == 2

    database_bytes = (tmp_path / "test.sqlite3").read_bytes()
    assert b"first-secret" not in database_bytes
    assert b"second-secret" not in database_bytes


def test_repeat_refresh_is_idempotent_and_uses_cache_validator(tmp_path: Path) -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=_rss("entry"), headers={"ETag": '"v1"'})

    with _app(tmp_path, httpx.MockTransport(handler)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "One", "url": "https://one.test/rss"}
        ).json()
        first = client.post(f"/api/v1/feeds/{feed['id']}/refresh").json()
        second = client.post(f"/api/v1/feeds/{feed['id']}/refresh").json()

        assert first["new_entry_count"] == 1
        assert second["status"] == "not_modified"
        assert second["new_entry_count"] == 0
        assert seen_headers[1]["if-none-match"] == '"v1"'


def test_authentication_failure_disables_automatic_retry(tmp_path: Path) -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(401))

    with _app(tmp_path, handler) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Private", "url": "https://feed.test/rss"}
        ).json()
        result = client.post(f"/api/v1/feeds/{feed['id']}/refresh").json()
        stored = client.get("/api/v1/feeds").json()[0]

        assert result["status"] == "auth_failed"
        assert stored["health"] == "auth_failed"
        assert stored["next_fetch_at"] is None


def test_torrent_payload_is_fetched_hashed_and_encrypted(tmp_path: Path) -> None:
    torrent_payload, expected_hash = _torrent()
    torrent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/episode.torrent":
            torrent_requests.append(request)
            return httpx.Response(200, content=torrent_payload)
        body = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Test</title><item>
        <guid>torrent-entry</guid><title>[Group] Anime - 01</title>
        <enclosure url="https://feed.test/episode.torrent"
          type="application/x-bittorrent" />
        </item></channel></rss>"""
        return httpx.Response(200, content=body)

    with _app(tmp_path, httpx.MockTransport(handler)) as client:
        feed = client.post(
            "/api/v1/feeds",
            json={
                "name": "Private",
                "url": "https://feed.test/rss",
                "headers": {"X-Api-Key": "torrent-secret"},
            },
        ).json()
        response = client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        releases = client.get("/api/v1/releases").json()

        assert response.status_code == 200
        assert releases[0]["identity_value"] == expected_hash
        assert torrent_requests[0].headers["x-api-key"] == "torrent-secret"

    database_bytes = (tmp_path / "test.sqlite3").read_bytes()
    assert torrent_payload not in database_bytes
    assert b"torrent-secret" not in database_bytes


def test_feed_test_update_history_and_delete_flow(tmp_path: Path) -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss("crud-entry")))

    with _app(tmp_path, handler) as client:
        test_result = client.post(
            "/api/v1/feeds/test", json={"url": "https://feed.test/private/path"}
        )
        assert test_result.status_code == 200
        assert test_result.json()["preview_titles"] == ["[Group] Anime - 01"]

        created = client.post(
            "/api/v1/feeds", json={"name": "Before", "url": "https://feed.test/rss"}
        ).json()
        updated = client.patch(
            f"/api/v1/feeds/{created['id']}",
            headers={"If-Match": str(created["version"])},
            json={"name": "After", "interval_seconds": 900},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "After"
        assert updated.json()["version"] == 2

        conflict = client.patch(
            f"/api/v1/feeds/{created['id']}",
            headers={"If-Match": "1"},
            json={"name": "Stale"},
        )
        assert conflict.status_code == 409

        assert client.post(f"/api/v1/feeds/{created['id']}/refresh").status_code == 200
        history = client.get(f"/api/v1/feeds/{created['id']}/fetches").json()
        assert history[0]["status"] == "success"
        assert history[0]["new_entry_count"] == 1

        deleted = client.delete(f"/api/v1/feeds/{created['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/feeds/{created['id']}/entries").status_code == 404
