import json
from pathlib import Path
from uuid import UUID

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text


def _settings(tmp_path: Path, filename: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / filename}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )


def test_http_correlation_reaches_audit_events_and_json_logs(tmp_path: Path) -> None:
    correlation_id = "55bd5b86-c5a3-4c9e-b76f-6a75f060d1f1"
    info_hash = "a" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>observed</guid><title>[Group] Observable Anime - 01 [1080p AVC][CHS]</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(
        create_app(_settings(tmp_path, "observability.sqlite3"), feed_transport=transport)
    ) as client:
        created = client.post(
            "/api/v1/feeds",
            headers={"X-Correlation-ID": correlation_id},
            json={"name": "Private", "url": "https://feed.test/rss?token=never-log-this"},
        )
        assert created.headers["x-correlation-id"] == correlation_id
        refreshed = client.post(
            f"/api/v1/feeds/{created.json()['id']}/refresh",
            headers={"X-Correlation-ID": correlation_id},
        )
        assert refreshed.status_code == 200
        generated = client.get(
            "/api/v1/releases", headers={"X-Correlation-ID": "not-a-uuid"}
        ).headers["x-correlation-id"]
        assert str(UUID(generated)) == generated

        services: ServiceContainer = client.app.state.services
        with services.engine.connect() as connection:
            audit_ids = set(
                connection.scalars(
                    text("SELECT correlation_id FROM audit_events WHERE correlation_id IS NOT NULL")
                )
            )
            event_ids = set(
                connection.scalars(
                    text(
                        "SELECT correlation_id FROM runtime_integration_events "
                        "WHERE correlation_id IS NOT NULL"
                    )
                )
            )
        assert correlation_id in audit_ids
        assert correlation_id in event_ids

    log_text = (tmp_path / "logs" / "application.jsonl").read_text(encoding="utf-8")
    records = [json.loads(line) for line in log_text.splitlines()]
    assert any(
        record.get("event") == "http.request_completed"
        and record.get("correlation_id") == correlation_id
        and record.get("path") == "/api/v1/feeds"
        for record in records
    )
    assert "never-log-this" not in log_text


def test_scheduled_retention_preserves_subscription_and_correction_history(
    tmp_path: Path,
) -> None:
    hashes = {
        "keep": "1" * 40,
        "orphan": "2" * 40,
        "corrected": "3" * 40,
        "manual": "4" * 40,
    }

    def item(guid: str, title: str) -> str:
        return (
            f"<item><guid>{guid}</guid><title>{title}</title>"
            f'<enclosure url="magnet:?xt=urn:btih:{hashes[guid]}" '
            'type="application/x-bittorrent" /></item>'
        )

    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        + item("keep", "[Group] Keep Anime - 01 [1080p AVC][CHS]")
        + item("orphan", "[Group] Orphan Anime - 01 [1080p AVC][CHS]")
        + item("corrected", "Unknown weekly package")
        + item("manual", "Unsupported manual package")
        + "<item><guid>no-reference</guid><title>Unusable entry</title></item>"
        + "</channel></rss>"
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(
        create_app(_settings(tmp_path, "retention.sqlite3"), feed_transport=transport)
    ) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Keep Anime"}).json()
        client.post(
            "/api/v1/subscriptions",
            json={"anime_id": anime["id"], "rules": {"fallback_wait_minutes": 0}},
        )
        feed = client.post(
            "/api/v1/feeds", json={"name": "Retention", "url": "https://feed.test/rss"}
        ).json()
        assert client.post(f"/api/v1/feeds/{feed['id']}/refresh").status_code == 200
        unmatched = client.get("/api/v1/recognition/unmatched").json()
        corrected = next(
            item for item in unmatched if item["source_title"] == "Unknown weekly package"
        )
        assert (
            client.post(
                f"/api/v1/recognition/releases/{corrected['release_id']}/remap",
                json={"series_title": "Corrected Anime", "episode_start": "1"},
            ).status_code
            == 200
        )
        manual = next(
            item for item in unmatched if item["source_title"] == "Unsupported manual package"
        )
        assert (
            client.post(f"/api/v1/downloads/releases/{manual['release_id']}/submit").status_code
            == 201
        )

        services: ServiceContainer = client.app.state.services
        old = "2025-01-01T00:00:00Z"
        with services.engine.begin() as connection:
            connection.execute(text("UPDATE feed_entries SET first_seen_at = :old"), {"old": old})
            connection.execute(
                text("UPDATE feed_fetches SET started_at = :old, finished_at = :old"), {"old": old}
            )
            connection.execute(
                text("UPDATE release_releases SET first_seen_at = :old"), {"old": old}
            )
            connection.execute(
                text("UPDATE runtime_integration_events SET occurred_at = :old"), {"old": old}
            )
            connection.execute(
                text(
                    "UPDATE runtime_job_runs SET started_at = :old, finished_at = :old "
                    "WHERE status != 'running'"
                ),
                {"old": old},
            )
            connection.execute(
                text(
                    "UPDATE runtime_scheduled_jobs SET due_at = :old "
                    "WHERE job_kind = 'system.retention'"
                ),
                {"old": old},
            )

        assert client.post("/api/v1/operations/run-now").status_code == 200
        remaining_hashes = {
            item["identity_value"] for item in client.get("/api/v1/releases").json()
        }
        assert remaining_hashes == {hashes["keep"], hashes["corrected"], hashes["manual"]}
        with services.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM feed_entries")) == 3
            assert connection.scalar(text("SELECT count(*) FROM feed_fetches")) == 0
        retention_run = next(
            item
            for item in client.get("/api/v1/operations/runs?limit=500").json()
            if item["job_kind"] == "system.retention"
        )
        assert retention_run["status"] == "success"
        assert retention_run["details"]["releases_removed"] == 1
        assert retention_run["details"]["feed_entries_removed"] == 2
