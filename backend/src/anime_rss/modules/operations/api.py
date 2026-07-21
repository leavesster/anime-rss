from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.operations.persistence import ScheduledJobRecord


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    job_kind: str
    dedupe_key: str
    payload_version: int
    payload: dict[str, Any]
    attempt: int
    lease_until: datetime


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
