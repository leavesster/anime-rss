from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text

INFO_HASH = "0123456789abcdef0123456789abcdef01234567"
V2_HASH = "89abcdef0123456789abcdef0123456789abcdef"


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / name}",
        master_key_file=tmp_path / f"{name}.key",
        download_poll_seconds=300,
        auth_enabled=False,
    )


def _rss(info_hash: str, *, revision: int = 1) -> bytes:
    suffix = f"V{revision}" if revision > 1 else ""
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title><item>
      <guid>{info_hash}</guid>
      <title>[Nix-Raws] Download Anime - 01{suffix} [1080p HEVC][简体]</title>
      <enclosure url="magnet:?xt=urn:btih:{info_hash}" type="application/x-bittorrent" />
    </item></channel></rss>""".encode()


class FakeQbittorrent:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, object]] = {}
        self.add_hashes: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.submitted_options: list[dict[str, list[str]]] = []
        self.fail_lookup_once = False
        self.timeout_after_add_once = False
        self.next_add_hash = INFO_HASH

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v2/auth/login":
            assert b"username=admin" in request.content
            assert b"password=download-secret" in request.content
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=test; Path=/"})
        assert request.headers.get("cookie") == "SID=test"
        if path == "/api/v2/app/version":
            return httpx.Response(200, text="v5.0.4")
        if path == "/api/v2/torrents/info":
            if self.fail_lookup_once:
                self.fail_lookup_once = False
                return httpx.Response(503)
            info_hash = request.url.params["hashes"]
            task = self.tasks.get(info_hash)
            return httpx.Response(200, json=[task] if task else [])
        if path == "/api/v2/torrents/add":
            body = parse_qs(request.content.decode())
            assert body["savepath"] == ["/downloads/anime"]
            self.submitted_options.append(body)
            info_hash = self.next_add_hash
            self.add_hashes.append(info_hash)
            self.tasks[info_hash] = {
                "hash": info_hash,
                "state": "downloading",
                "progress": 0.25,
                "save_path": "/downloads/anime",
                "category": "anime",
                "tags": "rss, seasonal",
            }
            if self.timeout_after_add_once:
                self.timeout_after_add_once = False
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(200, text="Ok.")
        if path == "/api/v2/torrents/delete":
            body = parse_qs(request.content.decode())
            info_hash = body["hashes"][0]
            self.deleted.append((info_hash, body["deleteFiles"][0]))
            self.tasks.pop(info_hash, None)
            return httpx.Response(200, text="Ok.")
        raise AssertionError(f"unexpected qBittorrent request: {request.method} {path}")


def _configure(client: TestClient) -> dict[str, object]:
    response = client.put(
        "/api/v1/downloads/config",
        headers={"If-Match": "0"},
        json={
            "base_url": "http://qb.test:8080",
            "username": "admin",
            "password": "download-secret",
            "default_save_path": "/downloads/anime",
            "default_category": "anime",
            "default_tags": ["seasonal", "rss"],
        },
    )
    assert response.status_code == 200
    return response.json()


def _subscribe_and_refresh(client: TestClient, feed_transport: httpx.MockTransport) -> None:
    anime = client.post("/api/v1/catalog/anime", json={"title": "Download Anime"}).json()
    client.post(
        "/api/v1/subscriptions",
        json={
            "anime_id": anime["id"],
            "save_path": None,
            "rules": {
                "preferred_groups": ["Nix-Raws"],
                "preferred_subtitles": ["zh-Hans"],
                "preferred_resolutions": ["1080p"],
                "preferred_codecs": ["HEVC"],
                "fallback_wait_minutes": 60,
            },
        },
    )
    feed = client.post(
        "/api/v1/feeds", json={"name": "Downloads", "url": "https://feed.test/rss"}
    ).json()
    assert feed_transport is not None
    assert client.post(f"/api/v1/feeds/{feed['id']}/refresh").status_code == 200


def test_config_submit_reconcile_external_delete_and_explicit_retry(tmp_path: Path) -> None:
    qb = FakeQbittorrent()
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=_rss(INFO_HASH))
    )
    app = create_app(
        _settings(tmp_path, "downloads.sqlite3"),
        feed_transport=feed_transport,
        qbittorrent_transport=httpx.MockTransport(qb.handler),
    )
    with TestClient(app) as client:
        config = _configure(client)
        assert config["base_url_redacted"] == "http://qb.test:8080"
        assert config["default_save_path"] == "/downloads/anime"
        assert config["password_configured"] is True
        assert client.post("/api/v1/downloads/config/test").json() == {
            "status": "connected",
            "version": "v5.0.4",
        }
        _subscribe_and_refresh(client, feed_transport)

        planned = client.get("/api/v1/downloads/tasks").json()[0]
        assert planned["state"] == "planned"
        assert planned["origin_kind"] == "selection_decision"
        assert planned["decision_id"] is not None
        assert planned["subscription_id"] is not None
        assert planned["requested_save_path"] == "/downloads/anime"
        reused = client.post(f"/api/v1/downloads/releases/{planned['release_id']}/submit")
        assert reused.status_code == 201
        assert reused.json()["id"] == planned["id"]
        assert reused.json()["origin_kind"] == "selection_decision"
        first = client.post("/api/v1/downloads/process").json()
        assert first["submissions"] == 1
        task = client.get("/api/v1/downloads/tasks").json()[0]
        assert task["state"] == "downloading"
        assert task["progress"] == 0.25
        assert qb.add_hashes == [INFO_HASH]
        assert qb.submitted_options[0]["category"] == ["anime"]
        assert qb.submitted_options[0]["tags"] == ["rss,seasonal"]

        qb.tasks[INFO_HASH].update(
            state="pausedDL",
            save_path="/downloads/manual",
            category="changed",
            tags="external",
        )
        client.post("/api/v1/downloads/process")
        changed = client.get("/api/v1/downloads/tasks").json()[0]
        assert changed["state"] == "paused"
        assert changed["actual_save_path"] == "/downloads/manual"
        assert changed["tags"] == ["external"]

        qb.tasks.pop(INFO_HASH)
        client.post("/api/v1/downloads/process")
        removed = client.get("/api/v1/downloads/tasks").json()[0]
        assert removed["state"] == "externally_removed"
        client.post("/api/v1/downloads/process")
        assert qb.add_hashes == [INFO_HASH]

        assert client.post(f"/api/v1/downloads/tasks/{removed['id']}/retry").status_code == 200
        client.post("/api/v1/downloads/process")
        assert qb.add_hashes == [INFO_HASH, INFO_HASH]

    database_bytes = (tmp_path / "downloads.sqlite3").read_bytes()
    assert b"download-secret" not in database_bytes


def test_manual_release_submission_is_durable_idempotent_and_btih_only(tmp_path: Path) -> None:
    pure_v2 = "1220" + "a" * 64
    rss = f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Manual</title>
      <item><guid>manual-btih</guid><title>Unknown weekly package</title>
        <enclosure url="magnet:?xt=urn:btih:{INFO_HASH}" type="application/x-bittorrent" />
      </item>
      <item><guid>manual-btmh</guid><title>Unknown v2 package</title>
        <enclosure url="magnet:?xt=urn:btmh:{pure_v2}" type="application/x-bittorrent" />
      </item>
    </channel></rss>""".encode()
    qb = FakeQbittorrent()
    app = create_app(
        _settings(tmp_path, "manual-download.sqlite3"),
        feed_transport=httpx.MockTransport(lambda request: httpx.Response(200, content=rss)),
        qbittorrent_transport=httpx.MockTransport(qb.handler),
    )

    with TestClient(app) as client:
        _configure(client)
        feed = client.post(
            "/api/v1/feeds", json={"name": "Manual", "url": "https://feed.test/rss"}
        ).json()
        assert client.post(f"/api/v1/feeds/{feed['id']}/refresh").status_code == 200
        releases = client.get("/api/v1/releases").json()
        btih_release = next(item for item in releases if item["btih"] == INFO_HASH)
        btmh_release = next(item for item in releases if item["btmh"] == pure_v2)

        first = client.post(f"/api/v1/downloads/releases/{btih_release['id']}/submit")
        second = client.post(f"/api/v1/downloads/releases/{btih_release['id']}/submit")

        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["origin_kind"] == "manual_release"
        assert first.json()["decision_id"] is None
        assert first.json()["subscription_id"] is None
        assert first.json()["state"] == "planned"
        assert client.get("/api/v1/selection/decisions").json() == []
        assert qb.add_hashes == []
        manual_audits = [
            item
            for item in client.get("/api/v1/audit/events").json()
            if item["event_type"] == "download.manual_planned"
        ]
        assert len(manual_audits) == 1
        assert manual_audits[0]["payload"]["release_id"] == btih_release["id"]

        processed = client.post("/api/v1/downloads/process").json()
        assert processed["submissions"] == 1
        assert qb.add_hashes == [INFO_HASH]
        assert client.get("/api/v1/downloads/tasks").json()[0]["state"] == "downloading"

        assert (
            client.post(f"/api/v1/downloads/releases/{btmh_release['id']}/submit").status_code
            == 409
        )
        assert client.post("/api/v1/downloads/releases/missing/submit").status_code == 404


