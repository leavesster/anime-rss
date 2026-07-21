from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.operations.persistence import (
    JobRunRecord,
    ScheduledJobRecord,
    SchedulerStateRecord,
)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    job_kind: str
    dedupe_key: str
    payload_version: int
    payload: dict[str, Any]
    attempt: int
    lease_until: datetime


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    id: str
    job_kind: str
    dedupe_key: str
    due_at: datetime
    attempt: int
    lease_owner: str | None
    lease_until: datetime | None
    last_error_code: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JobRun:
    id: str
    job_id: str
    job_kind: str
    dedupe_key: str
    worker_id: str
    attempt: int
    status: str
    error_code: str | None
    details: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class SchedulerState:
    state: str
    worker_id: str
    last_cycle_started_at: datetime | None
    last_cycle_finished_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    next_wake_at: datetime | None
    updated_at: datetime


class JobService:
    def __init__(self, session_factory: sessionmaker[Session], *, clock: Clock = utc_now) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def ensure_job(
        self,
        *,
        job_kind: str,
        dedupe_key: str,
        due_at: datetime,
        payload: dict[str, Any] | None = None,
        payload_version: int = 1,
    ) -> str:
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(ScheduledJobRecord).where(
                    ScheduledJobRecord.job_kind == job_kind,
                    ScheduledJobRecord.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                if due_at < existing.due_at:
                    existing.due_at = due_at
                    existing.updated_at = self._clock()
                return existing.id
            record = ScheduledJobRecord(
                id=new_id(),
                job_kind=job_kind,
                dedupe_key=dedupe_key,
                due_at=due_at,
                payload=payload or {},
                payload_version=payload_version,
                created_at=self._clock(),
                updated_at=self._clock(),
            )
            session.add(record)
            return record.id

    def synchronize_job(
        self,
        *,
        job_kind: str,
        dedupe_key: str,
        due_at: datetime,
        payload: dict[str, Any] | None = None,
        payload_version: int = 1,
        authoritative_due_at: bool = False,
    ) -> str:
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(ScheduledJobRecord).where(
                    ScheduledJobRecord.job_kind == job_kind,
                    ScheduledJobRecord.dedupe_key == dedupe_key,
                )
            )
            if record is None:
                record = ScheduledJobRecord(
                    id=new_id(),
                    job_kind=job_kind,
                    dedupe_key=dedupe_key,
                    due_at=due_at,
                    payload=payload or {},
                    payload_version=payload_version,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            elif record.lease_owner is None:
                if authoritative_due_at:
                    record.due_at = due_at
                record.payload = payload or {}
                record.payload_version = payload_version
                record.updated_at = now
            return record.id

    def claim_due(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        limit: int = 10,
    ) -> list[ClaimedJob]:
        now = self._clock()
        lease_until = now + timedelta(seconds=lease_seconds)
        claimed: list[ClaimedJob] = []
        with self._session_factory.begin() as session:
            candidate_ids = list(
                session.scalars(
                    select(ScheduledJobRecord.id)
                    .where(
                        ScheduledJobRecord.due_at <= now,
                        or_(
                            ScheduledJobRecord.lease_until.is_(None),
                            ScheduledJobRecord.lease_until < now,
                        ),
                    )
                    .order_by(ScheduledJobRecord.due_at, ScheduledJobRecord.id)
                    .limit(limit)
                )
            )
            for job_id in candidate_ids:
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(ScheduledJobRecord)
                        .where(
                            ScheduledJobRecord.id == job_id,
                            or_(
                                ScheduledJobRecord.lease_until.is_(None),
                                ScheduledJobRecord.lease_until < now,
                            ),
                        )
                        .values(
                            lease_owner=worker_id,
                            lease_until=lease_until,
                            attempt=ScheduledJobRecord.attempt + 1,
                            updated_at=now,
                        )
                    ),
                )
                if result.rowcount != 1:
                    continue
                record = session.get(ScheduledJobRecord, job_id)
                if record is None:
                    continue
                claimed.append(
                    ClaimedJob(
                        id=record.id,
                        job_kind=record.job_kind,
                        dedupe_key=record.dedupe_key,
                        payload_version=record.payload_version,
                        payload=record.payload,
                        attempt=record.attempt,
                        lease_until=lease_until,
                    )
                )
        return claimed

    def complete(self, job_id: str, *, worker_id: str) -> bool:
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(ScheduledJobRecord).where(
                        ScheduledJobRecord.id == job_id,
                        ScheduledJobRecord.lease_owner == worker_id,
                    )
                ),
            )
            return result.rowcount == 1

    def reschedule(
        self,
        job_id: str,
        *,
        worker_id: str,
        due_at: datetime,
        error_code: str | None = None,
    ) -> bool:
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(ScheduledJobRecord)
                    .where(
                        ScheduledJobRecord.id == job_id,
                        ScheduledJobRecord.lease_owner == worker_id,
                    )
                    .values(
                        due_at=due_at,
                        lease_owner=None,
                        lease_until=None,
                        last_error_code=error_code,
                        updated_at=self._clock(),
                    )
                ),
            )
            return result.rowcount == 1

    def start_run(self, job: ClaimedJob, *, worker_id: str) -> str:
        run_id = new_id()
        with self._session_factory.begin() as session:
            session.add(
                JobRunRecord(
                    id=run_id,
                    job_id=job.id,
                    job_kind=job.job_kind,
                    dedupe_key=job.dedupe_key,
                    worker_id=worker_id,
                    attempt=job.attempt,
                    status="running",
                    started_at=self._clock(),
                )
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(JobRunRecord)
                .where(JobRunRecord.id == run_id, JobRunRecord.status == "running")
                .values(
                    status=status,
                    error_code=error_code,
                    details=details or {},
                    finished_at=self._clock(),
                )
            )

    def recover_expired_runs(self) -> int:
        now = self._clock()
        with self._session_factory.begin() as session:
            expired_job_ids = select(ScheduledJobRecord.id).where(
                ScheduledJobRecord.lease_until.is_not(None),
                ScheduledJobRecord.lease_until < now,
            )
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(JobRunRecord)
                    .where(
                        JobRunRecord.status == "running", JobRunRecord.job_id.in_(expired_job_ids)
                    )
                    .values(
                        status="recovered",
                        error_code="lease_expired",
                        finished_at=now,
                    )
                ),
            )
            return result.rowcount

    def update_scheduler_state(
        self,
        *,
        worker_id: str,
        state: str,
        cycle_started_at: datetime | None = None,
        cycle_finished_at: datetime | None = None,
        success: bool = False,
        error_code: str | None = None,
        next_wake_at: datetime | None = None,
    ) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(SchedulerStateRecord, "scheduler")
            if record is None:
                record = SchedulerStateRecord(
                    id="scheduler", worker_id=worker_id, state=state, updated_at=now
                )
                session.add(record)
            record.worker_id = worker_id
            record.state = state
            if cycle_started_at is not None:
                record.last_cycle_started_at = cycle_started_at
            if cycle_finished_at is not None:
                record.last_cycle_finished_at = cycle_finished_at
            if success:
                record.last_success_at = now
                record.last_error_code = None
            elif error_code is not None:
                record.last_error_code = error_code
            record.next_wake_at = next_wake_at
            record.updated_at = now

    def get_scheduler_state(self) -> SchedulerState | None:
        with self._session_factory() as session:
            record = session.get(SchedulerStateRecord, "scheduler")
            if record is None:
                return None
            return SchedulerState(
                state=record.state,
                worker_id=record.worker_id,
                last_cycle_started_at=record.last_cycle_started_at,
                last_cycle_finished_at=record.last_cycle_finished_at,
                last_success_at=record.last_success_at,
                last_error_code=record.last_error_code,
                next_wake_at=record.next_wake_at,
                updated_at=record.updated_at,
            )

    def list_jobs(self, *, limit: int = 200) -> list[ScheduledJob]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(ScheduledJobRecord)
                    .order_by(ScheduledJobRecord.due_at, ScheduledJobRecord.id)
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [
                ScheduledJob(
                    id=item.id,
                    job_kind=item.job_kind,
                    dedupe_key=item.dedupe_key,
                    due_at=item.due_at,
                    attempt=item.attempt,
                    lease_owner=item.lease_owner,
                    lease_until=item.lease_until,
                    last_error_code=item.last_error_code,
                    updated_at=item.updated_at,
                )
                for item in records
            ]

    def list_runs(self, *, limit: int = 100) -> list[JobRun]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(JobRunRecord)
                    .order_by(JobRunRecord.started_at.desc(), JobRunRecord.id.desc())
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [
                JobRun(
                    id=item.id,
                    job_id=item.job_id,
                    job_kind=item.job_kind,
                    dedupe_key=item.dedupe_key,
                    worker_id=item.worker_id,
                    attempt=item.attempt,
                    status=item.status,
                    error_code=item.error_code,
                    details=item.details,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                )
                for item in records
            ]

    def prune_run_history(self, *, before: datetime) -> int:
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(JobRunRecord).where(
                        JobRunRecord.started_at < before,
                        JobRunRecord.status != "running",
                    )
                ),
            )
            return result.rowcount
