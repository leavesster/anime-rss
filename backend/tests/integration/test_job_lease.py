from datetime import UTC, datetime
from pathlib import Path

from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.migrations import run_migrations
from anime_rss.modules.operations.api import JobService


def test_only_one_worker_claims_a_durable_job(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'jobs.sqlite3'}"
    run_migrations(database_url)
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    now = datetime(2026, 7, 21, tzinfo=UTC)
    jobs = JobService(sessions, clock=lambda: now)
    jobs.ensure_job(job_kind="feed.refresh", dedupe_key="feed-1", due_at=now)

    first = jobs.claim_due(worker_id="worker-one")
    second = jobs.claim_due(worker_id="worker-two")

    assert len(first) == 1
    assert second == []
    assert jobs.complete(first[0].id, worker_id="worker-two") is False
    assert jobs.complete(first[0].id, worker_id="worker-one") is True
    engine.dispose()
