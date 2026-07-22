import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from anime_rss.modules.recognition import api as recognition_api
from anime_rss.modules.recognition.domain import MatchConfidence, normalize_series_key
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
        auth_enabled=False,
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


def test_manual_confirmation_re_evaluates_medium_confidence_candidate(tmp_path: Path) -> None:
    title = "Manual Anime - 01 [1080p AVC][CHS]"
    info_hash = "5" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        f"<guid>manual-confirm</guid><title>{title}</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Manual Anime"}).json()
        client.post(
            "/api/v1/subscriptions",
            json={"anime_id": anime["id"], "rules": {"fallback_wait_minutes": 0}},
        )
        feed = client.post(
            "/api/v1/feeds", json={"name": "Manual", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        candidate = client.get("/api/v1/recognition/episode-groups").json()[0]["candidates"][0]

        assert candidate["confidence"] == "medium"
        assert client.get("/api/v1/selection/episodes").json()[0]["state"] == "needs_confirmation"
        confirmed = client.post(f"/api/v1/recognition/candidates/{candidate['id']}/confirm")

        assert confirmed.status_code == 200
        assert confirmed.json()["recognition_eligible"] is True
        assert confirmed.json()["confidence"] == "high"
        assert client.get("/api/v1/selection/episodes").json()[0]["state"] == "decided"


def test_manual_remap_turns_unmatched_release_into_candidate(tmp_path: Path) -> None:
    info_hash = "6" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>manual-remap</guid><title>Unknown weekly package</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Mapped Anime"}).json()
        client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "allowed_subtitles": [],
                    "allowed_resolutions": [],
                    "allowed_codecs": [],
                    "fallback_wait_minutes": 0,
                },
            },
        )
        feed = client.post(
            "/api/v1/feeds", json={"name": "Unknown", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        unmatched = client.get("/api/v1/recognition/unmatched").json()[0]

        remapped = client.post(
            f"/api/v1/recognition/releases/{unmatched['release_id']}/remap",
            json={
                "series_title": "Mapped Anime",
                "episode_start": "2",
                "season": 1,
                "release_group": "Manual Group",
            },
        )

        assert remapped.status_code == 200
        assert remapped.json()["episode_key"] == "2"
        assert remapped.json()["recognition_eligible"] is True
        assert client.get("/api/v1/recognition/unmatched").json() == []
        assert client.get("/api/v1/selection/episodes").json()[0]["state"] == "decided"


def test_unmatched_release_can_be_dismissed_without_deleting_evidence(tmp_path: Path) -> None:
    info_hash = "d" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>dismiss-unmatched</guid><title>Unrecognized weekly package</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Dismiss", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        unmatched = client.get("/api/v1/recognition/unmatched").json()[0]

        first = client.post(f"/api/v1/recognition/releases/{unmatched['release_id']}/dismiss")
        second = client.post(f"/api/v1/recognition/releases/{unmatched['release_id']}/dismiss")

        assert first.status_code == 204
        assert second.status_code == 204
        assert client.get("/api/v1/recognition/unmatched").json() == []
        assert len(client.get("/api/v1/releases").json()) == 1

    database = sqlite3.connect(tmp_path / "recognition.sqlite3")
    try:
        assert database.execute("SELECT COUNT(*) FROM match_attempts").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM match_dismissed_releases").fetchone()[0] == 1
    finally:
        database.close()


def test_remap_supersedes_existing_candidate_without_rewriting_decision(tmp_path: Path) -> None:
    info_hash = "7" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>candidate-remap</guid><title>[Group] Corrected Anime - 01 [1080p AVC][CHS]</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Corrected Anime"}).json()
        client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "allowed_subtitles": [],
                    "allowed_resolutions": [],
                    "allowed_codecs": [],
                    "fallback_wait_minutes": 0,
                },
            },
        )
        feed = client.post(
            "/api/v1/feeds", json={"name": "Correction", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        previous = client.get("/api/v1/recognition/episode-groups").json()[0]["candidates"][0]
        decisions_before = client.get("/api/v1/selection/decisions").json()

        remapped = client.post(
            f"/api/v1/recognition/releases/{previous['release_id']}/remap",
            json={
                "series_title": "Corrected Anime",
                "episode_start": "2",
                "season": 1,
                "release_group": "Corrected Group",
            },
        )

        assert remapped.status_code == 200
        corrected = remapped.json()
        assert corrected["id"] != previous["id"]
        assert corrected["supersedes_candidate_id"] == previous["id"]
        assert corrected["episode_key"] == "2"
        groups = client.get("/api/v1/recognition/episode-groups").json()
        assert [group["episode_key"] for group in groups] == ["2"]
        decisions_after = client.get("/api/v1/selection/decisions").json()
        assert {item["episode_key"] for item in decisions_after} == {"1", "2"}
        assert decisions_before[0] in decisions_after
        actions = client.get("/api/v1/selection/manual-actions").json()
        assert actions[0]["action"] == "candidate_reassigned_after_decision"
        assert actions[0]["reason"]["previous_candidate_id"] == previous["id"]


def test_initial_recognition_remains_idempotent_after_rerun_migration(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss()))
    settings = _settings(tmp_path)

    with TestClient(create_app(settings, feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Idempotent", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        database = sqlite3.connect(tmp_path / "recognition.sqlite3")
        try:
            release_id, feed_entry_id = database.execute(
                "SELECT release_id, feed_entry_id FROM release_sources LIMIT 1"
            ).fetchone()
        finally:
            database.close()

        services = client.app.state.services
        services.recognition.recognize(release_id, feed_entry_id)
        services.recognition.recognize(release_id, feed_entry_id)

    database = sqlite3.connect(tmp_path / "recognition.sqlite3")
    try:
        attempts = database.execute(
            "SELECT trigger, COUNT(*) FROM match_attempts WHERE feed_entry_id = ? GROUP BY trigger",
            (feed_entry_id,),
        ).fetchall()
    finally:
        database.close()
    assert attempts == [("initial", 1)]


def test_parser_rerun_appends_attempt_without_duplicate_candidate(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss()))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Rerun", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        candidate = client.get("/api/v1/recognition/episode-groups").json()[0]["candidates"][0]

        first = client.post(f"/api/v1/recognition/releases/{candidate['release_id']}/rerun")
        second = client.post(f"/api/v1/recognition/releases/{candidate['release_id']}/rerun")

        assert first.status_code == 200
        assert first.json()["candidate_changed"] is False
        assert first.json()["candidate_adopted"] is False
        assert first.json()["candidate_id"] == candidate["id"]
        assert second.json()["attempt_id"] != first.json()["attempt_id"]

    database = sqlite3.connect(tmp_path / "recognition.sqlite3")
    try:
        attempts = database.execute(
            "SELECT trigger, COUNT(*) FROM match_attempts "
            "WHERE release_id = ? GROUP BY trigger ORDER BY trigger",
            (candidate["release_id"],),
        ).fetchall()
        candidate_count = database.execute(
            "SELECT COUNT(*) FROM match_candidates WHERE release_id = ?",
            (candidate["release_id"],),
        ).fetchone()[0]
    finally:
        database.close()
    assert attempts == [("explicit_rerun", 2), ("initial", 1)]
    assert candidate_count == 1


def test_changed_parser_rerun_supersedes_candidate_without_rewriting_decision(
    tmp_path: Path, monkeypatch
) -> None:
    info_hash = "8" * 40
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        "<guid>parser-rerun</guid><title>[Group] Parser Anime - 01 [1080p AVC][CHS]</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Parser Anime"}).json()
        client.post(
            "/api/v1/subscriptions",
            json={"anime_id": anime["id"], "rules": {"fallback_wait_minutes": 0}},
        )
        feed = client.post(
            "/api/v1/feeds", json={"name": "Parser", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        previous = client.get("/api/v1/recognition/episode-groups").json()[0]["candidates"][0]
        decisions_before = client.get("/api/v1/selection/decisions").json()
        original_parser = recognition_api.parse_release_title

        def changed_parser(title: str):
            parsed = original_parser(title)
            return replace(parsed, episode_start="2", episode_key="2")

        monkeypatch.setattr(recognition_api, "parse_release_title", changed_parser)
        rerun = client.post(f"/api/v1/recognition/releases/{previous['release_id']}/rerun")

        assert rerun.status_code == 200
        result = rerun.json()
        assert result["candidate_changed"] is True
        assert result["candidate_adopted"] is True
        assert result["previous_candidate_id"] == previous["id"]
        assert result["candidate_id"] != previous["id"]
        groups = client.get("/api/v1/recognition/episode-groups").json()
        assert [group["episode_key"] for group in groups] == ["2"]
        decisions_after = client.get("/api/v1/selection/decisions").json()
        assert {item["episode_key"] for item in decisions_after} == {"1", "2"}
        assert decisions_before[0] in decisions_after


def test_low_confidence_rerun_preserves_active_candidate(tmp_path: Path, monkeypatch) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss()))

    with TestClient(create_app(_settings(tmp_path), feed_transport=transport)) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "Safe rerun", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        previous = client.get("/api/v1/recognition/episode-groups").json()[0]["candidates"][0]
        original_parser = recognition_api.parse_release_title

        def low_confidence_parser(title: str):
            parsed = original_parser(title)
            return replace(
                parsed,
                series_title="Unsafe parser output",
                series_key=normalize_series_key("Unsafe parser output"),
                confidence=MatchConfidence.LOW,
                reason_code="parser_rerun_low_confidence",
            )

        monkeypatch.setattr(recognition_api, "parse_release_title", low_confidence_parser)
        rerun = client.post(f"/api/v1/recognition/releases/{previous['release_id']}/rerun")

        assert rerun.status_code == 200
        result = rerun.json()
        assert result["candidate_changed"] is False
        assert result["candidate_adopted"] is False
        assert result["candidate_id"] == previous["id"]
        assert client.get("/api/v1/recognition/unmatched").json() == []
        active = client.get("/api/v1/recognition/episode-groups").json()
        assert active[0]["candidates"][0]["id"] == previous["id"]
