from pathlib import Path
from uuid import UUID

from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.database import create_session_factory
from anime_rss.main import create_app
from anime_rss.modules.audit.api import record_event
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, name: str = "http-contracts.sqlite3") -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / name}",
        master_key_file=tmp_path / f"{name}.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )


def test_idempotency_replays_success_and_rejects_key_reuse(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = {"Idempotency-Key": "feed-create-contract-1"}
        payload = {"name": "Primary", "url": "https://feed.test/primary"}

        first = client.post("/api/v1/feeds", headers=headers, json=payload)
        replay = client.post("/api/v1/feeds", headers=headers, json=payload)
        conflict = client.post(
            "/api/v1/feeds",
            headers=headers,
            json={"name": "Different", "url": "https://feed.test/different"},
        )

        assert first.status_code == replay.status_code == 201
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.content == first.content
        assert [item["id"] for item in client.get("/api/v1/feeds").json()] == [first.json()["id"]]
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_key_conflict"


def test_preconditions_and_errors_have_one_structured_shape(tmp_path: Path) -> None:
    correlation_id = "0c58dc59-12af-47fb-9127-3871ef62b1cb"
    with TestClient(create_app(_settings(tmp_path))) as client:
        feed = client.post(
            "/api/v1/feeds",
            json={"name": "Versioned", "url": "https://feed.test/versioned"},
        ).json()
        missing = client.patch(
            f"/api/v1/feeds/{feed['id']}",
            headers={"X-Correlation-ID": correlation_id},
            json={"name": "No precondition"},
        )
        stale = client.patch(
            f"/api/v1/feeds/{feed['id']}",
            headers={"If-Match": str(feed["version"] + 1)},
            json={"name": "Stale"},
        )
        invalid = client.get("/api/v1/feeds", params={"cursor": "not-a-cursor"})

        assert missing.status_code == 428
        assert missing.json() == {
            "code": "if_match_required",
            "message": "If-Match header is required",
            "details": None,
            "correlation_id": correlation_id,
            "detail": "If-Match header is required",
        }
        assert missing.headers["x-correlation-id"] == correlation_id
        assert stale.status_code == 409
        assert stale.json()["code"] == "conflict"
        UUID(stale.json()["correlation_id"])
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "unprocessable_request"
        UUID(invalid.json()["correlation_id"])


def test_cursor_pages_are_opaque_complete_and_non_overlapping(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for index in range(5):
            response = client.post(
                "/api/v1/feeds",
                json={"name": f"Feed {index}", "url": f"https://feed.test/{index}"},
            )
            assert response.status_code == 201

        expected_ids = [item["id"] for item in client.get("/api/v1/feeds").json()]
        seen_ids: list[str] = []
        cursor: str | None = None
        page_count = 0
        while True:
            params = {"limit": "2"}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get("/api/v1/feeds", params=params)
            assert response.status_code == 200
            assert response.headers["x-page-limit"] == "2"
            seen_ids.extend(item["id"] for item in response.json())
            page_count += 1
            cursor = response.headers.get("x-next-cursor")
            if cursor is None:
                break

        assert page_count == 3
        assert seen_ids == expected_ids
        assert len(seen_ids) == len(set(seen_ids))


def test_cursor_pages_continue_beyond_legacy_service_limit(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        services: ServiceContainer = client.app.state.services
        sessions = create_session_factory(services.engine)
        with sessions.begin() as session:
            for index in range(501):
                record_event(
                    session,
                    event_type="pagination.tested",
                    entity_type="test",
                    entity_id=f"event-{index:03d}",
                )

        seen_ids: list[str] = []
        cursor: str | None = None
        while True:
            params = {"limit": "200"}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get("/api/v1/audit/events", params=params)
            assert response.status_code == 200
            seen_ids.extend(item["id"] for item in response.json())
            cursor = response.headers.get("x-next-cursor")
            if cursor is None:
                break

        assert len(seen_ids) == 501
        assert len(seen_ids) == len(set(seen_ids))


def test_catalog_versions_change_only_when_resource_changes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Version Anime"}).json()
        missing = client.post(
            f"/api/v1/catalog/anime/{anime['id']}/aliases",
            json={"alias": "Version Alias"},
        )
        assert missing.status_code == 428

        added = client.post(
            f"/api/v1/catalog/anime/{anime['id']}/aliases",
            headers={"If-Match": str(anime["version"])},
            json={"alias": "Version Alias"},
        ).json()
        assert added["version"] == anime["version"] + 1

        unchanged_alias = client.post(
            f"/api/v1/catalog/anime/{anime['id']}/aliases",
            headers={"If-Match": str(added["version"])},
            json={"alias": "Version Alias"},
        ).json()
        assert unchanged_alias["version"] == added["version"]

        schedule = {
            "air_date": "2026-07-22",
            "episode_count": 12,
            "airing_weekday": 2,
            "airing_time": "23:00",
            "schedule_timezone": "Asia/Tokyo",
        }
        changed_schedule = client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            headers={"If-Match": str(added["version"])},
            json=schedule,
        ).json()
        unchanged_schedule = client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            headers={"If-Match": str(changed_schedule["version"])},
            json=schedule,
        ).json()
        stale = client.put(
            f"/api/v1/catalog/anime/{anime['id']}/schedule",
            headers={"If-Match": str(added["version"])},
            json=schedule,
        )

        assert changed_schedule["version"] == added["version"] + 1
        assert unchanged_schedule["version"] == changed_schedule["version"]
        assert stale.status_code == 409


def test_openapi_declares_idempotency_preconditions_and_cursor_headers(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        schema = client.get("/openapi.json").json()

    create_feed = schema["paths"]["/api/v1/feeds"]["post"]
    assert any(item["name"] == "Idempotency-Key" for item in create_feed["parameters"])
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    assert not any(item["name"] == "Idempotency-Key" for item in login["parameters"])
    alias = schema["paths"]["/api/v1/catalog/anime/{anime_id}/aliases"]["post"]
    if_match = next(item for item in alias["parameters"] if item["name"] == "If-Match")
    assert if_match["required"] is True
    feed_list_headers = schema["paths"]["/api/v1/feeds"]["get"]["responses"]["200"]["headers"]
    assert {"X-Next-Cursor", "X-Page-Limit"} <= set(feed_list_headers)
