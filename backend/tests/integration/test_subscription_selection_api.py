from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / name}",
        master_key_file=tmp_path / f"{name}.key",
        auth_enabled=False,
    )


def _rss(title: str, info_hash: str = "a" * 40) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><item>'
        f"<guid>{info_hash}</guid><title>{title}</title>"
        f'<enclosure url="magnet:?xt=urn:btih:{info_hash}" '
        'type="application/x-bittorrent" /></item></channel></rss>'
    ).encode()


def test_catalog_search_is_cached_and_bangumi_anime_can_be_imported(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def bangumi(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = {
            "id": 123,
            "name": "Mujikaku Seijo",
            "name_cn": "无自觉圣女今天也无意识地释放力量",
            "summary": "summary",
            "date": "2026-07-01",
            "eps": 12,
            "images": {"large": "https://lain.bgm.tv/pic.jpg"},
            "infobox": [
                {"key": "别名", "value": [{"v": "Mujikaku Seijo"}]},
                {"key": "放送星期", "value": "星期三"},
                {"key": "放送开始", "value": "2026-07-01 23:30"},
            ],
        }
        if request.method == "POST":
            return httpx.Response(200, json={"data": [item]})
        return httpx.Response(200, json=item)

    with TestClient(
        create_app(
            _settings(tmp_path, "catalog.sqlite3"),
            bangumi_transport=httpx.MockTransport(bangumi),
            feed_transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=_rss(
                        "[Nix-Raws] 無自覺聖女今天也無意識地釋放力量 - 01 [1080p AVC][繁體]"
                    ),
                )
            ),
        )
    ) as client:
        first = client.get("/api/v1/catalog/bangumi/search", params={"query": "圣女"})
        second = client.get("/api/v1/catalog/bangumi/search", params={"query": "圣女"})
        feed = client.post(
            "/api/v1/feeds", json={"name": "Traditional", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        assert client.get("/api/v1/recognition/episode-groups").json()[0]["anime_id"] is None
        imported = client.post("/api/v1/catalog/bangumi/123/import")

        assert first.status_code == 200
        assert second.json() == first.json()
        assert len([request for request in requests if request.method == "POST"]) == 1
        assert imported.status_code == 200
        assert imported.json()["bangumi_id"] == 123
        assert imported.json()["schedule_timezone"] == "Asia/Tokyo"
        assert imported.json()["airing_weekday"] == 2
        assert imported.json()["airing_time"] == "23:30"
        assert {title["normalized"] for title in imported.json()["titles"]} >= {
            "无自觉圣女今天也无意识地释放力量",
            "mujikakuseijo",
        }
        group = client.get("/api/v1/recognition/episode-groups").json()[0]
        assert group["anime_id"] == imported.json()["id"]
        assert group["series_identity"] == f"anime:{imported.json()['id']}"
        assert group["candidates"][0]["catalog_match_method"] == "semantic"


def test_ambiguous_catalog_title_requires_binding_and_reuses_it_for_later_entries(
    tmp_path: Path,
) -> None:
    current_rss = [_rss("[Group] 胆大党 - 01 [1080p AVC][简体]", "c" * 40)]
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=current_rss[0])
    )
    with TestClient(
        create_app(_settings(tmp_path, "title-binding.sqlite3"), feed_transport=feed_transport)
    ) as client:
        client.post("/api/v1/catalog/anime", json={"title": "胆大党"}).raise_for_status()
        selected = client.post("/api/v1/catalog/anime", json={"title": "胆大党"}).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Ambiguous", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh").raise_for_status()

        ambiguous = client.get("/api/v1/recognition/episode-groups").json()[0]
        assert ambiguous["anime_id"] is None
        assert ambiguous["catalog_match_status"] == "ambiguous"

        bound = client.post(
            f"/api/v1/catalog/anime/{selected['id']}/title-bindings",
            json={"titles": ["胆大党"]},
        )
        assert bound.status_code == 200
        resolved = client.get("/api/v1/recognition/episode-groups").json()[0]
        assert resolved["anime_id"] == selected["id"]
        assert resolved["candidates"][0]["catalog_match_method"] == "manual_exact"

        client.post("/api/v1/catalog/anime", json={"title": "膽大黨"}).raise_for_status()
        current_rss[0] = _rss("[Group] 膽大黨 - 02 [1080p AVC][繁體]", "d" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh").raise_for_status()

        groups = client.get("/api/v1/recognition/episode-groups").json()
        assert {group["episode_key"] for group in groups} == {"1", "2"}
        assert {group["anime_id"] for group in groups} == {selected["id"]}
        second = next(group for group in groups if group["episode_key"] == "2")
        assert second["candidates"][0]["catalog_match_method"] == "manual_semantic"


def test_historical_candidates_require_backfill_preview_and_explicit_commit(
    tmp_path: Path,
) -> None:
    title = (
        "[Nix-Raws] 无自觉圣女今天也无意识地释放力量 / Mujikaku Seijo "
        "S01E01 [CR WEB-DL 1080p AVC AAC][简繁内封]"
    )
    feed_transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_rss(title)))
    with TestClient(
        create_app(_settings(tmp_path, "backfill.sqlite3"), feed_transport=feed_transport)
    ) as client:
        feed = client.post(
            "/api/v1/feeds", json={"name": "One", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        anime = client.post(
            "/api/v1/catalog/anime",
            json={"title": "无自觉圣女今天也无意识地释放力量"},
        ).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Nix-Raws"],
                    "preferred_codecs": ["AVC"],
                    "fallback_wait_minutes": 120,
                },
            },
        ).json()

        assert client.get("/api/v1/selection/episodes").json() == []
        preview = client.get(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-preview"
        ).json()
        assert preview[0]["episode_key"] == "1"
        assert preview[0]["selected_candidate_id"] is not None
        committed = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-commit",
            json={"episode_keys": ["1"]},
        )
        duplicate = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-commit",
            json={"episode_keys": ["1"]},
        )

        assert committed.json() == {"processed": 1}
        assert duplicate.json() == {"processed": 0}
        assert client.get("/api/v1/selection/episodes").json()[0]["state"] == "decided"
        decision = client.get("/api/v1/selection/decisions").json()[0]
        assert decision["kind"] == "selected_backfill"
        assert decision["candidate_snapshot"]["release_group"] == "Nix-Raws"


