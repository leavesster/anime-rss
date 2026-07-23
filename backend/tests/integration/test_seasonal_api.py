import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'seasonal.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )


def _subject(subject_id: int, name: str, *, platform: str = "TV") -> dict[str, object]:
    return {
        "id": subject_id,
        "name": name,
        "name_cn": f"{name} 中文",
        "date": "2026-07-04",
        "eps": 12,
        "platform": platform,
        "summary": f"{name} summary",
        "images": {"large": f"https://lain.bgm.tv/{subject_id}.jpg"},
        "collection": {"wish": subject_id, "doing": 10},
        "rating": {"score": 8.2, "total": 321},
        "infobox": [
            {"key": "放送星期", "value": "星期六"},
            {"key": "放送开始", "value": "2026年7月4日 23:30"},
        ],
    }


def test_seasonal_overview_caches_and_drives_subscription_lifecycle(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def bangumi(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v0/search/subjects":
            payload = json.loads(request.content)
            assert payload["filter"]["air_date"] == [">=2026-07-01", "<2026-10-01"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        _subject(101, "Popular Anime"),
                        _subject(102, "Second Anime", platform="WEB"),
                        _subject(103, "Movie", platform="剧场版"),
                    ],
                    "total": 3,
                },
            )
        subject_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=_subject(subject_id, f"Anime {subject_id}"))

    def clock() -> datetime:
        return datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    with TestClient(
        create_app(
            _settings(tmp_path),
            bangumi_transport=httpx.MockTransport(bangumi),
            clock=clock,
        )
    ) as client:
        first = client.get("/api/v1/seasonal")
        second = client.get("/api/v1/seasonal")

        assert first.status_code == 200
        assert second.json() == first.json()
        assert first.json()["title"] == "2026 年 7 月新番"
        assert [item["bangumi_id"] for item in first.json()["items"]] == [102, 101]
        assert {item["status"] for item in first.json()["items"]} == {"undecided"}
        assert first.json()["items"][0]["rating_score"] == 8.2
        assert first.json()["items"][0]["rating_total"] == 321
        assert len([request for request in requests if request.method == "POST"]) == 1

        watched_without_subscription = client.post("/api/v1/seasonal/102/watched")
        assert watched_without_subscription.status_code == 200
        assert watched_without_subscription.json()["status"] == "watched"
        assert watched_without_subscription.json()["subscription_id"] is None

        dismissed = client.post("/api/v1/seasonal/102/dismiss")
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"

        followed = client.post("/api/v1/seasonal/101/follow")
        assert followed.status_code == 200
        assert followed.json()["status"] == "following"
        subscription_id = followed.json()["subscription_id"]
        subscriptions = client.get("/api/v1/subscriptions").json()
        assert [(item["id"], item["state"]) for item in subscriptions] == [
            (subscription_id, "following")
        ]

        watched = client.post("/api/v1/seasonal/101/watched")
        assert watched.json()["status"] == "watched"
        assert client.get("/api/v1/subscriptions").json()[0]["state"] == "archived"

        overview = client.get("/api/v1/seasonal").json()
        assert {item["bangumi_id"]: item["status"] for item in overview["items"]} == {
            101: "watched",
            102: "dismissed",
        }

        resumed = client.post("/api/v1/seasonal/101/follow")
        assert resumed.json()["status"] == "following"
        assert resumed.json()["subscription_id"] == subscription_id
        assert client.get("/api/v1/subscriptions").json()[0]["state"] == "following"

        refreshed = client.post("/api/v1/seasonal/refresh", params={"year": 2026, "quarter": 3})
        assert refreshed.status_code == 200
        assert len([request for request in requests if request.method == "POST"]) == 2


def test_seasonal_period_validation(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/seasonal", params={"year": 2026, "quarter": 5})

    assert response.status_code == 422
    assert response.json()["message"] == "quarter must be between 1 and 4"
