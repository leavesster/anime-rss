from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent, append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.recognition.domain import (
    ContentKind,
    MatchConfidence,
    ParsedReleaseTitle,
    canonical_episode_number,
    normalize_series_key,
    parse_release_title,
)
from anime_rss.modules.recognition.persistence import (
    CandidateRecord,
    ManualActionRecord,
    MatchAttemptRecord,
)
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
    supersedes_candidate_id: str | None
    superseded_by_candidate_id: str | None
    superseded_at: datetime | None


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


class CandidateNotFoundError(LookupError):
    pass


class ReleaseRemapError(ValueError):
    pass


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
                    select(CandidateRecord.id).where(
                        CandidateRecord.release_id == release_id,
                        CandidateRecord.superseded_by_candidate_id.is_(None),
                    )
                )

            candidate_id = self._create_candidate(
                session,
                release_id=release_id,
                attempt_id=attempt_id,
                parsed=parsed,
                source_automation_eligible=source.automation_eligible,
                first_seen_at=source.first_seen_at,
            )
            if candidate_id is None:
                append_event(
                    session,
                    name="ReleaseMappingRequired.v1",
                    payload={"release_id": release_id, "reason_code": parsed.reason_code},
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
                .on_conflict_do_nothing(
                    index_elements=["release_id"],
                    index_where=CandidateRecord.superseded_by_candidate_id.is_(None),
                )
            ),
        )
        if result.rowcount:
            append_event(
                session,
                name="CandidateEvaluated.v1",
                payload={
                    "candidate_id": candidate_id,
                    "release_id": release_id,
                    "episode_key": parsed.episode_key,
                },
            )
            if not recognition_eligible:
                append_event(
                    session,
                    name="ManualConfirmationRequired.v1",
                    payload={"candidate_id": candidate_id, "release_id": release_id},
                )
            return candidate_id
        return session.scalar(
            select(CandidateRecord.id).where(
                CandidateRecord.release_id == release_id,
                CandidateRecord.superseded_by_candidate_id.is_(None),
            )
        )

    def list_episode_groups(self, *, limit: int = 100) -> list[EpisodeGroup]:
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(CandidateRecord)
                    .where(CandidateRecord.superseded_by_candidate_id.is_(None))
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
            candidate_exists = select(CandidateRecord.id).where(
                CandidateRecord.attempt_id == MatchAttemptRecord.id
            )
            statement = (
                select(MatchAttemptRecord)
                .where(
                    MatchAttemptRecord.confidence == MatchConfidence.LOW.value,
                    ~candidate_exists.exists(),
                )
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

    def confirm_candidate(self, candidate_id: str) -> Candidate:
        now = self._clock()
        with self._session_factory.begin() as session:
            record = session.get(CandidateRecord, candidate_id)
            if record is None or record.superseded_by_candidate_id is not None:
                raise CandidateNotFoundError(candidate_id)
            if not record.recognition_eligible or record.confidence != MatchConfidence.HIGH.value:
                previous_confidence = record.confidence
                record.recognition_eligible = True
                record.confidence = MatchConfidence.HIGH.value
                session.add(
                    ManualActionRecord(
                        candidate_id=record.id,
                        attempt_id=record.attempt_id,
                        action="confirmed",
                        payload={"previous_confidence": previous_confidence},
                        created_at=now,
                    )
                )
                append_event(
                    session,
                    name="CandidateEvaluated.v1",
                    payload={
                        "candidate_id": record.id,
                        "release_id": record.release_id,
                        "episode_key": record.episode_key,
                        "trigger": "manual_confirmation",
                    },
                )
                record_event(
                    session,
                    event_type="recognition.candidate_confirmed",
                    entity_type="candidate",
                    entity_id=record.id,
                    payload={"episode_key": record.episode_key},
                )
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise CandidateNotFoundError(candidate_id)
        return candidate

    def remap_release(
        self,
        release_id: str,
        *,
        series_title: str,
        episode_start: str,
        episode_end: str | None = None,
        season: int | None = None,
        release_group: str | None = None,
    ) -> Candidate:
        title = series_title.strip()[:300]
        series_key = normalize_series_key(title)
        start = canonical_episode_number(episode_start)
        end = canonical_episode_number(episode_end)
        if not title or not series_key:
            raise ReleaseRemapError("series title is required")
        if start is None or (episode_end is not None and end is None):
            raise ReleaseRemapError("episode number is invalid")
        if end is not None and start == end:
            end = None
        episode_key = f"{start}-{end}" if end else start
        now = self._clock()
        with self._session_factory.begin() as session:
            previous = session.scalar(
                select(CandidateRecord).where(
                    CandidateRecord.release_id == release_id,
                    CandidateRecord.superseded_by_candidate_id.is_(None),
                )
            )
            attempt = session.scalar(
                select(MatchAttemptRecord)
                .where(MatchAttemptRecord.release_id == release_id)
                .order_by(MatchAttemptRecord.parsed_at.desc(), MatchAttemptRecord.id.desc())
            )
            if attempt is None:
                raise CandidateNotFoundError(release_id)
            source = self._sources.get_recognition_source(release_id, attempt.feed_entry_id)
            if source is None:
                raise CandidateNotFoundError(release_id)
            candidate_id = new_id()
            if previous is not None:
                previous.superseded_by_candidate_id = candidate_id
                previous.superseded_at = now
            session.add(
                CandidateRecord(
                    id=candidate_id,
                    release_id=release_id,
                    attempt_id=attempt.id,
                    supersedes_candidate_id=previous.id if previous is not None else None,
                    source_title=attempt.source_title,
                    series_title=title,
                    series_key=series_key,
                    season=season,
                    episode_start=start,
                    episode_end=end,
                    episode_key=episode_key,
                    release_group=(release_group.strip()[:120] if release_group else None),
                    resolution=attempt.resolution,
                    video_codec=attempt.video_codec,
                    subtitle_language=attempt.subtitle_language,
                    revision=attempt.revision,
                    content_kind=(attempt.content_kind or ContentKind.EPISODE.value),
                    confidence=MatchConfidence.HIGH.value,
                    recognition_eligible=source.automation_eligible,
                    first_seen_at=source.first_seen_at,
                )
            )
            session.flush()
            session.add(
                ManualActionRecord(
                    candidate_id=candidate_id,
                    attempt_id=attempt.id,
                    action="remapped",
                    payload={
                        "supersedes_candidate_id": previous.id if previous is not None else None,
                        "previous_series_key": previous.series_key
                        if previous is not None
                        else None,
                        "previous_episode_key": previous.episode_key
                        if previous is not None
                        else None,
                        "series_title": title,
                        "series_key": series_key,
                        "season": season,
                        "episode_key": episode_key,
                        "release_group": release_group,
                    },
                    created_at=now,
                )
            )
            if previous is not None:
                append_event(
                    session,
                    name="CandidateRemapped.v1",
                    payload={
                        "release_id": release_id,
                        "previous_candidate_id": previous.id,
                        "candidate_id": candidate_id,
                        "previous_series_key": previous.series_key,
                        "previous_episode_key": previous.episode_key,
                        "episode_key": episode_key,
                    },
                )
            append_event(
                session,
                name="CandidateEvaluated.v1",
                payload={
                    "candidate_id": candidate_id,
                    "release_id": release_id,
                    "episode_key": episode_key,
                    "trigger": "manual_remap",
                },
            )
            record_event(
                session,
                event_type="recognition.release_remapped",
                entity_type="release",
                entity_id=release_id,
                payload={
                    "candidate_id": candidate_id,
                    "supersedes_candidate_id": previous.id if previous is not None else None,
                    "episode_key": episode_key,
                },
            )
        candidate = self.get_candidate(candidate_id)
        assert candidate is not None
        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        with self._session_factory() as session:
            record = session.get(CandidateRecord, candidate_id)
            return self._to_candidate(record) if record is not None else None

    def list_candidates_for_series_keys(self, series_keys: set[str]) -> list[Candidate]:
        if not series_keys:
            return []
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(CandidateRecord)
                    .where(
                        CandidateRecord.series_key.in_(series_keys),
                        CandidateRecord.superseded_by_candidate_id.is_(None),
                    )
                    .order_by(CandidateRecord.first_seen_at, CandidateRecord.id)
                )
            )
            return [self._to_candidate(record) for record in records]

    def permanent_release_ids(self) -> set[str]:
        with self._session_factory() as session:
            return set(
                session.scalars(
                    select(MatchAttemptRecord.release_id)
                    .join(
                        ManualActionRecord, ManualActionRecord.attempt_id == MatchAttemptRecord.id
                    )
                    .distinct()
                )
            )

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
            supersedes_candidate_id=record.supersedes_candidate_id,
            superseded_by_candidate_id=record.superseded_by_candidate_id,
            superseded_at=record.superseded_at,
        )
