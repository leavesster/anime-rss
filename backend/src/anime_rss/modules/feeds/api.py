import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import append_event
from anime_rss.infrastructure.http import HttpFetchError, HttpResult, SafeHttpClient
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.feeds.adapters import (
    FeedDocumentParser,
    FeedParseError,
)
from anime_rss.modules.feeds.domain import (
    FeedHealth,
    NormalizedFeedEntry,
    plan_transient_retry,
    redact_url,
    validate_refresh_interval,
)
from anime_rss.modules.feeds.persistence import FeedEntryRecord, FeedFetchRecord, FeedRecord
from anime_rss.modules.system.api import SecretCipher


class FeedNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Feed:
    id: str
    name: str
    url_redacted: str
    interval_seconds: int
    health: str
    consecutive_failures: int
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_fetch_at: datetime | None
    error_code: str | None
    version: int


@dataclass(frozen=True, slots=True)
class FeedEntry:
    id: str
    feed_id: str
    title: str
    published_at: datetime | None
    link_redacted: str | None
    identity_strength: str
    release_status: str
    release_error_code: str | None
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class FeedEntrySecret:
    id: str
    title: str
    published_at: datetime | None
    feed_url: str
    headers: dict[str, str]
    torrent_reference: str | None


@dataclass(frozen=True, slots=True)
class FeedFetch:
    id: str
    feed_id: str
    status: str
    http_status: int | None
    error_code: str | None
    entry_count: int
    new_entry_count: int
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshResult:
    feed_id: str
    status: str
    entry_count: int
    new_entry_count: int
    health: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class FeedTestResult:
    status: str
    entry_count: int
    preview_titles: list[str]
    error_code: str | None = None


Jitter = Callable[[int], int]


def _default_jitter(maximum: int) -> int:
    return random.SystemRandom().randint(0, maximum)


def _decode_headers(payload: bytes) -> dict[str, str]:
    decoded = cast(object, json.loads(payload))
    if not isinstance(decoded, dict):
        raise ValueError("stored feed headers are invalid")
    items = cast(dict[object, object], decoded)
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in items.items()):
        raise ValueError("stored feed headers are invalid")
    return cast(dict[str, str], items)


