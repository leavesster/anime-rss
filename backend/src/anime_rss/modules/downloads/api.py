from dataclasses import dataclass
from datetime import datetime
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.downloads.domain import (
    DownloadCycleResult,
    Downloader,
    DownloaderCompatibility,
    DownloaderConnection,
    DownloaderError,
    DownloadOriginKind,
    DownloadState,
)
from anime_rss.modules.downloads.persistence import DownloaderConfigRecord, DownloadTaskRecord
from anime_rss.modules.downloads.ports import ReleaseSources, SubscriptionQueries
from anime_rss.modules.downloads.worker import DownloadWorker
from anime_rss.modules.system.api import SecretCipher

_CONFIG_ID = "qbittorrent"


@dataclass(frozen=True, slots=True)
class DownloadConfig:
    adapter: str
    base_url_redacted: str
    username: str
    default_save_path: str | None
    default_category: str | None
    default_tags: list[str]
    password_configured: bool
    version: int
    last_tested_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class DownloadTask:
    id: str
    origin_kind: str
    decision_id: str | None
    release_id: str
    subscription_id: str | None
    info_hash: str
    state: str
    requested_save_path: str | None
    actual_save_path: str | None
    category: str | None
    tags: list[str]
    progress: float
    stale: bool
    missing_observation_count: int
    error_code: str | None
    attempt_count: int
    next_retry_at: datetime | None
    last_observed_at: datetime | None
    supersedes_decision_id: str | None
    superseded_by_decision_id: str | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime
    display_name: str | None = None


class DownloadConfigNotFoundError(LookupError):
    pass


class DownloadTaskNotFoundError(LookupError):
    pass


class DownloadReleaseNotFoundError(LookupError):
    pass


class DownloadSourceUnavailableError(RuntimeError):
    pass