def test_manual_alias_correction_matches_later_entries(tmp_path: Path) -> None:
    current_rss = [_rss("[Group] Unexpected Show - 01 [1080p AVC][CHS]", "1" * 40)]
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=current_rss[0])
    )
    with TestClient(
        create_app(_settings(tmp_path, "alias.sqlite3"), feed_transport=feed_transport)
    ) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Canonical Show"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {"fallback_wait_minutes": 0},
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Alias", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        assert client.get("/api/v1/selection/episodes").json() == []

        corrected = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"aliases": ["Unexpected Show"]},
        )
        assert corrected.status_code == 200
        assert "unexpectedshow" in corrected.json()["match_keys"]

        current_rss[0] = _rss("[Group] Unexpected Show - 02 [1080p AVC][CHS]", "2" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        episodes = client.get("/api/v1/selection/episodes").json()
        assert {(episode["episode_key"], episode["state"]) for episode in episodes} == {
            ("1", "decided"),
            ("2", "decided"),
        }


def test_fallback_deadline_survives_and_commits_when_due(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 21, 12, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=_rss("[Nix-Raws] Test Anime - 01 [1080p AVC][简体]", "b" * 40),
        )
    )
    settings = _settings(tmp_path, "waiting.sqlite3")
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Test Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Preferred", "Nix-Raws"],
                    "preferred_subtitles": ["zh-Hans+zh-Hant", "zh-Hans"],
                    "preferred_resolutions": ["1080p"],
                    "preferred_codecs": ["HEVC", "AVC"],
                    "fallback_wait_minutes": 60,
                },
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "One", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        slot = client.get("/api/v1/selection/episodes").json()[0]

        assert slot["state"] == "waiting_fallback"
        assert slot["fallback_deadline"] == "2026-07-21T13:00:00Z"
        paused = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"state": "paused"},
        ).json()
        assert paused["state"] == "paused"
        resumed = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(paused["version"])},
            json={"state": "following"},
        ).json()
        assert resumed["activation_at"] == "2026-07-21T12:00:00Z"

    current[0] += timedelta(minutes=61)
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as restarted:
        decision = restarted.get("/api/v1/selection/decisions").json()[0]
        assert decision["kind"] == "selected_fallback"


