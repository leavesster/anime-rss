from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.notifications.adapters import WebhookClient, WebhookError, WebhookMessage
from anime_rss.modules.notifications.persistence import (
    NotificationAttemptRecord,
    NotificationConfigRecord,
    NotificationRecord,
)
from anime_rss.modules.system.api import SecretCipher

_CONFIG_ID = "default"


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    webhook_enabled: bool
    webhook_url_redacted: str | None
    bearer_token_configured: bool
    version: int
    last_tested_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    kind: str
    level: str
    title: str
    message: str
    entity_type: str | None
    entity_id: str | None
    read_at: datetime | None
    delivery_state: str | None
    delivery_error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryCycle:
    delivered: int
    failed: int


class NotificationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        cipher: SecretCipher,
        webhook: WebhookClient,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._webhook = webhook
        self._clock = clock

    def get_config(self) -> NotificationConfig | None:
        with self._session_factory() as session:
            record = session.get(NotificationConfigRecord, _CONFIG_ID)
            return self._to_config(record) if record else None

    def configure(
        self,
        *,
        webhook_enabled: bool,
        webhook_url: str | None,
        bearer_token: str | None,
        expected_version: int | None = None,
    ) -> NotificationConfig:
        clean_url = self._validate_url(webhook_url) if webhook_url else None
        if webhook_enabled and clean_url is None:
            raise ValueError("webhook URL is required when delivery is enabled")
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(NotificationConfigRecord, _CONFIG_ID)
            if record is None:
                record = NotificationConfigRecord(
                    id=_CONFIG_ID,
                    webhook_enabled=webhook_enabled,
                    webhook_url_redacted=self._redact_url(clean_url) if clean_url else None,
                    webhook_url_ciphertext=(
                        self._cipher.encrypt(clean_url.encode(), purpose="notification:webhook:url")
                        if clean_url
                        else None
                    ),
                    bearer_token_ciphertext=(
                        self._cipher.encrypt(
                            bearer_token.encode(), purpose="notification:webhook:bearer"
                        )
                        if bearer_token
                        else None
                    ),
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if expected_version is not None and record.version != expected_version:
                    raise ValueError("notification config version conflict")
                record.webhook_enabled = webhook_enabled
                if clean_url:
                    record.webhook_url_redacted = self._redact_url(clean_url)
                    record.webhook_url_ciphertext = self._cipher.encrypt(
                        clean_url.encode(), purpose="notification:webhook:url"
                    )
                if bearer_token is not None:
                    record.bearer_token_ciphertext = (
                        self._cipher.encrypt(
                            bearer_token.encode(), purpose="notification:webhook:bearer"
                        )
                        if bearer_token
                        else None
                    )
                record.version += 1
                record.updated_at = now
            record_event(
                session,
                event_type="notification.configured",
                entity_type="notification_config",
                entity_id=_CONFIG_ID,
                payload={"webhook_enabled": webhook_enabled},
            )
        configured = self.get_config()
        assert configured is not None
        return configured

    def test_webhook(self) -> None:
        url, bearer = self._connection()
        now = self._clock()
        try:
            self._webhook.deliver(
                url=url,
                bearer_token=bearer,
                message=WebhookMessage(
                    id=f"test-{new_id()}",
                    kind="test",
                    level="info",
                    title="Anime RSS webhook test",
                    message="Webhook delivery is configured correctly.",
                    entity_type=None,
                    entity_id=None,
                    created_at=now.isoformat(),
                ),
            )
        except WebhookError as error:
            self._mark_config_result(now, error.code)
            raise
        self._mark_config_result(now, None)

    def handle_event(self, event: IntegrationEvent) -> None:
        presentation = self._presentation(event)
        if presentation is None:
            return
        kind, level, title, message, entity_type, entity_id = presentation
        now = self._clock()
        notification_id = new_id()
        with self._session_factory.begin() as session:
            statement = (
                insert(NotificationRecord)
                .values(
                    id=notification_id,
                    source_event_id=event.id,
                    kind=kind,
                    level=level,
                    title=title,
                    message=message,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["source_event_id"])
            )
            result = cast(CursorResult[Any], session.execute(statement))
            if not result.rowcount:
                return
            config = session.get(NotificationConfigRecord, _CONFIG_ID)
            if config is not None and config.webhook_enabled:
                session.add(
                    NotificationAttemptRecord(
                        id=new_id(),
                        notification_id=notification_id,
                        channel="webhook",
                        state="pending",
                        next_attempt_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def list_notifications(self, *, limit: int = 100) -> list[Notification]:
        with self._session_factory() as session:
            attempts = {
                item.notification_id: item
                for item in session.scalars(
                    select(NotificationAttemptRecord).order_by(
                        NotificationAttemptRecord.updated_at.desc()
                    )
                )
            }
            records = list(
                session.scalars(
                    select(NotificationRecord)
                    .order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [
                Notification(
                    id=item.id,
                    kind=item.kind,
                    level=item.level,
                    title=item.title,
                    message=item.message,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    read_at=item.read_at,
                    delivery_state=(attempts[item.id].state if item.id in attempts else None),
                    delivery_error_code=(
                        attempts[item.id].error_code if item.id in attempts else None
                    ),
                    created_at=item.created_at,
                )
                for item in records
            ]

    def mark_read(self, notification_id: str) -> Notification:
        with self._session_factory.begin() as session:
            record = session.get(NotificationRecord, notification_id)
            if record is None:
                raise LookupError("notification not found")
            record.read_at = record.read_at or self._clock()
        return next(
            item for item in self.list_notifications(limit=500) if item.id == notification_id
        )

    def process_deliveries(self, *, limit: int = 50) -> DeliveryCycle:
        now = self._clock()
        with self._session_factory.begin() as session:
            session.execute(
                update(NotificationAttemptRecord)
                .where(
                    NotificationAttemptRecord.state == "delivering",
                    NotificationAttemptRecord.started_at < now - timedelta(minutes=5),
                )
                .values(state="retrying", next_attempt_at=now, updated_at=now)
            )
        with self._session_factory() as session:
            attempt_ids = list(
                session.scalars(
                    select(NotificationAttemptRecord.id)
                    .where(
                        NotificationAttemptRecord.state.in_(["pending", "retrying"]),
                        or_(
                            NotificationAttemptRecord.next_attempt_at.is_(None),
                            NotificationAttemptRecord.next_attempt_at <= now,
                        ),
                    )
                    .order_by(
                        NotificationAttemptRecord.next_attempt_at, NotificationAttemptRecord.id
                    )
                    .limit(min(max(limit, 1), 200))
                )
            )
        delivered = 0
        failed = 0
        for attempt_id in attempt_ids:
            if self._deliver(attempt_id):
                delivered += 1
            else:
                failed += 1
        return DeliveryCycle(delivered, failed)

    def _deliver(self, attempt_id: str) -> bool:
        now = self._clock()
        with self._session_factory.begin() as session:
            attempt = session.get(NotificationAttemptRecord, attempt_id)
            if attempt is None or attempt.state not in {"pending", "retrying"}:
                return True
            notification = session.get(NotificationRecord, attempt.notification_id)
            if notification is None:
                session.delete(attempt)
                return True
            attempt.state = "delivering"
            attempt.attempt_count += 1
            attempt.started_at = now
            attempt.updated_at = now
            message = WebhookMessage(
                id=notification.id,
                kind=notification.kind,
                level=notification.level,
                title=notification.title,
                message=notification.message,
                entity_type=notification.entity_type,
                entity_id=notification.entity_id,
                created_at=notification.created_at.isoformat(),
            )
        try:
            url, bearer = self._connection()
            self._webhook.deliver(url=url, bearer_token=bearer, message=message)
        except (WebhookError, ValueError) as error:
            code = error.code if isinstance(error, WebhookError) else "webhook_not_configured"
            transient = isinstance(error, WebhookError) and error.transient
            with self._session_factory.begin() as session:
                attempt = session.get(NotificationAttemptRecord, attempt_id)
                if attempt is not None:
                    attempt.state = (
                        "retrying" if transient and attempt.attempt_count < 8 else "failed"
                    )
                    attempt.error_code = code
                    attempt.next_attempt_at = (
                        self._clock()
                        + timedelta(seconds=min(3600, 2 ** min(attempt.attempt_count, 11)))
                        if attempt.state == "retrying"
                        else None
                    )
                    attempt.updated_at = self._clock()
            self._mark_config_result(self._clock(), code)
            return False
        with self._session_factory.begin() as session:
            attempt = session.get(NotificationAttemptRecord, attempt_id)
            if attempt is not None:
                attempt.state = "delivered"
                attempt.error_code = None
                attempt.next_attempt_at = None
                attempt.delivered_at = self._clock()
                attempt.updated_at = self._clock()
        self._mark_config_result(self._clock(), None)
        return True

    def _connection(self) -> tuple[str, str | None]:
        with self._session_factory() as session:
            config = session.get(NotificationConfigRecord, _CONFIG_ID)
            if (
                config is None
                or not config.webhook_enabled
                or config.webhook_url_ciphertext is None
            ):
                raise ValueError("webhook is not configured")
            url = self._cipher.decrypt(
                config.webhook_url_ciphertext, purpose="notification:webhook:url"
            ).decode()
            bearer = (
                self._cipher.decrypt(
                    config.bearer_token_ciphertext, purpose="notification:webhook:bearer"
                ).decode()
                if config.bearer_token_ciphertext
                else None
            )
            return url, bearer

    def _mark_config_result(self, now: datetime, error_code: str | None) -> None:
        with self._session_factory.begin() as session:
            config = session.get(NotificationConfigRecord, _CONFIG_ID)
            if config is None:
                return
            config.last_tested_at = now
            config.last_error_code = error_code
            if error_code is None:
                config.last_success_at = now
            config.updated_at = now

    def _to_config(self, record: NotificationConfigRecord) -> NotificationConfig:
        return NotificationConfig(
            webhook_enabled=record.webhook_enabled,
            webhook_url_redacted=record.webhook_url_redacted,
            bearer_token_configured=record.bearer_token_ciphertext is not None,
            version=record.version,
            last_tested_at=record.last_tested_at,
            last_success_at=record.last_success_at,
            last_error_code=record.last_error_code,
        )

    @staticmethod
    def _validate_url(value: str) -> str:
        clean = value.strip()
        parts = urlsplit(clean)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("webhook URL must use HTTP or HTTPS")
        return clean

    @staticmethod
    def _redact_url(value: str) -> str:
        parts = urlsplit(value)
        authority = parts.hostname or ""
        if parts.port:
            authority += f":{parts.port}"
        return f"{parts.scheme}://{authority}{parts.path}"

    @staticmethod
    def _presentation(
        event: IntegrationEvent,
    ) -> tuple[str, str, str, str, str | None, str | None] | None:
        payload: dict[str, Any] = event.payload
        entity_id = next(
            (
                payload.get(key)
                for key in (
                    "decision_id",
                    "candidate_id",
                    "release_id",
                    "feed_id",
                    "task_id",
                    "expected_episode_id",
                )
                if isinstance(payload.get(key), str)
            ),
            None,
        )
        presentations = {
            "DecisionCommitted.v1": (
                "decision_committed",
                "success",
                "已选择下载版本",
                f"选择类型: {payload.get('kind', 'automatic')}",
                "decision",
            ),
            "ManualConfirmationRequired.v1": (
                "manual_confirmation",
                "warning",
                "候选需要确认",
                "标题识别置信度不足, 请检查候选信息。",
                "candidate",
            ),
            "ReleaseMappingRequired.v1": (
                "release_mapping",
                "warning",
                "发布条目需要映射",
                "无法自动识别动画或集数。",
                "release",
            ),
            "FeedRepeatedFailure.v1": (
                "feed_failure",
                "error",
                "订阅源连续抓取失败",
                str(payload.get("error_code", "feed fetch failed")),
                "feed",
            ),
            "FeedRecovered.v1": (
                "feed_recovered",
                "success",
                "订阅源已恢复",
                "订阅源抓取恢复正常。",
                "feed",
            ),
            "EpisodeMissing.v1": (
                "episode_missing",
                "warning",
                "预期集数仍未出现",
                (
                    f"{payload.get('anime_title', '动画')} "
                    f"第 {payload.get('episode_key', '?')} 集超过缺集阈值。"
                ),
                "expected_episode",
            ),
        }
        if event.name == "DownloadTaskChanged.v1":
            state = str(payload.get("state", "unknown"))
            if state == "completed":
                return (
                    "download_completed",
                    "success",
                    "下载已完成",
                    "qBittorrent 已完成该任务。",
                    "download_task",
                    entity_id,
                )
            if state in {"failed", "externally_removed"}:
                return (
                    "download_failed",
                    "error",
                    "下载任务需要处理",
                    str(payload.get("error_code", state)),
                    "download_task",
                    entity_id,
                )
            if state in {"submitted", "downloading"}:
                return (
                    "download_started",
                    "info",
                    "下载任务已提交",
                    "qBittorrent 已确认任务存在。",
                    "download_task",
                    entity_id,
                )
            return None
        value = presentations.get(event.name)
        if value is None:
            return None
        kind, level, title, message, entity_type = value
        return kind, level, title, message, entity_type, entity_id