class DownloadService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        cipher: SecretCipher,
        downloader: Downloader,
        releases: ReleaseSources,
        subscriptions: SubscriptionQueries,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._downloader = downloader
        self._releases = releases
        self._subscriptions = subscriptions
        self._clock = clock
        self._worker = DownloadWorker(
            session_factory,
            downloader,
            releases,
            self._connection,
            self._mark_config_result,
            clock=clock,
        )

    def get_config(self) -> DownloadConfig | None:
        with self._session_factory() as session:
            record = session.get(DownloaderConfigRecord, _CONFIG_ID)
            return self._to_config(record) if record is not None else None

    def configure(
        self,
        *,
        base_url: str,
        username: str,
        password: str | None,
        default_save_path: str | None = None,
        default_category: str | None = None,
        default_tags: list[str] | None = None,
        expected_version: int | None = None,
    ) -> DownloadConfig:
        endpoint = self._validate_endpoint(base_url)
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("username is required")
        clean_save_path = self._clean_optional(default_save_path, maximum=1024)
        clean_category = self._clean_optional(default_category, maximum=120)
        clean_tags = self._clean_tags(default_tags or [])
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(DownloaderConfigRecord, _CONFIG_ID)
            if record is None:
                if expected_version not in {None, 0}:
                    raise ValueError("download config version conflict")
                if not password:
                    raise ValueError("password is required")
                record = DownloaderConfigRecord(
                    id=_CONFIG_ID,
                    adapter="qbittorrent",
                    base_url_redacted=self._redact_endpoint(endpoint),
                    base_url_ciphertext=self._encrypt_config("base-url", endpoint),
                    username_ciphertext=self._encrypt_config("username", clean_username),
                    password_ciphertext=self._encrypt_config("password", password),
                    default_save_path=clean_save_path,
                    default_category=clean_category,
                    default_tags=clean_tags,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if expected_version is not None and record.version != expected_version:
                    raise ValueError("download config version conflict")
                record.base_url_redacted = self._redact_endpoint(endpoint)
                record.base_url_ciphertext = self._encrypt_config("base-url", endpoint)
                record.username_ciphertext = self._encrypt_config("username", clean_username)
                if password:
                    record.password_ciphertext = self._encrypt_config("password", password)
                record.default_save_path = clean_save_path
                record.default_category = clean_category
                record.default_tags = clean_tags
                record.version += 1
                record.updated_at = now
                record.last_error_code = None
            session.execute(
                update(DownloadTaskRecord)
                .where(
                    DownloadTaskRecord.state == DownloadState.FAILED.value,
                    DownloadTaskRecord.error_code.in_(
                        ["authentication_failed", "connection_failed", "config_missing"]
                    ),
                )
                .values(
                    state=DownloadState.RETRYING.value,
                    next_retry_at=now,
                    error_code=None,
                    updated_at=now,
                )
            )
            record_event(
                session,
                event_type="download.configured",
                entity_type="download_config",
                entity_id=_CONFIG_ID,
                payload={"endpoint": record.base_url_redacted, "version": record.version},
            )
        return self._to_config(record)

    def test_connection(self) -> DownloaderCompatibility:
        connection = self._connection()
        now = self._clock()
        try:
            version = self._downloader.test(connection)
        except DownloaderError as error:
            self._mark_config_result(now=now, error_code=error.code)
            raise
        self._mark_config_result(now=now, error_code=None)
        return version

    def handle_download_requested(self, event: IntegrationEvent) -> None:
        if event.name != "DownloadRequested.v1" or event.version != 1:
            return
        decision_id = event.payload.get("decision_id")
        release_id = event.payload.get("release_id")
        subscription_id = event.payload.get("subscription_id")
        supersedes = event.payload.get("supersedes_decision_id")
        if not all(isinstance(value, str) for value in (decision_id, release_id, subscription_id)):
            return
        if supersedes is not None and not isinstance(supersedes, str):
            return
        self.plan_download(
            decision_id=cast(str, decision_id),
            release_id=cast(str, release_id),
            subscription_id=cast(str, subscription_id),
            supersedes_decision_id=supersedes,
        )

    def handle_cancellation_requested(self, event: IntegrationEvent) -> None:
        if event.name != "DownloadCancellationRequested.v1" or event.version != 1:
            return
        decision_id = event.payload.get("decision_id")
        replacement_decision_id = event.payload.get("replacement_decision_id")
        if not isinstance(decision_id, str) or not isinstance(replacement_decision_id, str):
            return
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.scalar(
                select(DownloadTaskRecord).where(DownloadTaskRecord.decision_id == decision_id)
            )
            if task is None:
                raise RuntimeError("replacement source download task is not planned")
            task.cancellation_requested = True
            task.superseded_by_decision_id = replacement_decision_id
            task.next_retry_at = now
            task.updated_at = now
            task.version += 1

    def plan_download(
        self,
        *,
        decision_id: str,
        release_id: str,
        subscription_id: str,
        supersedes_decision_id: str | None = None,
    ) -> DownloadTask:
        source = self._releases.get_download_source(release_id)
        if source is None:
            raise RuntimeError("selected release has no automation-eligible download source")
        subscription = self._subscriptions.get_subscription(subscription_id)
        config = self.get_config()
        now = self._clock()
        task_id = new_id()
        idempotency_key = f"download-request:{decision_id}:{release_id}:1"
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[object],
                session.execute(
                    insert(DownloadTaskRecord)
                    .values(
                        id=task_id,
                        origin_kind=DownloadOriginKind.SELECTION_DECISION.value,
                        decision_id=decision_id,
                        release_id=release_id,
                        subscription_id=subscription_id,
                        info_hash=source.info_hash,
                        adapter="qbittorrent",
                        idempotency_key=idempotency_key,
                        state=DownloadState.PLANNED.value,
                        requested_save_path=(
                            subscription.save_path
                            if subscription.save_path is not None
                            else config.default_save_path
                            if config
                            else None
                        ),
                        category=config.default_category if config else None,
                        tags=config.default_tags if config else [],
                        progress=0.0,
                        stale=False,
                        observed_once=False,
                        missing_observation_count=0,
                        cancellation_requested=False,
                        supersedes_decision_id=supersedes_decision_id,
                        attempt_count=0,
                        next_retry_at=now,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["decision_id"])
                ),
            )
            if not result.rowcount:
                existing = session.scalar(
                    select(DownloadTaskRecord).where(DownloadTaskRecord.decision_id == decision_id)
                )
                if existing is None:
                    raise RuntimeError("download task conflict could not be resolved")
                task_id = existing.id
            else:
                record_event(
                    session,
                    event_type="download.planned",
                    entity_type="download_task",
                    entity_id=task_id,
                    payload={"decision_id": decision_id, "info_hash": source.info_hash},
                )
        return self.get_task(task_id)

    def submit_release_manually(self, release_id: str) -> DownloadTask:
        if not self._releases.has_release(release_id):
            raise DownloadReleaseNotFoundError(release_id)
        config = self.get_config()
        if config is None:
            raise DownloadConfigNotFoundError(_CONFIG_ID)
        source = self._releases.get_download_source(release_id)
        if source is None:
            raise DownloadSourceUnavailableError(
                "release has no qBittorrent-compatible BTIH download source"
            )
        now = self._clock()
        task_id = new_id()
        idempotency_key = f"manual-release:{release_id}:1"
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(DownloadTaskRecord)
                .where(DownloadTaskRecord.release_id == release_id)
                .order_by(DownloadTaskRecord.created_at, DownloadTaskRecord.id)
                .limit(1)
            )
            if existing is not None:
                task_id = existing.id
            else:
                result = cast(
                    CursorResult[object],
                    session.execute(
                        insert(DownloadTaskRecord)
                        .values(
                            id=task_id,
                            origin_kind=DownloadOriginKind.MANUAL_RELEASE.value,
                            decision_id=None,
                            release_id=release_id,
                            subscription_id=None,
                            info_hash=source.info_hash,
                            adapter="qbittorrent",
                            idempotency_key=idempotency_key,
                            state=DownloadState.PLANNED.value,
                            requested_save_path=(config.default_save_path if config else None),
                            category=config.default_category if config else None,
                            tags=config.default_tags if config else [],
                            progress=0.0,
                            stale=False,
                            observed_once=False,
                            missing_observation_count=0,
                            cancellation_requested=False,
                            attempt_count=0,
                            next_retry_at=now,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["idempotency_key"])
                    ),
                )
                if not result.rowcount:
                    existing = session.scalar(
                        select(DownloadTaskRecord).where(
                            DownloadTaskRecord.idempotency_key == idempotency_key
                        )
                    )
                    if existing is None:
                        raise RuntimeError("manual download task conflict could not be resolved")
                    task_id = existing.id
                else:
                    record_event(
                        session,
                        event_type="download.manual_planned",
                        entity_type="download_task",
                        entity_id=task_id,
                        payload={"release_id": release_id, "info_hash": source.info_hash},
                    )
        return self.get_task(task_id)

    def list_tasks(self, *, limit: int = 200) -> list[DownloadTask]:
        with self._session_factory() as session:
            records = session.scalars(
                select(DownloadTaskRecord)
                .order_by(DownloadTaskRecord.updated_at.desc(), DownloadTaskRecord.id)
                .limit(limit)
            ).all()
            references = self._releases.get_references({record.release_id for record in records})
            tasks: list[DownloadTask] = []
            for record in records:
                reference = references.get(record.release_id)
                tasks.append(
                    self._to_task(
                        record,
                        display_name=reference.display_name if reference is not None else None,
                    )
                )
            return tasks

    def retained_release_ids(self) -> set[str]:
        with self._session_factory() as session:
            return set(session.scalars(select(DownloadTaskRecord.release_id).distinct()))

    def get_task(self, task_id: str) -> DownloadTask:
        with self._session_factory() as session:
            record = session.get(DownloadTaskRecord, task_id)
            if record is None:
                raise DownloadTaskNotFoundError(task_id)
            reference = self._releases.get_references({record.release_id}).get(record.release_id)
            return self._to_task(
                record, display_name=reference.display_name if reference is not None else None
            )

    def retry_task(self, task_id: str) -> DownloadTask:
        now = self._clock()
        with self._session_factory.begin() as session:
            task = session.get(DownloadTaskRecord, task_id)
            if task is None:
                raise DownloadTaskNotFoundError(task_id)
            if task.state not in {
                DownloadState.FAILED.value,
                DownloadState.EXTERNALLY_REMOVED.value,
                DownloadState.SUBMITTED.value,
            }:
                raise ValueError("task is not retryable")
            task.state = DownloadState.RETRYING.value
            task.stale = False
            task.observed_once = False
            task.missing_observation_count = 0
            task.error_code = None
            task.next_retry_at = now
            task.operation_started_at = None
            task.cancellation_requested = bool(
                task.superseded_by_decision_id and task.superseded_at is None
            )
            task.updated_at = now
            task.version += 1
            record_event(
                session,
                event_type="download.retry_requested",
                entity_type="download_task",
                entity_id=task.id,
                payload={"previous_attempts": task.attempt_count},
            )
        return self.get_task(task_id)

    def process_cycle(self, *, limit: int = 100) -> DownloadCycleResult:
        if self.get_config() is None:
            return DownloadCycleResult(0, 0, 0)
        return self._worker.process_cycle(limit=limit)

    def recover_inflight(self, *, force: bool = False) -> int:
        return self._worker.recover_inflight(force=force)

    def reconcile(self, *, limit: int = 100) -> int:
        if self.get_config() is None:
            return 0
        return self._worker.reconcile(limit=limit)

    def _connection(self) -> DownloaderConnection:
        with self._session_factory() as session:
            record = session.get(DownloaderConfigRecord, _CONFIG_ID)
            if record is None:
                raise DownloadConfigNotFoundError(_CONFIG_ID)
            return DownloaderConnection(
                base_url=self._decrypt_config("base-url", record.base_url_ciphertext),
                username=self._decrypt_config("username", record.username_ciphertext),
                password=self._decrypt_config("password", record.password_ciphertext),
            )

    def _mark_config_result(
        self, *, now: datetime, error_code: str | None, tested: bool = True
    ) -> None:
        with self._session_factory.begin() as session:
            record = session.get(DownloaderConfigRecord, _CONFIG_ID)
            if record is None:
                return
            if tested:
                record.last_tested_at = now
            if error_code is None:
                record.last_success_at = now
            record.last_error_code = error_code
            record.updated_at = now

    def _encrypt_config(self, field: str, value: str) -> bytes:
        return self._cipher.encrypt(value.encode(), purpose=f"download-config:{field}")

    def _decrypt_config(self, field: str, value: bytes) -> str:
        return self._cipher.decrypt(value, purpose=f"download-config:{field}").decode()

    def _to_config(self, record: DownloaderConfigRecord) -> DownloadConfig:
        return DownloadConfig(
            adapter=record.adapter,
            base_url_redacted=record.base_url_redacted,
            username=self._decrypt_config("username", record.username_ciphertext),
            default_save_path=record.default_save_path,
            default_category=record.default_category,
            default_tags=list(record.default_tags),
            password_configured=bool(record.password_ciphertext),
            version=record.version,
            last_tested_at=record.last_tested_at,
            last_success_at=record.last_success_at,
            last_error_code=record.last_error_code,
        )

    @staticmethod
    def _to_task(record: DownloadTaskRecord, *, display_name: str | None = None) -> DownloadTask:
        return DownloadTask(
            id=record.id,
            origin_kind=record.origin_kind,
            decision_id=record.decision_id,
            release_id=record.release_id,
            subscription_id=record.subscription_id,
            info_hash=record.info_hash,
            state=record.state,
            requested_save_path=record.requested_save_path,
            actual_save_path=record.actual_save_path,
            category=record.category,
            tags=list(record.tags),
            progress=record.progress,
            stale=record.stale,
            missing_observation_count=record.missing_observation_count,
            error_code=record.error_code,
            attempt_count=record.attempt_count,
            next_retry_at=record.next_retry_at,
            last_observed_at=record.last_observed_at,
            supersedes_decision_id=record.supersedes_decision_id,
            superseded_by_decision_id=record.superseded_by_decision_id,
            superseded_at=record.superseded_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            display_name=display_name,
        )

    @staticmethod
    def _validate_endpoint(value: str) -> str:
        endpoint = value.strip().rstrip("/")
        parts = urlsplit(endpoint)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("qBittorrent URL must use http or https")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("qBittorrent URL must not contain credentials, query, or fragment")
        return endpoint

    @staticmethod
    def _redact_endpoint(value: str) -> str:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    @staticmethod
    def _clean_optional(value: str | None, *, maximum: int) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned[:maximum] if cleaned else None

    @staticmethod
    def _clean_tags(values: list[str]) -> list[str]:
        return sorted({value.strip()[:80] for value in values if value.strip()})[:20]
