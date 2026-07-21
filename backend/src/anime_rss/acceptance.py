from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import quote

SOAK_DAYS: Final = 7
STATE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    key: str
    label: str
    passed: bool
    observed: str
    required: str


@dataclass(frozen=True, slots=True)
class SoakState:
    version: int
    started_at: datetime
    earliest_completion_at: datetime


@dataclass(frozen=True, slots=True)
class SoakStatus:
    phase: str
    state: SoakState | None
    checks: tuple[AcceptanceCheck, ...]
    metrics: dict[str, int]
    observed_at: datetime


class SoakNotReadyError(RuntimeError):
    pass


class AcceptanceProjection:
    """Disposable, read-only cross-module projection for release acceptance."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def preflight(self) -> tuple[AcceptanceCheck, ...]:
        with closing(self._connect()) as connection:
            setup_completed = self._scalar(
                connection,
                "SELECT COUNT(*) FROM sys_instance_settings WHERE setup_completed = 1",
            )
            feed_count = self._scalar(connection, "SELECT COUNT(*) FROM feed_feeds")
            reliable_feeds = self._scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM feed_feeds
                WHERE health = 'healthy'
                  AND consecutive_failures = 0
                  AND last_success_at IS NOT NULL
                """,
            )
            bangumi_subscriptions = self._scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM sub_subscriptions AS subscription
                JOIN catalog_anime AS anime ON anime.id = subscription.anime_id
                WHERE subscription.state = 'following'
                  AND anime.source = 'bangumi'
                  AND anime.bangumi_id IS NOT NULL
                """,
            )
            downloader_ready = self._scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM download_configs
                WHERE adapter = 'qbittorrent'
                  AND last_success_at IS NOT NULL
                  AND last_error_code IS NULL
                """,
            )
            scheduler_ready = self._scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM runtime_scheduler_state
                WHERE last_success_at IS NOT NULL
                  AND last_error_code IS NULL
                """,
            )

        return (
            AcceptanceCheck(
                key="setup",
                label="Administrator setup",
                passed=setup_completed == 1,
                observed="complete" if setup_completed == 1 else "incomplete",
                required="complete",
            ),
            AcceptanceCheck(
                key="feeds",
                label="Reliable real feeds",
                passed=feed_count >= 2 and reliable_feeds == feed_count,
                observed=f"{reliable_feeds}/{feed_count} healthy",
                required="at least 2, all healthy",
            ),
            AcceptanceCheck(
                key="subscriptions",
                label="Following Bangumi anime",
                passed=bangumi_subscriptions >= 2,
                observed=str(bangumi_subscriptions),
                required="at least 2",
            ),
            AcceptanceCheck(
                key="downloader",
                label="qBittorrent connection",
                passed=downloader_ready == 1,
                observed="connected" if downloader_ready == 1 else "not verified",
                required="verified connection",
            ),
            AcceptanceCheck(
                key="scheduler",
                label="Durable scheduler",
                passed=scheduler_ready == 1,
                observed="healthy" if scheduler_ready == 1 else "not healthy",
                required="healthy",
            ),
        )

    def metrics(self, since: datetime) -> dict[str, int]:
        since_value = _format_datetime(since)
        with closing(self._connect()) as connection:
            return {
                "feed_fetch_successes": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM feed_fetches
                    WHERE started_at >= ? AND status = 'success'
                    """,
                    (since_value,),
                ),
                "feed_fetch_failures": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM feed_fetches
                    WHERE started_at >= ? AND status != 'success'
                    """,
                    (since_value,),
                ),
                "feed_failure_events": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE created_at >= ? AND event_type = 'feed.refresh_failed'
                    """,
                    (since_value,),
                ),
                "new_feed_entries": self._scalar(
                    connection,
                    """
                    SELECT COALESCE(SUM(new_entry_count), 0) FROM feed_fetches
                    WHERE started_at >= ?
                    """,
                    (since_value,),
                ),
                "releases_observed": self._scalar(
                    connection,
                    "SELECT COUNT(DISTINCT release_id) FROM release_sources WHERE observed_at >= ?",
                    (since_value,),
                ),
                "cross_feed_releases": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT source.release_id
                        FROM release_sources AS source
                        JOIN feed_entries AS entry ON entry.id = source.feed_entry_id
                        WHERE source.observed_at >= ?
                        GROUP BY source.release_id
                        HAVING COUNT(DISTINCT entry.feed_id) >= 2
                    )
                    """,
                    (since_value,),
                ),
                "recognition_candidates": self._scalar(
                    connection,
                    "SELECT COUNT(*) FROM match_candidates WHERE first_seen_at >= ?",
                    (since_value,),
                ),
                "manual_mapping_actions": self._scalar(
                    connection,
                    "SELECT COUNT(*) FROM match_manual_actions WHERE created_at >= ?",
                    (since_value,),
                ),
                "selection_decisions": self._scalar(
                    connection,
                    "SELECT COUNT(*) FROM select_decisions WHERE created_at >= ?",
                    (since_value,),
                ),
                "manual_selection_actions": self._scalar(
                    connection,
                    "SELECT COUNT(*) FROM select_manual_actions WHERE created_at >= ?",
                    (since_value,),
                ),
                "download_attempt_failures": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM download_attempts
                    WHERE started_at >= ? AND status = 'failed'
                    """,
                    (since_value,),
                ),
                "job_run_failures": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM runtime_job_runs
                    WHERE started_at >= ? AND status = 'failed'
                    """,
                    (since_value,),
                ),
                "unresolved_download_failures": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM download_tasks
                    WHERE state IN ('failed', 'retrying') OR stale = 1
                    """,
                ),
                "duplicate_download_identities": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT subscription_id, info_hash
                        FROM download_tasks
                        GROUP BY subscription_id, info_hash
                        HAVING COUNT(*) > 1
                    )
                    """,
                ),
                "lost_selected_decisions": self._scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM select_episode_slots AS slot
                    LEFT JOIN select_decisions AS decision
                      ON decision.id = slot.selected_decision_id
                    WHERE slot.selected_decision_id IS NOT NULL AND decision.id IS NULL
                    """,
                ),
                "unfinished_download_attempts": self._scalar(
                    connection,
                    "SELECT COUNT(*) FROM download_attempts WHERE status = 'started'",
                ),
            }

    def _connect(self) -> sqlite3.Connection:
        if not self._database_path.is_file():
            raise FileNotFoundError(f"database not found: {self._database_path}")
        encoded = quote(str(self._database_path.resolve()), safe="/")
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _scalar(
        connection: sqlite3.Connection,
        statement: str,
        parameters: tuple[str, ...] = (),
    ) -> int:
        row = connection.execute(statement, parameters).fetchone()
        return int(row[0]) if row is not None else 0


