from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.recognition.domain import (
    MatchConfidence,
    ParsedReleaseTitle,
    parse_release_title,
)
from anime_rss.modules.recognition.persistence import CandidateRecord, MatchAttemptRecord
from anime_rss.modules.releases.api import ReleaseRecognitionSource


class RecognitionSourceProvider(Protocol):
    def get_recognition_source(
        self, release_id: str, feed_entry_id: str
    ) -> ReleaseRecognitionSource | None: ...


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    release_id: str
    source_title: str
    series_title: str
    series_key: str
    season: int | None
    episode_start: str
    episode_end: str | None
    episode_key: str
    release_group: str | None
    resolution: str | None
    video_codec: str | None
    subtitle_language: str | None
    revision: int
    content_kind: str
    confidence: str
    recognition_eligible: bool
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class EpisodeGroup:
    key: str
    series_title: str
    series_key: str
    season: int | None
    episode_key: str
    candidate_count: int
    candidates: list[Candidate]
    latest_seen_at: datetime


@dataclass(frozen=True, slots=True)
class UnmatchedRelease:
    id: str
    release_id: str
    source_title: str
    confidence: str
    reason_code: str
    parsed_at: datetime


class RecognitionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        sources: RecognitionSourceProvider,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._clock = clock

    def handle_release_identified(self, event: IntegrationEvent) -> None:
        if event.name != "ReleaseIdentified.v1" or event.version != 1:
            return
        release_id = event.payload.get("release_id")
        feed_entry_id = event.payload.get("feed_entry_id")
        if not isinstance(release_id, str) or not isinstance(feed_entry_id, str):
            return
        self.recognize(release_id, feed_entry_id)

    def recognize(self, release_id: str, feed_entry_id: str) -> str | None:
        source = self._sources.get_recognition_source(release_id, feed_entry_id)
        if source is None:
            return None
        parsed = parse_release_title(source.title)
        now = self._clock()
        attempt_id = new_id()

        with self._session_factory.begin() as session:
            result = cast(
                CursorResult[object],
                session.execute(
                    insert(MatchAttemptRecord)
                    .values(
                        id=attempt_id,
                        release_id=release_id,
                        feed_entry_id=feed_entry_id,
                        parser_version=parsed.parser_version,
                        source_title=parsed.source_title,
                        release_group=parsed.release_group,
                        series_title=parsed.series_title,
                        series_key=parsed.series_key,
                        season=parsed.season,
                        episode_start=parsed.episode_start,
                        episode_end=parsed.episode_end,
                        episode_key=parsed.episode_key,
                        resolution=parsed.resolution,
                        video_codec=parsed.video_codec,
                        subtitle_language=parsed.subtitle_language,
                        revision=parsed.revision,
                        content_kind=parsed.content_kind.value,
                        confidence=parsed.confidence.value,
                        reason_code=parsed.reason_code,
                        parsed_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["feed_entry_id"])
                ),
            )
            if not result.rowcount:
                return session.scalar(
                    select(CandidateRecord.id).where(CandidateRecord.release_id == release_id)
                )

            candidate_id = self._create_candidate(
                session,
                release_id=release_id,
                attempt_id=attempt_id,
                parsed=parsed,
                source_automation_eligible=source.automation_eligible,
                first_seen_at=source.first_seen_at,
            )
            record_event(
                session,
                event_type="release.recognized",
                entity_type="release",
                entity_id=release_id,
                payload={
                    "parser_version": parsed.parser_version,
                    "confidence": parsed.confidence.value,
                    "reason_code": parsed.reason_code,
                    "episode_key": parsed.episode_key,
                },
            )
        return candidate_id

    def _create_candidate(
        self,
        session: Session,
        *,
        release_id: str,
        attempt_id: str,
        parsed: ParsedReleaseTitle,
        source_automation_eligible: bool,
        first_seen_at: datetime,
    ) -> str | None:
        if not all(
            (
                parsed.series_title,
                parsed.series_key,
                parsed.episode_start,
                parsed.episode_key,
            )
        ):
            return None
        candidate_id = new_id()
        recognition_eligible = (
            source_automation_eligible and parsed.confidence == MatchConfidence.HIGH
        )
        result = cast(
            CursorResult[object],
            session.execute(
                insert(CandidateRecord)
                .values(
                    id=candidate_id,
                    release_id=release_id,
                    attempt_id=attempt_id,
                    source_title=parsed.source_title,
                    series_title=parsed.series_title,
                    series_key=parsed.series_key,
                    season=parsed.season,
                    episode_start=parsed.episode_start,
                    episode_end=parsed.episode_end,
                    episode_key=parsed.episode_key,
                    release_group=parsed.release_group,
                    resolution=parsed.resolution,
                    video_codec=parsed.video_codec,
                    subtitle_language=parsed.subtitle_language,
                    revision=parsed.revision,
                    content_kind=parsed.content_kind.value,
                    confidence=parsed.confidence.value,
                    recognition_eligible=recognition_eligible,
                    first_seen_at=first_seen_at,
                )
                .on_conflict_do_nothing(index_elements=["release_id"])
            ),
        )
        if result.rowcount:
            return candidate_id
        return session.scalar(
            select(CandidateRecord.id).where(CandidateRecord.release_id == release_id)
        )

    def list_episode_groups(self, *, limit: int = 100) -> list[EpisodeGroup]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(CandidateRecord)
                    .order_by(CandidateRecord.first_seen_at.desc(), CandidateRecord.id)
                    .limit(min(max(limit, 1), 500) * 20)
                )
            )

        grouped: dict[tuple[str, str], list[CandidateRecord]] = defaultdict(list)
        for record in records:
            grouped[(record.series_key, record.episode_key)].append(record)

        groups = [self._to_group(key, candidates) for key, candidates in grouped.items()]
        groups.sort(key=lambda group: (group.latest_seen_at, group.key), reverse=True)
        return groups[:limit]

    def list_unmatched(self, *, limit: int = 100) -> list[UnmatchedRelease]:
        with self._session_factory() as session:
            statement = (
                select(MatchAttemptRecord)
                .where(MatchAttemptRecord.confidence == MatchConfidence.LOW.value)
                .order_by(MatchAttemptRecord.parsed_at.desc())
                .limit(min(max(limit, 1), 500))
            )
            return [
                UnmatchedRelease(
                    id=record.id,
                    release_id=record.release_id,
                    source_title=record.source_title,
                    confidence=record.confidence,
                    reason_code=record.reason_code,
                    parsed_at=record.parsed_at,
                )
                for record in session.scalars(statement)
            ]

    @staticmethod
    def _to_group(key: tuple[str, str], records: list[CandidateRecord]) -> EpisodeGroup:
        series_key, episode_key = key
        candidates = [RecognitionService._to_candidate(record) for record in records]
        latest_seen_at = max(candidate.first_seen_at for candidate in candidates)
        known_seasons = {
            candidate.season for candidate in candidates if candidate.season is not None
        }
        season = known_seasons.pop() if len(known_seasons) == 1 else None
        return EpisodeGroup(
            key=f"{series_key}:{episode_key}",
            series_title=records[0].series_title,
            series_key=series_key,
            season=season,
            episode_key=episode_key,
            candidate_count=len(candidates),
            candidates=candidates,
            latest_seen_at=latest_seen_at,
        )

    @staticmethod
    def _to_candidate(record: CandidateRecord) -> Candidate:
        return Candidate(
            id=record.id,
            release_id=record.release_id,
            source_title=record.source_title,
            series_title=record.series_title,
            series_key=record.series_key,
            season=record.season,
            episode_start=record.episode_start,
            episode_end=record.episode_end,
            episode_key=record.episode_key,
            release_group=record.release_group,
            resolution=record.resolution,
            video_codec=record.video_codec,
            subtitle_language=record.subtitle_language,
            revision=record.revision,
            content_kind=record.content_kind,
            confidence=record.confidence,
            recognition_eligible=record.recognition_eligible,
            first_seen_at=record.first_seen_at,
        )
