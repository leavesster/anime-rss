import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent, append_event
from anime_rss.infrastructure.http import HttpFetchError, SafeHttpClient
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.feeds.api import FeedEntryQueries, FeedEntrySecret
from anime_rss.modules.releases.domain import (
    InvalidTorrent,
    TorrentIdentity,
    parse_magnet_identity,
    parse_torrent_identity,
)
from anime_rss.modules.releases.persistence import (
    ReleasePayloadRecord,
    ReleaseRecord,
    ReleaseSourceRecord,
)
from anime_rss.modules.system.api import SecretCipher


@dataclass(frozen=True, slots=True)
class Release:
    id: str
    display_name: str | None
    identity_kind: str
    identity_value: str
    btih: str | None
    btmh: str | None
    automation_eligible: bool
    first_seen_at: datetime
    source_count: int


@dataclass(frozen=True, slots=True)
class ReleaseRecognitionSource:
    release_id: str
    feed_entry_id: str
    title: str
    feed_name: str
    feed_source_type: str
    published_at: datetime | None
    first_seen_at: datetime
    automation_eligible: bool


@dataclass(frozen=True, slots=True)
class ReleaseDownloadSource:
    release_id: str
    info_hash: str
    kind: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ReleaseReference:
    display_name: str | None
    source_url: str | None


@dataclass(frozen=True, slots=True)
class ReleaseRetentionResult:
    releases_removed: int
    feed_entries_removed: int


