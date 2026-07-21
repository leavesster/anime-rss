import sqlite3
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _rss() -> bytes:
    titles = [
        (
            "nix-1",
            "[Nix-Raws] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "S01E01 [CR WEB-DL 1080p AVC AAC][简繁内封]",
            "1111111111111111111111111111111111111111",
        ),
        (
            "mouse-1",
            "[黒ネズミたち] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "- 01 (ABEMA 1920x1080 AVC AAC MKV)",
            "2222222222222222222222222222222222222222",
        ),
        (
            "nix-2",
            "[Nix-Raws] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "S01E02 [CR WEB-DL 1080p AVC AAC][简繁内封]",
            "3333333333333333333333333333333333333333",
        ),
        (
            "mouse-2",
            "[黒ネズミたち] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
            "- 02 (ABEMA 1920x1080 AVC AAC MKV)",
            "4444444444444444444444444444444444444444",
        ),
    ]
    items = "".join(
        f"<item><guid>{guid}</guid><title>{title}</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item>'
        for guid, title, info_hash in titles
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'recognition.sqlite3'}",
        master_key_file=tmp_path / "master.key",
    )


def test_release_events_create_episode_candidate_groups(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss()))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Mixed groups", "url": "https://feed.test/rss"}
        ).json()
        refreshed = client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        assert refreshed.status_code == 200
        assert refreshed.json()["dispatched_events"] == 12
        groups = client.get("/api/v1/recognition/episode-groups").json()
        assert len(groups) == 2
        assert {group["episode_key"] for group in groups} == {"1", "2"}
        assert {group["candidate_count"] for group in groups} == {2}
        assert {
            candidate["release_group"] for group in groups for candidate in group["candidates"]
        } == {"Nix-Raws", "黒ネズミたち"}
        assert all(
            candidate["recognition_eligible"]
            for group in groups
            for candidate in group["candidates"]
        )


def test_existing_release_events_are_backfilled_on_startup(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss()))

    with TestClient(create_app(settings, feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Mixed groups", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

    database = sqlite3.connect(tmp_path / "recognition.sqlite3")
    try:
        database.execute("DELETE FROM match_candidates")
        database.execute("DELETE FROM match_attempts")
        database.execute(
            "DELETE FROM runtime_integration_event_deliveries WHERE consumer = ?",
            ("recognition.release-identifier.v1",),
        )
        database.commit()
    finally:
        database.close()

    with TestClient(create_app(settings, feed_transport=transport)) as restarted:
        groups = restarted.get("/api/v1/recognition/episode-groups").json()
        assert len(groups) == 2