class SoakAcceptanceService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._state_path = data_dir / "acceptance" / "real-feed-soak.json"
        self._projection = AcceptanceProjection(data_dir / "anime-rss.sqlite3")

    def preflight(self) -> tuple[AcceptanceCheck, ...]:
        return self._projection.preflight()

    def start(self, *, now: datetime | None = None) -> SoakState:
        if self._state_path.exists():
            return self._load_state()
        checks = self.preflight()
        if not all(check.passed for check in checks):
            raise SoakNotReadyError("real-feed soak preflight is not satisfied")
        started_at = _as_utc(now or datetime.now(UTC))
        state = SoakState(
            version=STATE_VERSION,
            started_at=started_at,
            earliest_completion_at=started_at + timedelta(days=SOAK_DAYS),
        )
        self._write_state(state)
        return state

    def status(self, *, now: datetime | None = None) -> SoakStatus:
        observed_at = _as_utc(now or datetime.now(UTC))
        checks = self.preflight()
        if not self._state_path.exists():
            return SoakStatus(
                phase="not_started",
                state=None,
                checks=checks,
                metrics={},
                observed_at=observed_at,
            )
        state = self._load_state()
        phase = "duration_met" if observed_at >= state.earliest_completion_at else "running"
        return SoakStatus(
            phase=phase,
            state=state,
            checks=checks,
            metrics=self._projection.metrics(state.started_at),
            observed_at=observed_at,
        )

    def render_report(self, *, now: datetime | None = None) -> str:
        status = self.status(now=now)
        lines = ["# Real-feed Soak Evidence", ""]
        lines.extend(_report_summary(status))
        lines.extend(
            [
                "",
                "## Preconditions",
                "",
                "| Check | Result | Observed | Required |",
                "| --- | --- | --- | --- |",
            ]
        )
        for check in status.checks:
            result = "pass" if check.passed else "pending"
            lines.append(f"| {check.label} | {result} | {check.observed} | {check.required} |")
        if status.state is not None:
            lines.extend(["", "## Window Metrics", ""])
            lines.extend(f"- `{key}`: {value}" for key, value in status.metrics.items())
        lines.extend(
            [
                "",
                "## Required Manual Review",
                "",
                "- Review recognized anime and episode mappings; counts cannot prove "
                "semantic correctness.",
                "- Review any manual mapping or selection action and its later matching behavior.",
                "- Confirm qBittorrent contains no duplicate torrent created outside the "
                "recorded task identity.",
                "- Do not mark acceptance complete until the phase is `duration_met` and "
                "all twelve design criteria have evidence.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _load_state(self) -> SoakState:
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        if payload.get("version") != STATE_VERSION:
            raise ValueError("unsupported real-feed soak state version")
        return SoakState(
            version=payload["version"],
            started_at=_parse_datetime(payload["started_at"]),
            earliest_completion_at=_parse_datetime(payload["earliest_completion_at"]),
        )

    def _write_state(self, state: SoakState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": state.version,
                    "started_at": _format_datetime(state.started_at),
                    "earliest_completion_at": _format_datetime(state.earliest_completion_at),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._state_path)


def render_preflight(checks: tuple[AcceptanceCheck, ...]) -> str:
    lines: list[str] = []
    for check in checks:
        result = "PASS" if check.passed else "PENDING"
        lines.append(f"{result:7} {check.label}: {check.observed} (required: {check.required})")
    return "\n".join(lines)


def render_status(status: SoakStatus) -> str:
    lines = [f"Phase: {status.phase}", render_preflight(status.checks)]
    if status.state is not None:
        lines.extend(
            [
                f"Started: {_format_datetime(status.state.started_at)}",
                f"Earliest completion: {_format_datetime(status.state.earliest_completion_at)}",
            ]
        )
        lines.extend(f"{key}: {value}" for key, value in status.metrics.items())
    return "\n".join(lines)


def _report_summary(status: SoakStatus) -> list[str]:
    lines = [f"- Phase: `{status.phase}`", f"- Observed: `{_format_datetime(status.observed_at)}`"]
    if status.state is None:
        lines.append("- Started: not started")
    else:
        lines.extend(
            [
                f"- Started: `{_format_datetime(status.state.started_at)}`",
                f"- Earliest completion: `{_format_datetime(status.state.earliest_completion_at)}`",
            ]
        )
    return lines


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("acceptance timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
