import base64
import hashlib
from pathlib import Path

from anime_rss.config import Settings
from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.main import create_app
from anime_rss.modules.audit.persistence import AuditEventRecord
from anime_rss.modules.system.persistence import AdminAccountRecord
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        master_key_file=tmp_path / "master.key",
        auth_enabled=enabled,
        scheduler_poll_seconds=60,
    )


def _legacy_scrypt_hash(password: str) -> str:
    salt = bytes(range(16))
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "$".join(
        (
            "scrypt-v1",
            str(2**14),
            "8",
            "1",
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(derived).decode(),
        )
    )


def test_first_run_setup_session_csrf_and_login(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
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
        engine = create_database_engine(settings.resolved_database_url)
        with create_session_factory(engine)() as session:
            password_hash = session.scalar(
                select(AdminAccountRecord.password_hash).where(
                    AdminAccountRecord.id == "administrator"
                )
            )
        engine.dispose()
        assert password_hash is not None and password_hash.startswith("$argon2id$")
        csrf = client.cookies.get("anime_rss_csrf")
        assert csrf
        assert client.cookies.get("anime_rss_session")
        progress = client.get("/api/v1/system/settings").json()
        assert progress["setup_completed_steps"] == ["administrator"]
        assert progress["setup_completed"] is False
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


def test_legacy_scrypt_login_upgrades_hash_without_changing_password_timestamp(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    password = "correct horse battery staple"
    app = create_app(settings)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "password": password},
            ).status_code
            == 200
        )
        engine = create_database_engine(settings.resolved_database_url)
        sessions = create_session_factory(engine)
        with sessions.begin() as session:
            account = session.get(AdminAccountRecord, "administrator")
            assert account is not None
            password_changed_at = account.password_changed_at
            account.password_hash = _legacy_scrypt_hash(password)

        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": password},
            ).status_code
            == 200
        )
        with sessions() as session:
            account = session.get(AdminAccountRecord, "administrator")
            assert account is not None
            assert account.password_hash.startswith("$argon2id$")
            assert account.password_changed_at == password_changed_at
            event_count = session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == "system.password_hash_upgraded")
            )
        assert event_count == 1

        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": password},
            ).status_code
            == 200
        )
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEventRecord)
                    .where(AuditEventRecord.event_type == "system.password_hash_upgraded")
                )
                == 1
            )
        engine.dispose()


def test_malformed_and_unknown_password_hashes_fail_authentication(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    password = "correct horse battery staple"
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "password": password},
            ).status_code
            == 200
        )
        engine = create_database_engine(settings.resolved_database_url)
        sessions = create_session_factory(engine)
        for stored in (
            "$argon2id$malformed",
            "unknown-v1$16384$8$1$c2FsdA==$aGFzaA==",
            "scrypt-v1$32768$8$1$c2FsdA==$aGFzaA==",
        ):
            with sessions.begin() as session:
                session.execute(
                    update(AdminAccountRecord)
                    .where(AdminAccountRecord.id == "administrator")
                    .values(password_hash=stored)
                )
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": password},
            )
            assert response.status_code == 401
            assert response.json()["code"] == "authentication_required"
            assert response.json()["message"] == "invalid credentials"
        engine.dispose()


def test_password_reset_writes_argon2id_and_revokes_existing_sessions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "password": "initial password value"},
            ).status_code
            == 200
        )
        app.state.services.auth.reset_password("replacement password value")
        assert client.get("/api/v1/feeds").status_code == 401

        engine = create_database_engine(settings.resolved_database_url)
        with create_session_factory(engine)() as session:
            password_hash = session.scalar(
                select(AdminAccountRecord.password_hash).where(
                    AdminAccountRecord.id == "administrator"
                )
            )
        engine.dispose()
        assert password_hash is not None and password_hash.startswith("$argon2id$")
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "initial password value"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "replacement password value"},
            ).status_code
            == 200
        )


def test_setup_progress_is_durable_ordered_and_idempotent(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "correct horse battery staple"},
        )
        assert setup.status_code == 200
        csrf = client.cookies.get("anime_rss_csrf")
        headers = {"x-csrf-token": csrf}

        first = client.post(
            "/api/v1/system/settings/setup/feed",
            headers=headers,
        ).json()
        duplicate = client.post(
            "/api/v1/system/settings/setup/feed",
            headers=headers,
        ).json()
        assert first["setup_completed_steps"] == ["administrator", "feed"]
        assert duplicate["version"] == first["version"]
        assert (
            client.post(
                "/api/v1/system/settings/setup/not-a-step",
                headers=headers,
            ).status_code
            == 422
        )

        for step in (
            "candidate_preview",
            "subscription",
            "download_defaults",
            "instance_preferences",
            "global_preferences",
            "qbittorrent_connection",
        ):
            response = client.post(
                f"/api/v1/system/settings/setup/{step}",
                headers=headers,
            )
            assert response.status_code == 200

        completed = client.get("/api/v1/system/settings").json()
        assert completed["setup_completed_steps"] == [
            "administrator",
            "instance_preferences",
            "qbittorrent_connection",
            "download_defaults",
            "feed",
            "global_preferences",
            "subscription",
            "candidate_preview",
        ]
        assert completed["setup_completed"] is True


def test_disabled_authentication_reports_an_open_local_instance(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, enabled=False))) as client:
        assert client.get("/api/v1/auth/status").json() == {
            "enabled": False,
            "setup_required": False,
            "authenticated": True,
            "username": None,
        }
        assert client.get("/api/v1/feeds").status_code == 200
