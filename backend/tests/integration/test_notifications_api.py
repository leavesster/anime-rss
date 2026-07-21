from datetime import UTC, datetime
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.container import ServiceContainer
from anime_rss.infrastructure.events import IntegrationEvent
from anime_rss.main import create_app
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