def test_resume_does_not_commit_a_candidate_from_the_previous_epoch(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 21, 12, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return current[0]

    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=_rss("[Nix-Raws] Epoch Anime - 01 [1080p AVC][简体]", "c" * 40),
        )
    )
    settings = _settings(tmp_path, "epochs.sqlite3")
    with TestClient(create_app(settings, feed_transport=feed_transport, clock=clock)) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Epoch Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={
                "anime_id": anime["id"],
                "rules": {
                    "preferred_groups": ["Preferred", "Nix-Raws"],
                    "fallback_wait_minutes": 60,
                },
            },
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Epoch", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        current[0] += timedelta(minutes=10)
        paused = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"state": "paused"},
        ).json()
        current[0] += timedelta(minutes=10)
        client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(paused["version"])},
            json={"state": "following"},
        )
        current[0] += timedelta(minutes=50)

        assert client.post("/api/v1/selection/process-due").json() == {"processed": 0}
        assert client.get("/api/v1/selection/decisions").json() == []
        slot = client.get("/api/v1/selection/episodes").json()[0]
        assert slot["state"] == "open"
        assert slot["fallback_deadline"] is None


def test_range_coverage_skips_full_duplicates_and_gates_partial_overlap(
    tmp_path: Path,
) -> None:
    current_rss = [_rss("[Group] Range Anime - 01-02 [1080p AVC][简体]", "1" * 40)]
    feed_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=current_rss[0])
    )
    with TestClient(
        create_app(_settings(tmp_path, "range-coverage.sqlite3"), feed_transport=feed_transport)
    ) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Range Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={"anime_id": anime["id"], "rules": {"fallback_wait_minutes": 0}},
        ).json()
        feed = client.post(
            "/api/v1/feeds", json={"name": "Range", "url": "https://feed.test/rss"}
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        decisions = client.get(
            "/api/v1/selection/decisions", params={"subscription_id": subscription["id"]}
        ).json()
        assert [(item["episode_key"], item["kind"]) for item in decisions] == [
            ("1-2", "selected_fallback")
        ]

        for episode, info_hash in (("01", "2" * 40), ("02", "3" * 40)):
            current_rss[0] = _rss(f"[Other] Range Anime - {episode} [1080p AVC][简体]", info_hash)
            client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        assert (
            len(
                client.get(
                    "/api/v1/selection/decisions",
                    params={"subscription_id": subscription["id"]},
                ).json()
            )
            == 1
        )
        preview = client.get(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-preview"
        ).json()
        singles = {
            item["episode_key"]: item for item in preview if item["episode_key"] in {"1", "2"}
        }
        assert singles["1"]["candidates"][0]["coverage_status"] == "full"
        assert singles["2"]["candidates"][0]["coverage_status"] == "full"
        assert singles["1"]["selected_candidate_id"] is None

        overlap_anime = client.post("/api/v1/catalog/anime", json={"title": "Overlap Anime"}).json()
        overlap_subscription = client.post(
            "/api/v1/subscriptions",
            json={"anime_id": overlap_anime["id"], "rules": {"fallback_wait_minutes": 0}},
        ).json()
        current_rss[0] = _rss("[Group] Overlap Anime - 01 [1080p AVC][简体]", "4" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        current_rss[0] = _rss("[Group] Overlap Anime - 01-02 [1080p AVC][简体]", "5" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        slots = client.get(
            "/api/v1/selection/episodes",
            params={"subscription_id": overlap_subscription["id"]},
        ).json()
        overlap_slot = next(item for item in slots if item["episode_key"] == "1-2")
        assert overlap_slot["state"] == "needs_confirmation"
        assert overlap_slot["confirmation_reason"] == {
            "kind": "episode_coverage_overlap",
            "status": "partial",
            "covered_episode_keys": ["1", "2"],
            "already_covered_episode_keys": ["1"],
            "detail": None,
        }
        overlap_preview = client.get(
            f"/api/v1/selection/subscriptions/{overlap_subscription['id']}/backfill-preview"
        ).json()
        range_preview = next(item for item in overlap_preview if item["episode_key"] == "1-2")
        candidate = range_preview["candidates"][0]
        assert candidate["eligible"] is False
        assert candidate["coverage_status"] == "partial"
        assert candidate["already_covered_episode_keys"] == ["1"]
        assert range_preview["selected_candidate_id"] is None

        selected = client.post(
            f"/api/v1/selection/subscriptions/{overlap_subscription['id']}"
            f"/candidates/{candidate['candidate_id']}/select",
            json={},
        )
        assert selected.status_code == 200
        assert (
            len(
                client.get(
                    "/api/v1/selection/decisions",
                    params={"subscription_id": overlap_subscription["id"]},
                ).json()
            )
            == 2
        )


def test_completed_only_accepts_revision_upgrades_and_archived_stops_all_automation(
    tmp_path: Path,
) -> None:
    current_rss = [_rss("[Group] Lifecycle Anime - 01 [1080p AVC][简体]", "6" * 40)]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=current_rss[0]))
    with TestClient(
        create_app(_settings(tmp_path, "lifecycle.sqlite3"), feed_transport=transport)
    ) as client:
        anime = client.post("/api/v1/catalog/anime", json={"title": "Lifecycle Anime"}).json()
        subscription = client.post(
            "/api/v1/subscriptions",
            json={"anime_id": anime["id"], "rules": {"fallback_wait_minutes": 0}},
        ).json()
        feed = client.post(
            "/api/v1/feeds",
            json={"name": "Lifecycle", "url": "https://feed.test/rss"},
        ).json()
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        completed = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(subscription["version"])},
            json={"state": "completed"},
        ).json()
        current_rss[0] = _rss("[Group] Lifecycle Anime - 02 [1080p AVC][简体]", "7" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        current_rss[0] = _rss("[Group] Lifecycle Anime - 01V2 [1080p AVC][简体]", "8" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")

        decisions = client.get(
            "/api/v1/selection/decisions", params={"subscription_id": subscription["id"]}
        ).json()
        assert [item["kind"] for item in decisions] == [
            "selected_upgrade",
            "selected_fallback",
        ]
        assert {item["episode_key"] for item in decisions} == {"1"}

        archived = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(completed["version"])},
            json={"state": "archived"},
        ).json()
        current_rss[0] = _rss("[Group] Lifecycle Anime - 01V3 [1080p AVC][简体]", "9" * 40)
        client.post(f"/api/v1/feeds/{feed['id']}/refresh")
        assert (
            len(
                client.get(
                    "/api/v1/selection/decisions",
                    params={"subscription_id": subscription["id"]},
                ).json()
            )
            == 2
        )

        illegal_resume = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(archived["version"])},
            json={"state": "following"},
        )
        assert illegal_resume.status_code == 422
        restored = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(archived["version"])},
            json={"state": "paused"},
        ).json()
        resumed = client.patch(
            f"/api/v1/subscriptions/{subscription['id']}",
            headers={"If-Match": str(restored["version"])},
            json={"state": "following"},
        )
        assert resumed.status_code == 200


