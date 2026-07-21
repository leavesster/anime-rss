from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / name}",
        master_key_file=tmp_path / f"{name}.key",
        auth_enabled=False,
    )


def _rss(title: str, info_hash: str = "a" * 40) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        f"<guid>{info_hash}</guid><title>{title}</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()


def test_catalog_search_is_cached_and_bangumi_anime_can_be_imported(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def bangumi(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = {
            "id": 123,
            "name": "Mujikaku Seijo",
            "name_cn": "无自觉圣女今天也无意识地释放力量",
            "summary": "summary",
            "date": "2026-07-01",
            "eps": 12,
            "images": {"large": "https://lain.bgm.tv/pic.jpg"},
            "infobox": [{"key": "别名", "value": [{"v": "Mujikaku Seijo"}]}],
        }
        if request.method == "POST":
            return httpx.Response(200, json={"data": [item]})
        return httpx.Response(200, json=item)

    with TestClient(
        create_app(
            _settings(tmp_path, "catalog.sqlite3"),
            bangumi_transport=httpx.MockTransport(bangumi),
        )
    ) as client:
        first = client.get("/api/v1/catalog/bangumi/search", params={"query": "圣女"})
        second = client.get("/api/v1/catalog/bangumi/search", params={"query": "圣女"})
        imported = client.post("/api/v1/catalog/bangumi/123/import")

        assert first.status_code == 200
        assert second.json() == first.json()
        assert len([request for request in requests if request.method == "POST"]) == 1
        assert imported.status_code == 200
        assert imported.json()["bangumi_id"] == 123
        assert {title["normalized"] for title in imported.json()["titles"]} >= {
            "无自觉圣女今天也无意识地释放力量",
            "mujikakuseijo",
        }


def test_historical_candidates_require_backfill_preview_and_explicit_commit(
    tmp_path: Path,
) -> None:
    title = (
        "[Nix-Raws] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
        "S01E01 [CR WEB-DL 1080p AVC AAC][简繁内封]"
    )
    feed_transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss(title)))
    with TestClient(
        create_app(_settings(tmp_path, "backfill.sqlite3"), feed_transport=feed_transport)
    ) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "One", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        anime = client.post(
            "/api/v1/catalog/anime",
            json={"title": "无自觉圣女今天也无意识地释放力量"},
        ).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Nix-Raws"],
                    "preferred_codecs": ["AVC"],
                    "fallback_wait_minutes": 120,
                },
            },
        ).json()

        assert client.get("/api/v1/selection/episodes").json() == []
        preview = client.get(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-preview"
        ).json()
        assert preview[0]["episode_key"] == "1"
        assert preview[0]["selected_candidate_id"] is not None
        committed = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-commit",
            json={"episode_keys": ["1"]},
        )
        duplicate = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-commit",
            json={"episode_keys": ["1"]},
        )

        assert committed.json() == {"processed": 1}
        assert duplicate.json() == {"processed": 0}
        assert client.get("/api/v1/selection/episodes").json()[0]["state"] == "decided"
        decision = client.get("/api/v1/selection/decisions").json()[0]
        assert decision["kind"] == "selected_backfill"
        assert decision["candidate_snapshot"]["release_group"] == "Nix-Raws"


def test_fallback_deadline_survives_and_commits_when_due(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 21, 12, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=_rss("[Nix-Raws] Test Anime - 01 [1080p AVC][简体]", "b" * 40),
        )
    )
    settings = _settings(tmp_path, "waiting.sqlite3")
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Test Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Preferred", "Nix-Raws"],
                    "preferred_subtitles": ["zh-Hans+zh-Hant", "zh-Hans"],
                    "preferred_resolutions": ["1080p"],
                    "preferred_codecs": ["HEVC", "AVC"],
                    "fallback_wait_minutes": 60,
                },
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "One", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        slot = client.get("/api/v1/selection/episodes").json()[0]

        assert slot["state"] == "waiting_fallback"
        assert slot["fallback_deadline"] == "2026-07-21T13:00:00Z"
        paused = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"state": "paused"},
        ).json()
        assert paused["state"] == "paused"
        resumed = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(paused["version"])},
            json={"state": "following"},
        ).json()
        assert resumed["activation_at"] == "2026-07-21T12:00:00Z"

    current[0] += timedelta(minutes=61)
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as restarted:
        decision = restarted.get("/api/v1/selection/decisions").json()[0]
        assert decision["kind"] == "selected_fallback"


def test_resume_does_not_commit_a_candidate_from_the_previous_epoch(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 21, 12, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=_rss("[Nix-Raws] Epoch Anime - 01 [1080p AVC][简体]", "c" * 40),
        )
    )
    settings = _settings(tmp_path, "epochs.sqlite3")
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Epoch Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Preferred", "Nix-Raws"],
                    "fallback_wait_minutes": 60,
                },
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Epoch", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        current[0] += timedelta(minutes=10)
        paused = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"state": "paused"},
        ).json()
        current[0] += timedelta(minutes=10)
        client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(paused["version"])},
            json={"state": "following"},
        )
        current[0] += timedelta(minutes=50)

        assert client.post("/api/v1/selection/process-due").json() == {"processed": 0}
        assert client.get("/api/v1/selection/decisions").json() == []
        slot = client.get("/api/v1/selection/episodes").json()[0]
        assert slot["state"] == "open"
        assert slot["fallback_deadline"] is None
