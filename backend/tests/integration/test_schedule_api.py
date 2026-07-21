from datetime import UTC, datetime
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'schedule.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )


def _rss(title: str) -> bytes:
    info_hash = "f" * 40
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        f"<guid>{info_hash}</guid><title>{title}</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()


def test_schedule_marks_missing_once_without_creating_download_work(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 20, 0, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    with TestClient(create_app(_settings(tmp_path), clock=clock)) as client:
        settings = client.get("/api/v1/system/settings").json()
        assert settings["version"] == 0
        updated = client.put(
            "/api/v1/system/settings",
            headers={"If-Match": "0"},
            json={
                "timezone": "Asia/Shanghai",
                "interface_language": "zh-CN",
                "missing_episode_grace_hours": 24,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["setup_completed_steps"] == ["instance_preferences"]

        anime = client.post("/api/v1/catalog/anime", json={"title": "Calendar Anime"}).json()
        scheduled = client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            json={
                "air_date": "2026-07-20",
                "episode_count": 12,
                "airing_weekday": 0,
                "airing_time": "01:00",
                "schedule_timezone": "UTC",
            },
        )
        assert scheduled.status_code == 200
        subscription = client.post("/api/v1/subscriptions", json={"anime_id": anime["id"]}).json()

        initial = client.post("/api/v1/schedule/sync").json()
        assert initial == {"generated": 2, "acquired": 0, "missing": 0, "notifications": 0}
        calendar = client.get("/api/v1/schedule/calendar", params={"days": 8}).json()
        first = next(
            episode
            for day in calendar
            for episode in day["episodes"]
            if episode["episode_key"] == "1"
        )
        assert first["local_time"] == "09:00"
        assert first["state"] == "scheduled"

        current[0] = datetime(2026, 7, 21, 2, 0, tzinfo=UTC)
        missing = client.post("/api/v1/schedule/sync").json()
        duplicate = client.post("/api/v1/schedule/sync").json()
        assert missing["missing"] == 1
        assert missing["notifications"] == 1
        assert duplicate["notifications"] == 0

        client.post("/api/v1/operations/run-now")
        warnings = client.get("/api/v1/schedule/missing").json()
        assert [item["episode_key"] for item in warnings] == ["1"]
        notifications = client.get("/api/v1/notifications").json()
        assert [item["kind"] for item in notifications].count("episode_missing") == 1
        assert client.get("/api/v1/downloads/tasks").json() == []

        acquired = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/episodes/1/acquired-elsewhere"
        )
        assert acquired.status_code == 200
        result = client.post("/api/v1/schedule/sync").json()
        assert result["acquired"] == 1
        assert client.get("/api/v1/schedule/missing").json() == []
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        assert next(item for item in history if item["episode_key"] == "1")["state"] == "acquired"


def test_acceptable_fallback_suppresses_missing_warning(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 20, 0, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=_rss("[Fallback] Waiting Anime - 01 [1080p AVC][简体]"),
        )
    )
    with TestClient(
        create_app(_settings(tmp_path), clock=clock, feed_transport=transport)
    ) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Waiting Anime"}).json()
        client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            json={
                "air_date": "2026-07-20",
                "episode_count": 1,
                "airing_weekday": 0,
                "airing_time": "01:00",
                "schedule_timezone": "UTC",
            },
        )
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Preferred", "Fallback"],
                    "fallback_wait_minutes": 2880,
                },
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Waiting", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        slot = client.get(
            "/api/v1/selection/episodes", params={"subscription_id": subscription["id"]}
        ).json()[0]
        assert slot["state"] == "waiting_fallback"

        current[0] = datetime(2026, 7, 21, 2, 0, tzinfo=UTC)
        synced = client.post("/api/v1/schedule/sync").json()
        assert synced["missing"] == 0
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        assert history[0]["state"] == "scheduled"
        assert history[0]["has_acceptable_candidate"] is True