class FeedService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        cipher: SecretCipher,
        http_client: SafeHttpClient,
        parser: FeedDocumentParser,
        *,
        clock: Clock = utc_now,
        jitter: Jitter = _default_jitter,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._http_client = http_client
        self._parser = parser
        self._clock = clock
        self._jitter = jitter

    def create_feed(
        self,
        *,
        name: str,
        url: str,
        interval_seconds: int = 600,
        headers: dict[str, str] | None = None,
    ) -> Feed:
        self._validate_configuration(name=name, url=url, interval_seconds=interval_seconds)
        feed_id = new_id()
        now = self._clock()
        record = FeedRecord(
            id=feed_id,
            name=name.strip(),
            url_redacted=redact_url(url),
            endpoint_ciphertext=self._cipher.encrypt(
                url.encode(), purpose=f"feed:{feed_id}:endpoint"
            ),
            headers_ciphertext=self._encrypt_headers(feed_id, headers or {}),
            interval_seconds=interval_seconds,
            next_fetch_at=now,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory.begin() as session:
            session.add(record)
            record_event(
                session,
                event_type="feed.created",
                entity_type="feed",
                entity_id=feed_id,
                payload={"url": record.url_redacted, "interval_seconds": interval_seconds},
            )
        return self._to_feed(record)

    def update_feed(
        self,
        feed_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        interval_seconds: int | None = None,
        headers: dict[str, str] | None = None,
        expected_version: int | None = None,
    ) -> Feed:
        with self._session_factory.begin() as session:
            record = session.get(FeedRecord, feed_id)
            if record is None:
                raise FeedNotFoundError(feed_id)
            if expected_version is not None and record.version != expected_version:
                raise ValueError("feed version conflict")
            next_name = name.strip() if name is not None else record.name
            next_url = url or self._decrypt_endpoint(record)
            next_interval = interval_seconds or record.interval_seconds
            self._validate_configuration(
                name=next_name, url=next_url, interval_seconds=next_interval
            )
            record.name = next_name
            record.interval_seconds = next_interval
            if url is not None:
                record.url_redacted = redact_url(url)
                record.endpoint_ciphertext = self._cipher.encrypt(
                    url.encode(), purpose=f"feed:{feed_id}:endpoint"
                )
            if headers is not None:
                record.headers_ciphertext = self._encrypt_headers(feed_id, headers)
            record.version += 1
            record.updated_at = self._clock()
            record.error_code = None
            if record.health == FeedHealth.AUTH_FAILED.value:
                record.health = FeedHealth.UNKNOWN.value
                record.next_fetch_at = self._clock()
            record_event(
                session,
                event_type="feed.updated",
                entity_type="feed",
                entity_id=feed_id,
                payload={"url": record.url_redacted, "version": record.version},
            )
        return self._to_feed(record)

    def delete_feed(self, feed_id: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(FeedRecord, feed_id)
            if record is None:
                raise FeedNotFoundError(feed_id)
            record_event(
                session,
                event_type="feed.deleted",
                entity_type="feed",
                entity_id=feed_id,
                payload={"url": record.url_redacted},
            )
            session.delete(record)

    def list_feeds(self) -> list[Feed]:
        with self._session_factory() as session:
            records = session.scalars(select(FeedRecord).order_by(FeedRecord.name)).all()
            return [self._to_feed(record) for record in records]

    def list_entries(self, feed_id: str, *, limit: int = 100) -> list[FeedEntry]:
        with self._session_factory() as session:
            if session.get(FeedRecord, feed_id) is None:
                raise FeedNotFoundError(feed_id)
            records = session.scalars(
                select(FeedEntryRecord)
                .where(FeedEntryRecord.feed_id == feed_id)
                .order_by(FeedEntryRecord.first_seen_at.desc())
                .limit(limit)
            ).all()
            return [self._to_entry(record) for record in records]

    def list_fetches(self, feed_id: str, *, limit: int = 100) -> list[FeedFetch]:
        with self._session_factory() as session:
            if session.get(FeedRecord, feed_id) is None:
                raise FeedNotFoundError(feed_id)
            records = session.scalars(
                select(FeedFetchRecord)
                .where(FeedFetchRecord.feed_id == feed_id)
                .order_by(FeedFetchRecord.started_at.desc())
                .limit(limit)
            ).all()
            return [
                FeedFetch(
                    id=record.id,
                    feed_id=record.feed_id,
                    status=record.status,
                    http_status=record.http_status,
                    error_code=record.error_code,
                    entry_count=record.entry_count,
                    new_entry_count=record.new_entry_count,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                )
                for record in records
            ]

    def test_feed(self, *, url: str, headers: dict[str, str] | None = None) -> FeedTestResult:
        self._validate_configuration(name="test", url=url, interval_seconds=600)
        try:
            response = self._http_client.fetch(url, headers=headers)
            self._raise_for_status(response)
            entries = self._parser.parse(response.body)
        except (HttpFetchError, FeedParseError) as error:
            return FeedTestResult(
                status="failed", entry_count=0, preview_titles=[], error_code=str(error)
            )
        return FeedTestResult(
            status="success",
            entry_count=len(entries),
            preview_titles=[entry.title_normalized for entry in entries[:10]],
        )

    def refresh_feed(self, feed_id: str) -> RefreshResult:
        started_at = self._clock()
        with self._session_factory() as session:
            record = session.get(FeedRecord, feed_id)
            if record is None:
                raise FeedNotFoundError(feed_id)
            url = self._decrypt_endpoint(record)
            headers = self._decrypt_headers(record)
            etag = record.etag
            last_modified = record.last_modified

        try:
            response = self._http_client.fetch(
                url, headers=headers, etag=etag, last_modified=last_modified
            )
            if response.status_code == 304:
                return self._record_not_modified(feed_id, started_at, response)
            self._raise_for_status(response)
            entries = self._parser.parse(response.body)
        except HttpFetchError as error:
            return self._record_fetch_error(feed_id, started_at, error)
        except FeedParseError as error:
            return self._record_invalid_content(feed_id, started_at, str(error))

        return self._record_success(feed_id, started_at, response, entries)

    def _record_success(
        self,
        feed_id: str,
        started_at: datetime,
        response: HttpResult,
        entries: list[NormalizedFeedEntry],
    ) -> RefreshResult:
        now = self._clock()
        new_count = 0
        with self._session_factory.begin() as session:
            feed = self._required_feed(session, feed_id)
            for entry in entries:
                entry_id = new_id()
                reference_ciphertext = None
                if entry.torrent_reference is not None:
                    reference_ciphertext = self._cipher.encrypt(
                        entry.torrent_reference.encode(), purpose=f"feed-entry:{entry_id}:torrent"
                    )
                statement = (
                    insert(FeedEntryRecord)
                    .values(
                        id=entry_id,
                        feed_id=feed_id,
                        source_guid=entry.source_guid,
                        guid_hash=entry.guid_hash,
                        identity_strength=entry.identity_strength.value,
                        title_raw=entry.title_raw,
                        title_normalized=entry.title_normalized,
                        published_at=entry.published_at,
                        link_redacted=redact_url(entry.link),
                        torrent_reference_ciphertext=reference_ciphertext,
                        first_seen_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["feed_id", "guid_hash"])
                )
                result = cast(CursorResult[Any], session.execute(statement))
                if result.rowcount:
                    new_count += 1
                    append_event(
                        session,
                        name="FeedEntryObserved.v1",
                        payload={"feed_entry_id": entry_id},
                    )

            feed.health = FeedHealth.HEALTHY.value
            feed.consecutive_failures = 0
            feed.error_code = None
            feed.last_attempt_at = now
            feed.last_success_at = now
            feed.next_fetch_at = now + timedelta(
                seconds=feed.interval_seconds + self._jitter(max(1, feed.interval_seconds // 10))
            )
            feed.etag = response.etag or feed.etag
            feed.last_modified = response.last_modified or feed.last_modified
            feed.updated_at = now
            session.add(
                FeedFetchRecord(
                    feed_id=feed_id,
                    status="success",
                    http_status=response.status_code,
                    entry_count=len(entries),
                    new_entry_count=new_count,
                    started_at=started_at,
                    finished_at=now,
                )
            )
            record_event(
                session,
                event_type="feed.refresh_succeeded",
                entity_type="feed",
                entity_id=feed_id,
                payload={"entry_count": len(entries), "new_entry_count": new_count},
            )

        return RefreshResult(
            feed_id=feed_id,
            status="success",
            entry_count=len(entries),
            new_entry_count=new_count,
            health=FeedHealth.HEALTHY.value,
            error_code=None,
        )

    def _record_not_modified(
        self, feed_id: str, started_at: datetime, response: HttpResult
    ) -> RefreshResult:
        now = self._clock()
        with self._session_factory.begin() as session:
            feed = self._required_feed(session, feed_id)
            feed.health = FeedHealth.HEALTHY.value
            feed.consecutive_failures = 0
            feed.error_code = None
            feed.last_attempt_at = now
            feed.last_success_at = now
            feed.next_fetch_at = now + timedelta(seconds=feed.interval_seconds)
            feed.etag = response.etag or feed.etag
            feed.last_modified = response.last_modified or feed.last_modified
            feed.updated_at = now
            session.add(
                FeedFetchRecord(
                    feed_id=feed_id,
                    status="not_modified",
                    http_status=304,
                    started_at=started_at,
                    finished_at=now,
                )
            )
        return RefreshResult(
            feed_id=feed_id,
            status="not_modified",
            entry_count=0,
            new_entry_count=0,
            health=FeedHealth.HEALTHY.value,
            error_code=None,
        )

    def _record_fetch_error(
        self, feed_id: str, started_at: datetime, error: HttpFetchError
    ) -> RefreshResult:
        now = self._clock()
        with self._session_factory.begin() as session:
            feed = self._required_feed(session, feed_id)
            if error.http_status in {401, 403}:
                feed.health = FeedHealth.AUTH_FAILED.value
                feed.consecutive_failures += 1
                feed.next_fetch_at = None
                status = "auth_failed"
            elif error.transient:
                retry = plan_transient_retry(
                    now=now,
                    previous_failures=feed.consecutive_failures,
                    jitter_seconds=self._jitter(60),
                )
                feed.health = retry.health.value
                feed.consecutive_failures = retry.consecutive_failures
                feed.next_fetch_at = retry.next_fetch_at
                status = "transient_failure"
            else:
                feed.health = FeedHealth.DEGRADED.value
                feed.consecutive_failures += 1
                feed.next_fetch_at = now + timedelta(hours=1)
                status = "invalid_response"
            feed.error_code = error.code
            feed.last_attempt_at = now
            feed.updated_at = now
            session.add(
                FeedFetchRecord(
                    feed_id=feed_id,
                    status=status,
                    http_status=error.http_status,
                    error_code=error.code,
                    started_at=started_at,
                    finished_at=now,
                )
            )
            record_event(
                session,
                event_type="feed.refresh_failed",
                entity_type="feed",
                entity_id=feed_id,
                payload={"error_code": error.code, "status": status},
            )
            health = feed.health
        return RefreshResult(
            feed_id=feed_id,
            status=status,
            entry_count=0,
            new_entry_count=0,
            health=health,
            error_code=error.code,
        )

    def _record_invalid_content(
        self, feed_id: str, started_at: datetime, error_code: str
    ) -> RefreshResult:
        return self._record_fetch_error(
            feed_id,
            started_at,
            HttpFetchError(error_code, http_status=200, transient=False),
        )

    def _raise_for_status(self, response: HttpResult) -> None:
        status = response.status_code
        if status in {401, 403}:
            raise HttpFetchError("authentication_failed", http_status=status, transient=False)
        if status == 429 or status >= 500:
            raise HttpFetchError("upstream_unavailable", http_status=status, transient=True)
        if status < 200 or status >= 300:
            raise HttpFetchError("unexpected_http_status", http_status=status, transient=False)

    def _encrypt_headers(self, feed_id: str, headers: dict[str, str]) -> bytes | None:
        if not headers:
            return None
        payload = json.dumps(headers, sort_keys=True, separators=(",", ":")).encode()
        return self._cipher.encrypt(payload, purpose=f"feed:{feed_id}:headers")

    def _decrypt_headers(self, record: FeedRecord) -> dict[str, str]:
        if record.headers_ciphertext is None:
            return {}
        payload = self._cipher.decrypt(
            record.headers_ciphertext, purpose=f"feed:{record.id}:headers"
        )
        return _decode_headers(payload)

    def _decrypt_endpoint(self, record: FeedRecord) -> str:
        return self._cipher.decrypt(
            record.endpoint_ciphertext, purpose=f"feed:{record.id}:endpoint"
        ).decode()

    @staticmethod
    def _required_feed(session: Session, feed_id: str) -> FeedRecord:
        record = session.get(FeedRecord, feed_id)
        if record is None:
            raise FeedNotFoundError(feed_id)
        return record

    @staticmethod
    def _validate_configuration(*, name: str, url: str, interval_seconds: int) -> None:
        if not name.strip() or len(name.strip()) > 120:
            raise ValueError("feed name must contain between 1 and 120 characters")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("feed URL must use HTTP or HTTPS")
        validate_refresh_interval(interval_seconds)

    @staticmethod
    def _to_feed(record: FeedRecord) -> Feed:
        return Feed(
            id=record.id,
            name=record.name,
            url_redacted=record.url_redacted,
            interval_seconds=record.interval_seconds,
            health=record.health,
            consecutive_failures=record.consecutive_failures,
            last_attempt_at=record.last_attempt_at,
            last_success_at=record.last_success_at,
            next_fetch_at=record.next_fetch_at,
            error_code=record.error_code,
            version=record.version,
        )

    @staticmethod
    def _to_entry(record: FeedEntryRecord) -> FeedEntry:
        return FeedEntry(
            id=record.id,
            feed_id=record.feed_id,
            title=record.title_normalized,
            published_at=record.published_at,
            link_redacted=record.link_redacted,
            identity_strength=record.identity_strength,
            release_status=record.release_status,
            release_error_code=record.release_error_code,
            first_seen_at=record.first_seen_at,
        )


class FeedEntryQueries:
    def __init__(self, session_factory: sessionmaker[Session], cipher: SecretCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    def get_secret(self, entry_id: str) -> FeedEntrySecret | None:
        with self._session_factory() as session:
            statement = (
                select(FeedEntryRecord, FeedRecord)
                .join(FeedRecord, FeedRecord.id == FeedEntryRecord.feed_id)
                .where(FeedEntryRecord.id == entry_id)
            )
            row = session.execute(statement).one_or_none()
            if row is None:
                return None
            entry, feed = row
            endpoint = self._cipher.decrypt(
                feed.endpoint_ciphertext, purpose=f"feed:{feed.id}:endpoint"
            ).decode()
            headers: dict[str, str] = {}
            if feed.headers_ciphertext is not None:
                headers_payload = self._cipher.decrypt(
                    feed.headers_ciphertext, purpose=f"feed:{feed.id}:headers"
                )
                headers = _decode_headers(headers_payload)
            reference = None
            if entry.torrent_reference_ciphertext is not None:
                reference = self._cipher.decrypt(
                    entry.torrent_reference_ciphertext,
                    purpose=f"feed-entry:{entry.id}:torrent",
                ).decode()
            return FeedEntrySecret(
                id=entry.id,
                title=entry.title_normalized,
                published_at=entry.published_at,
                feed_url=endpoint,
                headers=headers,
                torrent_reference=reference,
            )

    def record_release_resolution(
        self, entry_id: str, *, status: str, error_code: str | None = None
    ) -> None:
        with self._session_factory.begin() as session:
            entry = session.get(FeedEntryRecord, entry_id)
            if entry is None:
                return
            entry.release_status = status
            entry.release_error_code = error_code
