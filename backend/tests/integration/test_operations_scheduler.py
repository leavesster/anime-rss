from datetime import UTC, datetime
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.database import create_session_factory
from anime_rss.main import create_app
from anime_rss.modules.operations.persistence import ScheduledJobRecord
from fastapi.testclient import TestClient


def test_scheduler_refreshes_due_feed_and_exposes_diagnostics(tmp_path: Path) -> None:
    info_hash = "a" * 40
    batch_hash = "b" * 40
    unmatched_hash = "c" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>scheduled-1</guid><title>[Group] Scheduled Anime - 01 [1080p AVC]</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item>'
        "<item><guid>scheduled-batch</guid><title>[Group] Archive Anime BDRip [1080p]</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{batch_hash}" '
        'type="application/x-bittorrent" /></item>'
        "<item><guid>scheduled-unmatched</guid><title>[Group] Mystery Weekly Release</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{unmatched_hash}" '
        'type="application/x-bittorrent" /></item>'
        "</channel></rss>"
    ).encode()
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'scheduler.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        scheduler_poll_seconds=60,
        auth_enabled=False,
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(
        create_app(settings, feed_transport=transport, jitter=lambda maximum: 0)
    ) as client:
        feed = client.post(
            "/api/v1/feeds",
            json={"name": "Scheduled", "url": "https://feed.test/rss"},
        ).json()

        cycle = client.post("/api/v1/operations/run-now")

        assert cycle.status_code == 200
        assert cycle.json()["processed"] >= 1
        stored = client.get("/api/v1/feeds").json()[0]
        assert stored["id"] == feed["id"]
        assert stored["health"] == "healthy"
        assert stored["last_success_at"] is not None

        jobs = client.get("/api/v1/operations/jobs").json()
        assert {item["job_kind"] for item in jobs} >= {
            "feed.refresh",
            "events.dispatch",
            "selection.process_due",
            "downloads.process_cycle",
        }
        runs = client.get("/api/v1/operations/runs").json()
        assert any(
            item["job_kind"] == "feed.refresh" and item["status"] == "success" for item in runs
        )
        overview = client.get("/api/v1/operations/overview").json()
        assert overview["scheduler"]["last_success_at"] is not None
        assert {item["key"] for item in overview["dependencies"]} == {
            "feeds",
            "bangumi",
            "qbittorrent",
            "scheduler",
        }
        recognition_work = [
            item for item in overview["failed_work"] if item["kind"] == "recognition"
        ]
        assert len(recognition_work) == 1
        assert recognition_work[0]["title"] == "[Group] Mystery Weekly Release"
        assert recognition_work[0]["attention_kind"] == "confirmation"
        audit = client.get("/api/v1/audit/events").json()
        assert any(item["event_type"] == "feed.refresh_succeeded" for item in audit)


def test_feed_transient_failure_is_exposed_in_operations_diagnostics(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'scheduler.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        scheduler_poll_seconds=60,
        auth_enabled=False,
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    with TestClient(create_app(settings, feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds",
            json={"name": "Unavailable", "url": "https://feed.test/rss"},
        ).json()
        refreshed = client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        assert refreshed.status_code == 200
        assert refreshed.json()["status"] == "transient_failure"
        overview = client.get("/api/v1/operations/overview").json()
        feeds = next(item for item in overview["dependencies"] if item["key"] == "feeds")
        failed_feed = next(
            item for item in overview["failed_work"] if item["key"] == f"feed:{feed['id']}"
        )
        assert feeds["status"] == "degraded"
        assert failed_feed["kind"] == "feed"
        assert failed_feed["error_code"] == "upstream_unavailable"


def test_operations_overview_counts_all_jobs_and_does_not_hide_late_failures(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'scheduler.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        scheduler_poll_seconds=60,
        auth_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        baseline = client.get("/api/v1/operations/overview").json()["pending_jobs"]
        services: ServiceContainer = client.app.state.services
        sessions = create_session_factory(services.engine)
        future = datetime(2100, 1, 1, tzinfo=UTC)
        with sessions.begin() as session:
            session.add_all(
                ScheduledJobRecord(
                    id=f"bulk-{index:03d}",
                    job_kind="audit.test",
                    dedupe_key=f"bulk-{index:03d}",
                    payload={},
                    due_at=future,
                    created_at=future,
                    updated_at=future,
                )
                for index in range(500)
            )
            session.add(
                ScheduledJobRecord(
                    id="zz-failed",
                    job_kind="audit.test",
                    dedupe_key="failed",
                    payload={},
                    due_at=future,
                    last_error_code="persistent_failure",
                    created_at=future,
                    updated_at=future,
                )
            )

        overview = client.get("/api/v1/operations/overview").json()

        assert overview["pending_jobs"] == baseline + 501
        failed = next(item for item in overview["failed_work"] if item["key"] == "job:zz-failed")
        assert failed["error_code"] == "persistent_failure"
