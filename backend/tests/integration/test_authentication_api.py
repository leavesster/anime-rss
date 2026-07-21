from pathlib import Path

from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=enabled,
        scheduler_poll_seconds=60,
    )


def test_first_run_setup_session_csrf_and_login(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        status = client.get("/api/v1/auth/status").json()
        assert status == {
            "enabled": True,
            "setup_required": True,
            "authenticated": False,
            "username": None,
        }
        assert client.get("/api/v1/feeds").status_code == 428
        assert (
            client.post(
                "/api/v1/auth/setup", json={"username": "admin", "password": "too-short"}
            ).status_code
            == 422
        )

        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "correct horse battery staple"},
        )
        assert setup.status_code == 200
        assert setup.json()["username"] == "admin"
        csrf = client.cookies.get("anime_rss_csrf")
        assert csrf
        assert client.cookies.get("anime_rss_session")
        assert client.get("/api/v1/feeds").status_code == 200
        assert (
            client.post(
                "/api/v1/feeds",
                json={"name": "Protected", "url": "https://feed.test/rss"},
            ).status_code
            == 403
        )
        created = client.post(
            "/api/v1/feeds",
            headers={"x-csrf-token": csrf},
            json={"name": "Protected", "url": "https://feed.test/rss"},
        )
        assert created.status_code == 201

        assert client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf}).status_code == 204
        assert client.get("/api/v1/feeds").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong-password-value"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "correct horse battery staple"},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auth/status").json()["authenticated"] is True


def test_disabled_authentication_reports_an_open_local_instance(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, enabled=False))) as client:
        assert client.get("/api/v1/auth/status").json() == {
            "enabled": False,
            "setup_required": False,
            "authenticated": True,
            "username": None,
        }
        assert client.get("/api/v1/feeds").status_code == 200
