from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.database import create_session_factory
from anime_rss.infrastructure.events import IntegrationEvent
from anime_rss.main import create_app
from anime_rss.modules.notifications.persistence import NotificationRecord
from fastapi.testclient import TestClient


def test_notification_event_webhook_delivery_and_read_state(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def webhook(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'notifications.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )
    with TestClient(create_app(settings, webhook_transport=httpx.MockTransport(webhook))) as client:
        configured = client.put(
            "/api/v1/notifications/config",
            headers={"If-Match": "0"},
            json={
                "webhook_enabled": True,
                "webhook_url": "https://notify.test/hook?secret=hidden",
                "bearer_token": "notification-secret",
            },
        )
        assert configured.status_code == 200
        assert configured.json()["webhook_url_redacted"] == "https://notify.test/hook"
        assert configured.json()["bearer_token_configured"] is True

        services: ServiceContainer = client.app.state.services
        services.notifications.handle_event(
            IntegrationEvent(
                id="event-1",
                name="DecisionCommitted.v1",
                version=1,
                payload={"decision_id": "decision-1", "kind": "selected_preferred"},
                occurred_at=datetime(2026, 7, 22, tzinfo=UTC),
            )
        )
        services.notifications.handle_event(
            IntegrationEvent(
                id="event-1",
                name="DecisionCommitted.v1",
                version=1,
                payload={"decision_id": "decision-1"},
                occurred_at=datetime(2026, 7, 22, tzinfo=UTC),
            )
        )

        notifications = client.get("/api/v1/notifications").json()
        assert len(notifications) == 1
        assert notifications[0]["delivery_state"] == "pending"
        delivered = client.post("/api/v1/notifications/process")
        assert delivered.json() == {"delivered": 1, "failed": 0}
        assert len(requests) == 1
        assert requests[0].headers["authorization"] == "Bearer notification-secret"
        assert requests[0].headers["idempotency-key"] == notifications[0]["id"]

        marked = client.post(f"/api/v1/notifications/{notifications[0]['id']}/read").json()
        assert marked["read_at"] is not None

    database_bytes = (tmp_path / "notifications.sqlite3").read_bytes()
    assert b"notification-secret" not in database_bytes
    assert b"secret=hidden" not in database_bytes


def test_webhook_transient_failure_is_retained_for_retry(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'retry.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with TestClient(create_app(settings, webhook_transport=transport)) as client:
        client.put(
            "/api/v1/notifications/config",
            headers={"If-Match": "0"},
            json={"webhook_enabled": True, "webhook_url": "https://notify.test/hook"},
        )
        services: ServiceContainer = client.app.state.services
        services.notifications.handle_event(
            IntegrationEvent(
                id="event-2",
                name="DownloadTaskChanged.v1",
                version=1,
                payload={"task_id": "task-1", "state": "completed"},
                occurred_at=datetime.now(UTC),
            )
        )
        assert client.post("/api/v1/notifications/process").json() == {
            "delivered": 0,
            "failed": 1,
        }
        notification = client.get("/api/v1/notifications").json()[0]
        assert notification["delivery_state"] == "retrying"
        assert notification["delivery_error_code"] == "webhook_unavailable"


def test_old_notification_can_be_marked_read_beyond_the_list_page_limit(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'old-notification.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=False,
        scheduler_poll_seconds=60,
    )
    with TestClient(create_app(settings)) as client:
        services: ServiceContainer = client.app.state.services
        sessions = create_session_factory(services.engine)
        created_at = datetime(2026, 7, 1, tzinfo=UTC)
        with sessions.begin() as session:
            session.add_all(
                NotificationRecord(
                    id=f"notification-{index:03d}",
                    source_event_id=f"event-{index:03d}",
                    kind="test",
                    level="info",
                    title=f"Notification {index}",
                    message="pagination regression",
                    created_at=created_at + timedelta(seconds=index),
                )
                for index in range(501)
            )

        response = client.post("/api/v1/notifications/notification-000/read")

        assert response.status_code == 200
        assert response.json()["id"] == "notification-000"
        assert response.json()["read_at"] is not None