class ReleaseService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        feed_entries: FeedEntryQueries,
        cipher: SecretCipher,
        torrent_http_client: SafeHttpClient,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._feed_entries = feed_entries
        self._cipher = cipher
        self._torrent_http_client = torrent_http_client
        self._clock = clock

    def handle_feed_entry_observed(self, event: IntegrationEvent) -> None:
        if event.name != "FeedEntryObserved.v1" or event.version != 1:
            return
        entry_id = event.payload.get("feed_entry_id")
        if not isinstance(entry_id, str):
            return
        self.observe_feed_entry(entry_id)

    def observe_feed_entry(self, entry_id: str) -> str | None:
        entry = self._feed_entries.get_secret(entry_id)
        if entry is None or entry.torrent_reference is None:
            self._feed_entries.record_release_resolution(entry_id, status="no_reference")
            return None

        try:
            identity, payload, payload_kind = self._resolve_identity(entry)
        except InvalidTorrent as error:
            self._feed_entries.record_release_resolution(
                entry_id, status="invalid", error_code=str(error)
            )
            return None
        except HttpFetchError as error:
            if error.transient:
                raise
            self._feed_entries.record_release_resolution(
                entry_id, status="invalid", error_code=error.code
            )
            return None

        release_id = self._store_observation(
            entry_id=entry_id,
            identity=identity,
            display_name=identity.torrent_name or entry.title,
            payload=payload,
            payload_kind=payload_kind,
        )
        self._feed_entries.record_release_resolution(entry_id, status="identified")
        return release_id

    def list_releases(self, *, limit: int = 100) -> list[Release]:
        with self._session_factory() as session:
            source_counts = (
                select(
                    ReleaseSourceRecord.release_id,
                    func.count(ReleaseSourceRecord.id).label("source_count"),
                )
                .group_by(ReleaseSourceRecord.release_id)
                .subquery()
            )
            statement = (
                select(ReleaseRecord, source_counts.c.source_count)
                .outerjoin(source_counts, source_counts.c.release_id == ReleaseRecord.id)
                .order_by(ReleaseRecord.first_seen_at.desc())
                .limit(limit)
            )
            return [
                Release(
                    id=record.id,
                    display_name=record.display_name,
                    identity_kind=record.identity_kind,
                    identity_value=record.identity_value,
                    btih=record.btih,
                    btmh=record.btmh,
                    automation_eligible=record.automation_eligible,
                    first_seen_at=record.first_seen_at,
                    source_count=source_count or 0,
                )
                for record, source_count in session.execute(statement)
            ]

    def get_recognition_source(
        self, release_id: str, feed_entry_id: str
    ) -> ReleaseRecognitionSource | None:
        entry = self._feed_entries.get_secret(feed_entry_id)
        if entry is None:
            return None
        with self._session_factory() as session:
            statement = (
                select(ReleaseRecord)
                .join(ReleaseSourceRecord, ReleaseSourceRecord.release_id == ReleaseRecord.id)
                .where(
                    ReleaseRecord.id == release_id,
                    ReleaseSourceRecord.feed_entry_id == feed_entry_id,
                )
            )
            release = session.scalar(statement)
            if release is None:
                return None
            return ReleaseRecognitionSource(
                release_id=release.id,
                feed_entry_id=feed_entry_id,
                title=entry.title,
                feed_name=entry.feed_name,
                feed_source_type=entry.feed_source_type,
                published_at=entry.published_at,
                first_seen_at=release.first_seen_at,
                automation_eligible=release.automation_eligible,
            )

    def has_release(self, release_id: str) -> bool:
        with self._session_factory() as session:
            return session.get(ReleaseRecord, release_id) is not None

    def list_recognition_sources_for_feed(self, feed_id: str) -> list[tuple[str, str]]:
        entry_ids = self._feed_entries.list_ids(feed_id)
        if not entry_ids:
            return []
        with self._session_factory() as session:
            return [
                (release_id, feed_entry_id)
                for release_id, feed_entry_id in session.execute(
                    select(
                        ReleaseSourceRecord.release_id,
                        func.min(ReleaseSourceRecord.feed_entry_id),
                    )
                    .where(ReleaseSourceRecord.feed_entry_id.in_(entry_ids))
                    .group_by(ReleaseSourceRecord.release_id)
                    .order_by(ReleaseSourceRecord.release_id)
                )
            ]

    def get_download_source(self, release_id: str) -> ReleaseDownloadSource | None:
        with self._session_factory() as session:
            release = session.get(ReleaseRecord, release_id)
            if release is None or release.btih is None or not release.automation_eligible:
                return None
            payload = session.scalar(
                select(ReleasePayloadRecord)
                .where(ReleasePayloadRecord.release_id == release_id)
                .order_by(ReleasePayloadRecord.created_at, ReleasePayloadRecord.id)
                .limit(1)
            )
            if payload is None:
                return None
            content = self._cipher.decrypt(
                payload.ciphertext,
                purpose=f"release-payload:{payload.id}:content",
            )
            return ReleaseDownloadSource(
                release_id=release.id,
                info_hash=release.btih,
                kind=payload.kind,
                content=content,
            )

    def get_references(self, release_ids: set[str]) -> dict[str, ReleaseReference]:
        if not release_ids:
            return {}
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    ReleaseRecord.id,
                    ReleaseRecord.display_name,
                    ReleaseSourceRecord.feed_entry_id,
                )
                .outerjoin(
                    ReleaseSourceRecord,
                    ReleaseSourceRecord.release_id == ReleaseRecord.id,
                )
                .where(ReleaseRecord.id.in_(release_ids))
                .order_by(
                    ReleaseRecord.id,
                    ReleaseSourceRecord.observed_at,
                    ReleaseSourceRecord.id,
                )
            )
            first_sources: dict[str, tuple[str | None, str | None]] = {}
            for release_id, display_name, feed_entry_id in rows:
                first_sources.setdefault(release_id, (display_name, feed_entry_id))
        links = self._feed_entries.get_public_links(
            {entry_id for _, entry_id in first_sources.values() if entry_id is not None}
        )
        return {
            release_id: ReleaseReference(
                display_name=display_name,
                source_url=links.get(entry_id) if entry_id is not None else None,
            )
            for release_id, (display_name, entry_id) in first_sources.items()
        }

    def prune_unmatched(
        self, *, before: datetime, retained_release_ids: set[str]
    ) -> ReleaseRetentionResult:
        with self._session_factory() as session:
            statement = select(ReleaseRecord.id).where(ReleaseRecord.first_seen_at < before)
            if retained_release_ids:
                statement = statement.where(ReleaseRecord.id.not_in(retained_release_ids))
            release_ids = set(session.scalars(statement))
            if not release_ids:
                return ReleaseRetentionResult(0, 0)
            entry_ids = set(
                session.scalars(
                    select(ReleaseSourceRecord.feed_entry_id).where(
                        ReleaseSourceRecord.release_id.in_(release_ids)
                    )
                )
            )
        removed_entries = self._feed_entries.delete_entries(entry_ids)
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(delete(ReleaseRecord).where(ReleaseRecord.id.in_(release_ids))),
            )
        return ReleaseRetentionResult(result.rowcount, removed_entries)

    def _resolve_identity(self, entry: FeedEntrySecret) -> tuple[TorrentIdentity, bytes, str]:
        reference = entry.torrent_reference
        assert reference is not None
        if reference.lower().startswith("magnet:"):
            encoded = reference.encode()
            return parse_magnet_identity(reference), encoded, "magnet"

        try:
            parts = urlsplit(reference)
        except ValueError as error:
            raise HttpFetchError("unsupported_url", transient=False) from error
        if parts.scheme not in {"http", "https"}:
            raise InvalidTorrent("unsupported_torrent_reference")
        headers = entry.headers if self._same_origin(entry.feed_url, reference) else {}
        response = self._torrent_http_client.fetch(reference, headers=headers)
        if response.status_code in {401, 403}:
            raise HttpFetchError(
                "torrent_authentication_failed",
                http_status=response.status_code,
                transient=False,
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise HttpFetchError(
                "torrent_upstream_unavailable",
                http_status=response.status_code,
                transient=True,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise HttpFetchError(
                "torrent_unexpected_http_status",
                http_status=response.status_code,
                transient=False,
            )
        return parse_torrent_identity(response.body), response.body, "torrent"

    def _store_observation(
        self,
        *,
        entry_id: str,
        identity: TorrentIdentity,
        display_name: str,
        payload: bytes,
        payload_kind: str,
    ) -> str:
        now = self._clock()
        proposed_release_id = new_id()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    insert(ReleaseRecord)
                    .values(
                        id=proposed_release_id,
                        identity_kind=identity.identity_kind.value,
                        identity_value=identity.identity_value,
                        display_name=display_name,
                        btih=identity.btih,
                        btmh=identity.btmh,
                        automation_eligible=identity.automation_eligible,
                        first_seen_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["identity_kind", "identity_value"])
                ),
            )
            if result.rowcount:
                release_id = proposed_release_id
            else:
                release_id = session.scalar(
                    select(ReleaseRecord.id).where(
                        ReleaseRecord.identity_kind == identity.identity_kind.value,
                        ReleaseRecord.identity_value == identity.identity_value,
                    )
                )
                if release_id is None:
                    raise RuntimeError("release identity conflict could not be resolved")
                if identity.torrent_name is not None:
                    record = session.get(ReleaseRecord, release_id)
                    if record is not None:
                        record.display_name = identity.torrent_name

            source_result = cast(
                CursorResult[Any],
                session.execute(
                    insert(ReleaseSourceRecord)
                    .values(
                        id=new_id(),
                        release_id=release_id,
                        feed_entry_id=entry_id,
                        observed_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["release_id", "feed_entry_id"])
                ),
            )

            payload_id = new_id()
            ciphertext = self._cipher.encrypt(
                payload, purpose=f"release-payload:{payload_id}:content"
            )
            session.execute(
                insert(ReleasePayloadRecord)
                .values(
                    id=payload_id,
                    release_id=release_id,
                    feed_entry_id=entry_id,
                    kind=payload_kind,
                    ciphertext=ciphertext,
                    sha256=payload_sha256,
                    size_bytes=len(payload),
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["release_id", "sha256"])
            )

            if source_result.rowcount:
                append_event(
                    session,
                    name="ReleaseIdentified.v1",
                    payload={"release_id": release_id, "feed_entry_id": entry_id},
                )
                record_event(
                    session,
                    event_type="release.identified",
                    entity_type="release",
                    entity_id=release_id,
                    payload={
                        "identity_kind": identity.identity_kind.value,
                        "identity_value": identity.identity_value,
                        "automation_eligible": identity.automation_eligible,
                    },
                )
        return release_id

    @staticmethod
    def _same_origin(first: str, second: str) -> bool:
        try:
            left = urlsplit(first)
            right = urlsplit(second)
            return (left.scheme, left.hostname, left.port) == (
                right.scheme,
                right.hostname,
                right.port,
            )
        except ValueError:
            return False
