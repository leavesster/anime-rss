from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.downloads.domain import (
    DownloadCycleResult,
    Downloader,
    DownloaderError,
    DownloaderTask,
    DownloadState,
    Submission,
    normalize_qbittorrent_state,
)
from anime_rss.modules.downloads.persistence import DownloadAttemptRecord, DownloadTaskRecord
from anime_rss.modules.downloads.ports import (
    ConfigResultRecorder,
    ConnectionProvider,
    ReleaseSources,
)

_ACTIVE_RECONCILE_STATES = {
    DownloadState.SUBMITTED.value,
    DownloadState.DOWNLOADING.value,
    DownloadState.PAUSED.value,
    DownloadState.COMPLETED.value,
}


class DownloadWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        downloader: Downloader,
        releases: ReleaseSources,
        connection: ConnectionProvider,
        record_config_result: ConfigResultRecorder,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._downloader = downloader
        self._releases = releases
        self._connection = connection
        self._record_config_result = record_config_result
        self._clock = clock

    def process_cycle(self, *, limit: int = 100) -> DownloadCycleResult:
        self.recover_inflight()
        cancellations = self._process_cancellations(limit=limit)
        submissions = self._process_submissions(limit=max(limit - cancellations, 0))
        reconciled = self.reconcile(limit=limit)
        return DownloadCycleResult(cancellations, submissions, reconciled)

    def recover_inflight(self, *, force: bool = False) -> int:
        now = self._clock()
        cutoff = now if force else now - timedelta(minutes=2)
        recovered = 0
        with self._session_factory.begin() as session:
            tasks = session.scalars(
                select(DownloadTaskRecord).where(
                    DownloadTaskRecord.state.in_(
                        [DownloadState.SUBMITTING.value, DownloadState.CANCELING.value]
                    ),
                    DownloadTaskRecord.operation_started_at <= cutoff,
                )
            ).all()
            for task in tasks:
                was_canceling = task.state == DownloadState.CANCELING.value
                task.state = (
                    DownloadState.FAILED.value if was_canceling else DownloadState.RETRYING.value
                )
                task.cancellation_requested = was_canceling
                task.stale = True
                task.error_code = "operation_interrupted"
                task.next_retry_at = now
                task.operation_started_at = None
                task.updated_at = now
                task.version += 1
                attempts = session.scalars(
                    select(DownloadAttemptRecord).where(
                        DownloadAttemptRecord.task_id == task.id,
                        DownloadAttemptRecord.status == "started",
                    )
                ).all()
                for attempt in attempts:
                    attempt.status = "failed"
                    attempt.details = {
                        "error_code": "operation_interrupted",
                        "transient": True,
                    }
                    attempt.finished_at = now
                recovered += 1
        return recovered

    def reconcile(self, *, limit: int = 100) -> int:
        with self._session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(DownloadTaskRecord.id)
                    .where(DownloadTaskRecord.state.in_(_ACTIVE_RECONCILE_STATES))
                    .order_by(DownloadTaskRecord.last_observed_at, DownloadTaskRecord.created_at)
                    .limit(limit)
                )
            )
        return sum(self._reconcile_one(task_id) for task_id in task_ids)

    def _process_cancellations(self, *, limit: int) -> int:
        with self._session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(DownloadTaskRecord.id)
                    .where(
                        DownloadTaskRecord.cancellation_requested.is_(True),
                        DownloadTaskRecord.next_retry_at <= self._clock(),
                    )
                    .order_by(DownloadTaskRecord.updated_at, DownloadTaskRecord.id)
                    .limit(limit)
                )
            )
        return sum(self._cancel_one(task_id) for task_id in task_ids)

    def _process_submissions(self, *, limit: int) -> int:
        if limit <= 0:
            return 0
        now = self._clock()
        with self._session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(DownloadTaskRecord.id)
                    .where(
                        DownloadTaskRecord.state.in_(
                            [DownloadState.PLANNED.value, DownloadState.RETRYING.value]
                        ),
                        DownloadTaskRecord.next_retry_at <= now,
                    )
                    .order_by(DownloadTaskRecord.next_retry_at, DownloadTaskRecord.created_at)
                    .limit(limit)
                )
            )
        return sum(self._submit_one(task_id) for task_id in task_ids)

    def _submit_one(self, task_id: str) -> bool:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None or task.state not in {
                DownloadState.PLANNED.value,
                DownloadState.RETRYING.value,
            }:
                return False
            if not self._replacement_ready(session, task):
                return False
            task.state = DownloadState.SUBMITTING.value
            task.operation_started_at = now
            task.attempt_count += 1
            task.updated_at = now
            task.version += 1
            attempt_id = self._start_attempt(session, task.id, "submit", now)

        source = self._releases.get_download_source(task.release_id)
        if source is None:
            self._finish_failure(
                task_id,
                attempt_id,
                "release_source_missing",
                transient=False,
                config_error=False,
            )
            return True
        try:
            connection = self._connection()
            observed = self._downloader.lookup(connection, task.info_hash)
            if observed is None:
                self._downloader.submit(
                    connection,
                    Submission(
                        info_hash=task.info_hash,
                        source_kind=source.kind,
                        content=source.content,
                        save_path=task.requested_save_path,
                        category=task.category,
                        tags=tuple(task.tags),
                    ),
                )
                observed = self._downloader.lookup(connection, task.info_hash)
        except DownloaderError as error:
            self._finish_failure(task_id, attempt_id, error.code, transient=error.transient)
            return True

        if observed is None:
            self._finish_submitted_unobserved(task_id, attempt_id)
        else:
            self._finish_observation(task_id, observed, attempt_id=attempt_id)
        self._record_config_result(now=self._clock(), error_code=None, tested=False)
        return True

    def _cancel_one(self, task_id: str) -> bool:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None or not task.cancellation_requested:
                return False
            task.state = DownloadState.CANCELING.value
            task.operation_started_at = now
            task.updated_at = now
            task.version += 1
            attempt_id = self._start_attempt(session, task.id, "cancel", now)
        try:
            observed = self._downloader.cancel_incomplete(self._connection(), task.info_hash)
        except DownloaderError as error:
            self._finish_cancel_failure(task_id, attempt_id, error)
            return True

        now = self._clock()
        with self._session_factory.begin() as session:
            current = session.get(DownloadTaskRecord, task_id)
            attempt = session.get(DownloadAttemptRecord, attempt_id)
            if current is None or attempt is None:
                return True
            if observed is not None and observed.progress >= 1:
                self._apply_observation(current, observed, now)
            else:
                current.state = DownloadState.SUPERSEDED.value
                current.progress = observed.progress if observed else current.progress
            current.cancellation_requested = False
            current.next_retry_at = None
            current.superseded_at = now
            current.error_code = None
            current.stale = False
            current.operation_started_at = None
            current.updated_at = now
            current.version += 1
            attempt.status = "succeeded"
            attempt.finished_at = now
            append_event(
                session,
                name="DownloadTaskChanged.v1",
                payload={"task_id": current.id, "state": current.state},
            )
        self._record_config_result(now=now, error_code=None, tested=False)
        return True

    def _reconcile_one(self, task_id: str) -> bool:
        with self._session_factory() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None or task.state not in _ACTIVE_RECONCILE_STATES:
                return False
            info_hash = task.info_hash
            observed_once = task.observed_once
        try:
            observed = self._downloader.lookup(self._connection(), info_hash)
        except DownloaderError as error:
            now = self._clock()
            with self._session_factory.begin() as session:
                current = session.get(DownloadTaskRecord, task_id)
                if current is not None:
                    current.stale = True
                    current.error_code = error.code
                    current.updated_at = now
                    current.version += 1
            self._record_config_result(now=now, error_code=error.code, tested=False)
            return True

        if observed is None:
            now = self._clock()
            with self._session_factory.begin() as session:
                current = session.get(DownloadTaskRecord, task_id)
                if current is None:
                    return True
                before = current.state
                if observed_once:
                    current.state = DownloadState.EXTERNALLY_REMOVED.value
                    current.error_code = "externally_removed"
                    current.next_retry_at = None
                else:
                    current.stale = True
                    current.error_code = "submission_not_observed"
                current.updated_at = now
                current.version += 1
                if current.state != before:
                    append_event(
                        session,
                        name="DownloadTaskChanged.v1",
                        payload={"task_id": current.id, "state": current.state},
                    )
            self._record_config_result(now=now, error_code=None, tested=False)
            return True

        self._finish_observation(task_id, observed)
        self._record_config_result(now=self._clock(), error_code=None, tested=False)
        return True

    def _finish_observation(
        self,
        task_id: str,
        observed: DownloaderTask,
        *,
        attempt_id: str | None = None,
    ) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None:
                return
            before = (task.state, task.actual_save_path, task.category, tuple(task.tags))
            self._apply_observation(task, observed, now)
            task.operation_started_at = None
            task.next_retry_at = None
            task.version += 1
            if attempt_id is not None:
                attempt = session.get(DownloadAttemptRecord, attempt_id)
                if attempt is not None:
                    attempt.status = "succeeded"
                    attempt.finished_at = now
                    attempt.details = {"existing": task.attempt_count == 1}
            after = (task.state, task.actual_save_path, task.category, tuple(task.tags))
            if before != after:
                append_event(
                    session,
                    name="DownloadTaskChanged.v1",
                    payload={"task_id": task.id, "state": task.state},
                )

    @staticmethod
    def _apply_observation(
        task: DownloadTaskRecord, observed: DownloaderTask, now: datetime
    ) -> None:
        task.external_id = observed.info_hash
        task.state = normalize_qbittorrent_state(observed.state, observed.progress).value
        task.progress = observed.progress
        task.actual_save_path = observed.save_path
        task.category = observed.category
        task.tags = list(observed.tags)
        task.stale = False
        task.observed_once = True
        task.error_code = None
        task.last_observed_at = now
        task.updated_at = now

    def _finish_submitted_unobserved(self, task_id: str, attempt_id: str) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            attempt = session.get(DownloadAttemptRecord, attempt_id)
            if task is None or attempt is None:
                return
            task.state = DownloadState.SUBMITTED.value
            task.stale = True
            task.error_code = "awaiting_observation"
            task.next_retry_at = None
            task.operation_started_at = None
            task.updated_at = now
            task.version += 1
            attempt.status = "succeeded"
            attempt.details = {"observed": False}
            attempt.finished_at = now

    def _finish_failure(
        self,
        task_id: str,
        attempt_id: str,
        code: str,
        *,
        transient: bool,
        config_error: bool = True,
    ) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            attempt = session.get(DownloadAttemptRecord, attempt_id)
            if task is None or attempt is None:
                return
            task.state = DownloadState.RETRYING.value if transient else DownloadState.FAILED.value
            task.stale = transient
            task.error_code = code
            task.next_retry_at = now + self._retry_delay(task.attempt_count) if transient else None
            task.operation_started_at = None
            task.updated_at = now
            task.version += 1
            attempt.status = "failed"
            attempt.details = {"error_code": code, "transient": transient}
            attempt.finished_at = now
        if config_error:
            self._record_config_result(now=now, error_code=code, tested=False)

    def _finish_cancel_failure(self, task_id: str, attempt_id: str, error: DownloaderError) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            attempt = session.get(DownloadAttemptRecord, attempt_id)
            if task is None or attempt is None:
                return
            task.state = DownloadState.FAILED.value
            task.stale = error.transient
            task.error_code = error.code
            task.cancellation_requested = error.transient
            task.next_retry_at = now + timedelta(seconds=30) if error.transient else None
            task.operation_started_at = None
            task.updated_at = now
            task.version += 1
            attempt.status = "failed"
            attempt.details = {"error_code": error.code, "transient": error.transient}
            attempt.finished_at = now
        self._record_config_result(now=now, error_code=error.code, tested=False)

    @staticmethod
    def _replacement_ready(session: Session, task: DownloadTaskRecord) -> bool:
        if task.supersedes_decision_id is None:
            return True
        predecessor = session.scalar(
            select(DownloadTaskRecord).where(
                DownloadTaskRecord.decision_id == task.supersedes_decision_id
            )
        )
        return predecessor is not None and predecessor.superseded_at is not None

    @staticmethod
    def _start_attempt(session: Session, task_id: str, operation: str, now: datetime) -> str:
        attempt_id = new_id()
        session.add(
            DownloadAttemptRecord(
                id=attempt_id,
                task_id=task_id,
                operation=operation,
                status="started",
                details={},
                started_at=now,
            )
        )
        return attempt_id

    @staticmethod
    def _retry_delay(attempt_count: int) -> timedelta:
        seconds = (30, 120, 600, 1800)[min(max(attempt_count - 1, 0), 3)]
        return timedelta(seconds=seconds)
