from pathlib import Path

import httpx
import pytest
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, *, auth_enabled: bool = True, **values: object) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'browser-security.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=auth_enabled,
        scheduler_poll_seconds=60,
        **values,
    )


def test_host_validation_allows_ip_literals_and_configured_names(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        auth_enabled=False,
        browser_trusted_hosts="localhost,testserver,anime.home,*.trusted.home",
    )
    with TestClient(create_app(settings)) as client:
        assert (
            client.get("/api/v1/health/live", headers={"Host": "127.0.0.1:8080"}).status_code == 200
        )
        assert client.get("/api/v1/health/live", headers={"Host": "anime.home"}).status_code == 200
        assert (
            client.get("/api/v1/health/live", headers={"Host": "node.trusted.home"}).status_code
            == 200
        )
        rejected = client.get("/api/v1/health/live", headers={"Host": "rebind.example"})

        assert rejected.status_code == 400
        assert rejected.json()["code"] == "untrusted_host"
        assert rejected.headers["x-correlation-id"] == rejected.json()["correlation_id"]


def test_origin_validation_rejects_cross_site_writes_and_supports_https_proxy(
    tmp_path: Path,
) -> None:
    credentials = {"username": "admin", "password": "correct horse battery staple"}
    with TestClient(create_app(_settings(tmp_path / "default"))) as client:
        rejected = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "https://attacker.example"},
            json=credentials,
        )
        fetch_metadata = client.post(
            "/api/v1/auth/setup",
            headers={"Sec-Fetch-Site": "cross-site"},
            json=credentials,
        )
        accepted = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "http://testserver"},
            json=credentials,
        )

        assert rejected.status_code == 403
        assert rejected.json()["code"] == "origin_mismatch"
        assert fetch_metadata.status_code == 403
        assert fetch_metadata.json()["code"] == "cross_site_request_rejected"
        assert accepted.status_code == 200

    proxy_settings = _settings(
        tmp_path / "proxy",
        browser_trusted_origins="https://anime.example",
    )
    with TestClient(create_app(proxy_settings)) as client:
        accepted = client.post(
            "/api/v1/auth/setup",
            headers={"Host": "anime.example", "Origin": "https://anime.example"},
            json=credentials,
        )
        assert accepted.status_code == 200


def test_login_rate_limit_is_isolated_and_returns_retry_after(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        auth_rate_limit_attempts=2,
        auth_rate_limit_window_seconds=300,
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "correct horse battery staple"},
        )
        client.cookies.clear()
        invalid = {"username": "admin", "password": "wrong password value"}

        assert client.post("/api/v1/auth/login", json=invalid).status_code == 401
        assert client.post("/api/v1/auth/login", json=invalid).status_code == 401
        limited = client.post("/api/v1/auth/login", json=invalid)

        assert limited.status_code == 429
        assert limited.json()["code"] == "rate_limited"
        assert 1 <= int(limited.headers["retry-after"]) <= 300


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/v1/feeds/test",
            {"url": "https://feed.test/rss", "headers": {}},
        ),
        ("/api/v1/downloads/config/test", None),
        ("/api/v1/notifications/config/test", None),
    ],
)
def test_connection_test_rate_limits_are_endpoint_scoped(
    tmp_path: Path,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    feed = b'<?xml version="1.0"?><rss version="2.0"><channel /></rss>'
    settings = _settings(
        tmp_path,
        auth_enabled=False,
        connection_test_rate_limit_attempts=2,
        connection_test_rate_limit_window_seconds=60,
    )
    app = create_app(
        settings,
        feed_transport=httpx.MockTransport(lambda request: httpx.Response(200, content=feed)),
    )
    with TestClient(app) as client:
        first = client.post(path, json=payload) if payload is not None else client.post(path)
        second = client.post(path, json=payload) if payload is not None else client.post(path)
        limited = client.post(path, json=payload) if payload is not None else client.post(path)

        assert first.status_code != 429
        assert second.status_code != 429
        assert limited.status_code == 429
        assert limited.json()["code"] == "rate_limited"