def test_global_preferences_and_manual_episode_controls_are_auditable(tmp_path: Path) -> None:
    feeds = {
        "/a": _rss("[Group-A] Manual Anime - 01 [1080p HEVC][简体]", "d" * 40),
        "/b": _rss("[Group-B] Manual Anime - 01 [1080p AVC][简体]", "e" * 40),
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=feeds[request.url.path])
    )
    with TestClient(
        create_app(_settings(tmp_path, "manual-controls.sqlite3"), feed_transport=transport)
    ) as client:
        global_profile = client.put(
            "/api/v1/subscriptions/preferences/global",
            headers={"If-Match": "0"},
            json={
                "preferred_groups": ["Group-A", "Group-B"],
                "preferred_codecs": ["HEVC", "AVC"],
                "fallback_wait_minutes": 30,
            },
        )
        assert global_profile.status_code == 200
        assert global_profile.json()["version"] == 1

        for name in ("a", "b"):
            feed = client.post(
                "/api/v1/feeds",
                json={"name": name, "url": f"https://feed.test/{name}"},
            ).json()
            assert client.post(f"/api/v1/feeds/{feed['id']}/refresh").status_code == 200

        anime = client.post("/api/v1/catalog/anime", json={"title": "Manual Anime"}).json()
        subscription = client.post("/api/v1/subscriptions", json={"anime_id": anime["id"]}).json()
        assert subscription["uses_global_rules"] is True
        assert subscription["rules"]["preferred_groups"] == ["Group-A", "Group-B"]

        preview = client.get(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-preview"
        ).json()[0]
        candidates = {item["release_group"]: item["candidate_id"] for item in preview["candidates"]}
        selected_b = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}"
            f"/candidates/{candidates['Group-B']}/select",
            json={},
        )
        assert selected_b.status_code == 200

        conflict = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}"
            f"/candidates/{candidates['Group-A']}/select",
            json={},
        )
        assert conflict.status_code == 409
        replacement = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}"
            f"/candidates/{candidates['Group-A']}/select",
            json={"replace_existing": True},
        )
        assert replacement.status_code == 200
        decisions = client.get(
            "/api/v1/selection/decisions",
            params={"subscription_id": subscription["id"]},
        ).json()
        assert [item["kind"] for item in decisions] == [
            "selected_manual_replacement",
            "selected_manual",
        ]

        reset = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/episodes/1/reset"
        )
        assert reset.status_code == 200
        rejected = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}"
            f"/candidates/{candidates['Group-A']}/reject"
        )
        assert rejected.status_code == 200
        preview_after_rejection = client.get(
            f"/api/v1/selection/subscriptions/{subscription['id']}/backfill-preview"
        ).json()[0]
        assert preview_after_rejection["selected_candidate_id"] is None
        assert {item["coverage_status"] for item in preview_after_rejection["candidates"]} == {
            "full"
        }
        assert (
            "manually_rejected"
            in next(
                item
                for item in preview_after_rejection["candidates"]
                if item["candidate_id"] == candidates["Group-A"]
            )["rejection_reasons"]
        )

        acquired = client.post(
            f"/api/v1/selection/subscriptions/{subscription['id']}/episodes/2/acquired-elsewhere"
        )
        assert acquired.status_code == 200
        actions = client.get(
            "/api/v1/selection/manual-actions",
            params={"subscription_id": subscription["id"]},
        ).json()
        assert {item["action"] for item in actions} >= {
            "selected",
            "replaced",
            "reset",
            "rejected",
            "acquired_elsewhere",
        }

        updated_profile = client.put(
            "/api/v1/subscriptions/preferences/global",
            headers={"If-Match": "1"},
            json={"preferred_groups": ["Group-B"], "fallback_wait_minutes": 5},
        )
        assert updated_profile.json()["version"] == 2
        refreshed_subscription = client.get("/api/v1/subscriptions").json()[0]
        assert refreshed_subscription["rules"]["preferred_groups"] == ["Group-B"]