def test_timeout_after_success_recovers_by_hash_without_duplicate_add(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 21, 12, 0, tzinfo=UTC)]
    qb = FakeQbittorrent()
    qb.timeout_after_add_once = True
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=_rss(INFO_HASH))
    )
    app = create_app(
        _settings(tmp_path, "retry.sqlite3"),
        feed_transport=feed_transport,
        qbittorrent_transport=httpx.MockTransport(qb.handler),
        clock=lambda: now[0],
    )
    with TestClient(app) as client:
        _configure(client)
        _subscribe_and_refresh(client, feed_transport)
        first = client.post("/api/v1/downloads/process").json()
        assert first["submissions"] == 1
        assert client.get("/api/v1/downloads/tasks").json()[0]["state"] == "retrying"

        now[0] += timedelta(seconds=31)
        second = client.post("/api/v1/downloads/process").json()
        assert second["submissions"] == 1
        assert client.get("/api/v1/downloads/tasks").json()[0]["state"] == "downloading"
        assert qb.add_hashes == [INFO_HASH]


def test_upgrade_cancels_incomplete_task_without_deleting_files(tmp_path: Path) -> None:
    current_release = [INFO_HASH]
    current_revision = [1]
    qb = FakeQbittorrent()

    def feed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_rss(current_release[0], revision=current_revision[0]),
        )

    feed_transport = httpx.MockTransport(feed_handler)
    app = create_app(
        _settings(tmp_path, "replacement.sqlite3"),
        feed_transport=feed_transport,
        qbittorrent_transport=httpx.MockTransport(qb.handler),
    )
    with TestClient(app) as client:
        _configure(client)
        _subscribe_and_refresh(client, feed_transport)
        client.post("/api/v1/downloads/process")

        current_release[0] = V2_HASH
        current_revision[0] = 2
        qb.next_add_hash = V2_HASH
        feed_id = client.get("/api/v1/feeds").json()[0]["id"]
        assert client.post(f"/api/v1/feeds/{feed_id}/refresh").status_code == 200
        result = client.post("/api/v1/downloads/process").json()
        tasks = client.get("/api/v1/downloads/tasks").json()

        assert result["cancellations"] == 1
        assert result["submissions"] == 1
        assert qb.deleted == [(INFO_HASH, "false")]
        assert {task["state"] for task in tasks} == {"superseded", "downloading"}
        assert qb.add_hashes == [INFO_HASH, V2_HASH]


