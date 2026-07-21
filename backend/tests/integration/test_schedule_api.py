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
            headers={"If-Match": str(anime["version"])},
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
            headers={"If-Match": str(anime["version"])},
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


def test_episode_overrides_cover_delays_double_episodes_specials_and_cancellations(
    tmp_path: Path,
) -> None:
    current = [datetime(2026, 7, 20, 0, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    with TestClient(create_app(_settings(tmp_path), clock=clock)) as client:
        client.put(
            "/api/v1/system/settings",
            headers={"If-Match": "0"},
            json={
                "timezone": "UTC",
                "interface_language": "zh-CN",
                "missing_episode_grace_hours": 24,
            },
        )
        anime = client.post("/api/v1/catalog/anime", json={"title": "Irregular Anime"}).json()
        client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            headers={"If-Match": str(anime["version"])},
            json={
                "air_date": "2026-07-20",
                "episode_count": 12,
                "airing_weekday": 0,
                "airing_time": "01:00",
                "schedule_timezone": "UTC",
            },
        )
        client.post("/api/v1/subscriptions", json={"anime_id": anime["id"]})
        assert client.post("/api/v1/schedule/sync").json()["generated"] == 2

        delayed_at = "2026-07-22T03:00:00Z"
        delayed = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/1",
            headers={"If-Match": "0"},
            json={"expected_at": delayed_at, "note": "provider postponement"},
        )
        assert delayed.status_code == 200
        assert delayed.json()["version"] == 1
        idempotent = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/1",
            headers={"If-Match": "1"},
            json={"expected_at": delayed_at, "note": "provider postponement"},
        )
        assert idempotent.json()["version"] == 1

        episode_two = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/2",
            headers={"If-Match": "0"},
            json={"expected_at": delayed_at, "note": "double episode"},
        ).json()
        special = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/SP1",
            headers={"If-Match": "0"},
            json={"expected_at": delayed_at, "source": "provider", "note": "special"},
        ).json()
        assert episode_two["version"] == 1
        assert special["source"] == "provider"

        synced = client.post("/api/v1/schedule/sync").json()
        assert synced["generated"] == 3
        calendar = client.get("/api/v1/schedule/calendar", params={"days": 8}).json()
        same_time = [
            episode
            for day in calendar
            for episode in day["episodes"]
            if episode["expected_at"] == "2026-07-22T03:00:00Z"
        ]
        assert {episode["episode_key"] for episode in same_time} == {"1", "2", "SP1"}
        assert (
            next(item for item in same_time if item["episode_key"] == "SP1")["schedule_source"]
            == "provider"
        )
        assert client.get("/api/v1/downloads/tasks").json() == []
        assert client.get("/api/v1/selection/decisions").json() == []

        cancelled = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/2",
            headers={"If-Match": str(episode_two["version"])},
            json={"cancelled": True, "note": "broadcast cancelled"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["version"] == 2
        client.post("/api/v1/schedule/sync")
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        assert next(item for item in history if item["episode_key"] == "2")["state"] == "inactive"
        calendar = client.get("/api/v1/schedule/calendar", params={"days": 8}).json()
        assert "2" not in {
            episode["episode_key"] for day in calendar for episode in day["episodes"]
        }

        moved_outside_horizon = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/SP1",
            headers={"If-Match": str(special["version"])},
            json={"expected_at": "2026-08-10T03:00:00Z", "source": "provider"},
        )
        assert moved_outside_horizon.status_code == 200
        client.post("/api/v1/schedule/sync")
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        assert next(item for item in history if item["episode_key"] == "SP1")["state"] == (
            "inactive"
        )

        restored = client.delete(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/2",
            headers={"If-Match": "2"},
        )
        assert restored.status_code == 204
        client.post("/api/v1/schedule/sync")
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        restored_episode = next(item for item in history if item["episode_key"] == "2")
        assert restored_episode["state"] == "scheduled"
        assert restored_episode["expected_at"] == "2026-07-27T01:00:00Z"
        assert restored_episode["schedule_source"] == "manual"

        conflict = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/1",
            headers={"If-Match": "99"},
            json={"expected_at": "2026-07-23T03:00:00Z"},
        )
        assert conflict.status_code == 409
        naive = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/OVA1",
            headers={"If-Match": "0"},
            json={"expected_at": "2026-07-23T03:00:00"},
        )
        assert naive.status_code == 422
        invalid_key = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/bad%20key",
            headers={"If-Match": "0"},
            json={"expected_at": "2026-07-23T03:00:00Z"},
        )
        assert invalid_key.status_code == 422

        overrides = client.get(f"/api/v1/schedule/anime/{anime['id']}/overrides").json()
        assert {item["episode_key"] for item in overrides} == {"1", "SP1"}
        audit_types = {event["event_type"] for event in client.get("/api/v1/audit/events").json()}
        assert {
            "schedule.override_created",
            "schedule.override_updated",
            "schedule.override_deleted",
        } <= audit_types


def test_missing_notification_uses_overridden_time_and_resets_after_reschedule(
    tmp_path: Path,
) -> None:
    current = [datetime(2026, 7, 20, 0, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    with TestClient(create_app(_settings(tmp_path), clock=clock)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Delayed Anime"}).json()
        client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            headers={"If-Match": str(anime["version"])},
            json={
                "air_date": "2026-07-20",
                "episode_count": 1,
                "airing_weekday": 0,
                "airing_time": "01:00",
                "schedule_timezone": "UTC",
            },
        )
        client.post("/api/v1/subscriptions", json={"anime_id": anime["id"]})
        client.post("/api/v1/schedule/sync")
        override = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/1",
            headers={"If-Match": "0"},
            json={"expected_at": "2026-07-21T01:00:00Z"},
        ).json()

        current[0] = datetime(2026, 7, 21, 2, 0, tzinfo=UTC)
        before_grace = client.post("/api/v1/schedule/sync").json()
        assert before_grace["missing"] == 0
        assert before_grace["notifications"] == 0

        current[0] = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
        missing = client.post("/api/v1/schedule/sync").json()
        assert missing["missing"] == 1
        assert missing["notifications"] == 1

        postponed_again = client.put(
            f"/api/v1/schedule/anime/{anime['id']}/overrides/1",
            headers={"If-Match": str(override["version"])},
            json={"expected_at": "2026-07-24T01:00:00Z"},
        )
        assert postponed_again.status_code == 200
        recovered = client.post("/api/v1/schedule/sync").json()
        assert recovered["missing"] == 0
        history = client.get(f"/api/v1/schedule/anime/{anime['id']}/episodes").json()
        assert history[0]["state"] == "scheduled"
        assert history[0]["missing_notified_at"] is None
