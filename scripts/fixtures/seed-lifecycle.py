import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    database_path = Path(sys.argv[1])
    feed_id = sys.argv[2]
    subscription_id = sys.argv[3]
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    info_hash = "0123456789abcdef0123456789abcdef01234567"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO feed_entries (
                id, feed_id, source_guid, guid_hash, identity_strength,
                title_raw, title_normalized, published_at, link_redacted,
                torrent_reference_ciphertext, release_status, release_error_code,
                first_seen_at
            ) VALUES (
                'acceptance-entry', ?, 'acceptance-entry', ?, 'strong',
                '[Acceptance] Acceptance Anime - 01',
                '[Acceptance] Acceptance Anime - 01', ?, NULL, NULL,
                'identified', NULL, ?
            )
            """,
            (feed_id, "a" * 64, now, now),
        )
        connection.execute(
            """
            INSERT INTO release_releases (
                id, identity_kind, identity_value, btih, btmh,
                automation_eligible, first_seen_at
            ) VALUES ('acceptance-release', 'btih', ?, ?, NULL, 1, ?)
            """,
            (info_hash, info_hash, now),
        )
        connection.execute(
            """
            INSERT INTO release_sources (id, release_id, feed_entry_id, observed_at)
            VALUES ('acceptance-source', 'acceptance-release', 'acceptance-entry', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO match_attempts (
                id, release_id, feed_entry_id, parser_version, source_title,
                release_group, series_title, series_key, season, episode_start,
                episode_end, episode_key, resolution, video_codec,
                subtitle_language, revision, content_kind, confidence,
                reason_code, parsed_at
            ) VALUES (
                'acceptance-attempt', 'acceptance-release', 'acceptance-entry',
                'acceptance', '[Acceptance] Acceptance Anime - 01',
                'Acceptance', 'Acceptance Anime', 'acceptanceanime', 1, '9001',
                NULL, '9001', '1080p', 'AVC', 'zh-Hans', 1, 'episode', 'high',
                'acceptance_fixture', ?
            )
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO match_candidates (
                id, release_id, attempt_id, supersedes_candidate_id,
                superseded_by_candidate_id, superseded_at, source_title,
                series_title, series_key, season, episode_start, episode_end,
                episode_key, release_group, resolution, video_codec,
                subtitle_language, revision, content_kind, confidence,
                recognition_eligible, first_seen_at
            ) VALUES (
                'acceptance-candidate', 'acceptance-release', 'acceptance-attempt',
                NULL, NULL, NULL, '[Acceptance] Acceptance Anime - 01',
                'Acceptance Anime', 'acceptanceanime', 1, '9001', NULL, '9001',
                'Acceptance', '1080p', 'AVC', 'zh-Hans', 1, 'episode', 'high', 1, ?
            )
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO select_episode_slots (
                id, subscription_id, anime_title, episode_key, state,
                fallback_deadline, best_candidate_id, selected_decision_id,
                version, created_at, updated_at
            ) VALUES (
                'acceptance-slot', ?, 'Acceptance Anime', '9001', 'decided', NULL,
                'acceptance-candidate', 'acceptance-decision', 1, ?, ?
            )
            """,
            (subscription_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO select_decisions (
                id, slot_id, subscription_id, episode_key, candidate_id,
                release_id, kind, reason, rules_snapshot, candidate_snapshot,
                created_at
            ) VALUES (
                'acceptance-decision', 'acceptance-slot', ?, '9001',
                'acceptance-candidate', 'acceptance-release', 'selected_preferred',
                '{}', '{}', '{}', ?
            )
            """,
            (subscription_id, now),
        )
        task_columns = {row[1] for row in connection.execute("PRAGMA table_info(download_tasks)")}
        origin_column = "origin_kind," if "origin_kind" in task_columns else ""
        origin_value = "'selection_decision'," if "origin_kind" in task_columns else ""
        connection.execute(
            f"""
            INSERT INTO download_tasks (
                id, {origin_column} decision_id, release_id, subscription_id, info_hash,
                external_id, adapter, idempotency_key, state,
                requested_save_path, actual_save_path, category, tags, progress,
                stale, observed_once, cancellation_requested,
                supersedes_decision_id, superseded_by_decision_id, superseded_at,
                error_code, attempt_count, next_retry_at, last_observed_at,
                operation_started_at, version, created_at, updated_at
            ) VALUES (
                'acceptance-task', {origin_value} 'acceptance-decision', 'acceptance-release', ?, ?,
                ?, 'qbittorrent', 'acceptance-decision:qbittorrent', 'completed',
                NULL, NULL, NULL, '[]', 1.0, 0, 1, 0,
                NULL, NULL, NULL, NULL, 1, NULL, ?, NULL, 1, ?, ?
            )
            """,
            (subscription_id, info_hash, info_hash, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO runtime_scheduled_jobs (
                id, job_kind, dedupe_key, due_at, payload, payload_version,
                attempt, lease_owner, lease_until, last_error_code,
                created_at, updated_at
            ) VALUES (
                'acceptance-job', 'acceptance.fixture', 'acceptance.lifecycle',
                '2099-01-01T00:00:00Z', '{}', 1, 0, NULL, NULL, NULL, ?, ?
            )
            """,
            (now, now),
        )
        connection.commit()


if __name__ == "__main__":
    main()