def test_download_config_validation_and_api_errors(tmp_path: Path) -> None:
    qb = FakeQbittorrent()
    with TestClient(
        create_app(
            _settings(tmp_path, "errors.sqlite3"),
            qbittorrent_transport=httpx.MockTransport(qb.handler),
        )
    ) as client:
        assert client.get("/api/v1/downloads/config").json() is None
        assert client.post("/api/v1/downloads/config/test").status_code == 409
        assert (
            client.put(
                "/api/v1/downloads/config",
                headers={"If-Match": "0"},
                json={"base_url": "ftp://qb.test", "username": "admin", "password": "secret"},
            ).status_code
            == 422
        )
        config = _configure(client)
        conflict = client.put(
            "/api/v1/downloads/config",
            headers={"If-Match": str(int(config["version"]) + 1)},
            json={"base_url": "http://qb.test", "username": "admin"},
        )
        assert conflict.status_code == 409
        assert client.post("/api/v1/downloads/tasks/missing/retry").status_code == 404

        services: ServiceContainer = client.app.state.services
        assert services.downloads.list_tasks() == []


def test_restart_recovers_an_interrupted_submission(tmp_path: Path) -> None:
    qb = FakeQbittorrent()
    settings = _settings(tmp_path, "restart.sqlite3")
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=_rss(INFO_HASH))
    )
    qb_transport = httpx.MockTransport(qb.handler)
    with TestClient(
        create_app(
            settings,
            feed_transport=feed_transport,
            qbittorrent_transport=qb_transport,
        )
    ) as client:
        _configure(client)
        _subscribe_and_refresh(client, feed_transport)
        services: ServiceContainer = client.app.state.services
        with services.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE download_tasks SET state='submitting', "
                    "operation_started_at='2026-07-21T00:00:00Z'"
                )
            )

    with TestClient(
        create_app(
            settings,
            feed_transport=feed_transport,
            qbittorrent_transport=qb_transport,
        )
    ) as restarted:
        task = restarted.get("/api/v1/downloads/tasks").json()[0]
        assert task["state"] == "downloading"
        assert task["error_code"] is None
        assert qb.add_hashes == [INFO_HASH]
