from datetime import timedelta
from uuid import uuid4

from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.operations.api import JobService
from anime_rss.modules.operations.ports import JobHandler, ScheduleSource


class Scheduler:
    def __init__(
        self,
        jobs: JobService,
        *,
        handlers: dict[str, JobHandler],
        schedule_sources: list[ScheduleSource],
        clock: Clock = utc_now,
        lease_seconds: int = 60,
        worker_id: str | None = None,
    ) -> None:
        self._jobs = jobs
        self._handlers = handlers
        self._schedule_sources = schedule_sources
        self._clock = clock
        self._lease_seconds = lease_seconds
        self.worker_id = worker_id or f"scheduler-{uuid4()}"

    def recover(self) -> int:
        return self._jobs.recover_expired_runs()

    def run_once(self, *, limit: int = 50, next_wake_seconds: float = 5.0) -> int:
        started_at = self._clock()
        self._jobs.update_scheduler_state(
            worker_id=self.worker_id, state="running", cycle_started_at=started_at
        )
        error_code: str | None = None
        processed = 0
        try:
            for source in self._schedule_sources:
                for schedule in source():
                    self._jobs.synchronize_job(
                        job_kind=schedule.job_kind,
                        dedupe_key=schedule.dedupe_key,
                        due_at=schedule.due_at,
                        payload=schedule.payload,
                        payload_version=schedule.payload_version,
                        authoritative_due_at=schedule.authoritative_due_at,
                    )
            claimed = self._jobs.claim_due(
                worker_id=self.worker_id, lease_seconds=self._lease_seconds, limit=limit
            )
            for job in claimed:
                processed += 1
                run_id = self._jobs.start_run(job, worker_id=self.worker_id)
                handler = self._handlers.get(job.job_kind)
                if handler is None:
                    error = "unknown_job_kind"
                    self._jobs.finish_run(run_id, status="failed", error_code=error)
                    self._jobs.reschedule(
                        job.id,
                        worker_id=self.worker_id,
                        due_at=self._clock() + timedelta(minutes=5),
                        error_code=error,
                    )
                    continue
                try:
                    result = handler(job)
                except Exception as exc:
                    error = type(exc).__name__[:80]
                    self._jobs.finish_run(run_id, status="failed", error_code=error)
                    self._jobs.reschedule(
                        job.id,
                        worker_id=self.worker_id,
                        due_at=self._clock()
                        + timedelta(seconds=min(300, 2 ** min(job.attempt, 8))),
                        error_code=error,
                    )
                    continue
                self._jobs.finish_run(run_id, status="success", details=result.details)
                if result.next_due_at is None:
                    self._jobs.complete(job.id, worker_id=self.worker_id)
                else:
                    self._jobs.reschedule(
                        job.id, worker_id=self.worker_id, due_at=result.next_due_at
                    )
        except Exception as exc:
            error_code = type(exc).__name__[:80]
            raise
        finally:
            finished_at = self._clock()
            self._jobs.update_scheduler_state(
                worker_id=self.worker_id,
                state="degraded" if error_code else "idle",
                cycle_finished_at=finished_at,
                success=error_code is None,
                error_code=error_code,
                next_wake_at=finished_at + timedelta(seconds=next_wake_seconds),
            )
        return processed
