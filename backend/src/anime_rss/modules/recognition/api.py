from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent, append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.kernel.titles import title_variant_signature
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.catalog.api import CatalogTitleMatch
from anime_rss.modules.recognition.domain import (
    ContentKind,
    MatchConfidence,
    ParsedReleaseTitle,
    canonical_episode_number,
    extract_series_titles,
    normalize_series_key,
    parse_release_title,
)
from anime_rss.modules.recognition.persistence import (
    CandidateRecord,
    DismissedReleaseRecord,
    ManualActionRecord,
    MatchAttemptRecord,
)
from anime_rss.modules.releases.api import ReleaseRecognitionSource, ReleaseReference


class RecognitionSourceProvider(Protocol):
    def get_recognition_source(
        self, release_id: str, feed_entry_id: str
    ) -> ReleaseRecognitionSource | None: ...

    def get_references(self, release_ids: set[str]) -> dict[str, ReleaseReference]: ...

    def list_recognition_sources_for_feed(self, feed_id: str) -> list[tuple[str, str]]: ...


class CatalogTitleResolver(Protocol):
    def resolve_titles(self, titles: list[str]) -> CatalogTitleMatch: ...


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    release_id: str
    source_title: str
    series_title: str
    title_variants: list[str]
    series_key: str
    anime_id: str | None
    catalog_match_status: str
    catalog_match_method: str | None
    catalog_match_key: str | None
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
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeGroup:
    key: str
    series_title: str
    series_key: str
    series_identity: str
    anime_id: str | None
    catalog_match_status: str
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
    content_kind: str
    parsed_at: datetime
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class RecognitionRerun:
    attempt_id: str
    release_id: str
    parser_version: str
    parsed_at: datetime
    confidence: str
    reason_code: str
    candidate_id: str | None
    previous_candidate_id: str | None
    candidate_changed: bool
    candidate_adopted: bool


class CandidateNotFoundError(LookupError):
    pass


class ReleaseRemapError(ValueError):
    pass


class ReleaseDismissError(ValueError):
    pass


class RecognitionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        sources: RecognitionSourceProvider,
        catalog: CatalogTitleResolver,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._catalog = catalog
        self._clock = clock

    def handle_release_identified(self, event: IntegrationEvent) -> None:
        if event.name != "ReleaseIdentified.v1" or event.version != 1:
            return
        release_id = event.payload.get("release_id")
        feed_entry_id = event.payload.get("feed_entry_id")
        if not isinstance(release_id, str) or not isinstance(feed_entry_id, str):
            return
        self.recognize(release_id, feed_entry_id)

    def handle_catalog_titles_changed(self, event: IntegrationEvent) -> None:
        if event.name != "CatalogTitlesChanged.v1" or event.version != 1:
            return
        self.reconcile_catalog_matches()

    def handle_feed_recognition_context_changed(self, event: IntegrationEvent) -> None:
        if event.name != "FeedRecognitionContextChanged.v1" or event.version != 1:
            return
        feed_id = event.payload.get("feed_id")
        if not isinstance(feed_id, str):
            return
        for release_id, feed_entry_id in self._sources.list_recognition_sources_for_feed(feed_id):
            self.rerun_release(release_id, feed_entry_id=feed_entry_id)

    def reconcile_catalog_matches(self) -> int:
        with self._session_factory() as session:
            candidates = list(
                session.execute(
                    select(
                        CandidateRecord.id,
                        CandidateRecord.source_title,
                        CandidateRecord.series_title,
                        CandidateRecord.title_variants,
                    ).where(CandidateRecord.superseded_by_candidate_id.is_(None))
                )
            )
        resolved = [
            (
                candidate_id,
                list(title_variants or extract_series_titles(source_title) or (series_title,)),
            )
            for candidate_id, source_title, series_title, title_variants in candidates
        ]
        resolved = [
            (candidate_id, title_variants, self._catalog.resolve_titles(title_variants))
            for candidate_id, title_variants in resolved
        ]
        changed = 0
        with self._session_factory.begin() as session:
            for candidate_id, title_variants, catalog_match in resolved:
                record = session.get(CandidateRecord, candidate_id)
                if record is None or record.superseded_by_candidate_id is not None:
                    continue
                if record.title_variants is None:
                    record.title_variants = title_variants
                previous_anime_id = record.anime_id
                previous_status = record.catalog_match_status
                next_identity = (
                    catalog_match.anime_id,
                    catalog_match.status,
                    catalog_match.method,
                    catalog_match.matched_key,
                )
                current_identity = (
                    record.anime_id,
                    record.catalog_match_status,
                    record.catalog_match_method,
                    record.catalog_match_key,
                )
                if next_identity == current_identity:
                    continue
                record.anime_id = catalog_match.anime_id
                record.catalog_match_status = catalog_match.status
                record.catalog_match_method = catalog_match.method
                record.catalog_match_key = catalog_match.matched_key
                changed += 1
                append_event(
                    session,
                    name="CandidateCatalogIdentityChanged.v1",
                    payload={
                        "candidate_id": record.id,
                        "release_id": record.release_id,
                        "episode_key": record.episode_key,
                        "previous_anime_id": previous_anime_id,
                        "anime_id": catalog_match.anime_id,
                        "previous_status": previous_status,
                        "status": catalog_match.status,
                    },
                )
                if catalog_match.anime_id is not None:
                    append_event(
                        session,
                        name="CandidateEvaluated.v1",
                        payload={
                            "candidate_id": record.id,
                            "release_id": record.release_id,
                            "episode_key": record.episode_key,
                            "trigger": "catalog_match",
                        },
                    )
        return changed

    def _resolve_catalog_match(self, titles: tuple[str, ...]) -> CatalogTitleMatch:
        if not titles:
            return CatalogTitleMatch("unmatched", None, None, None)
        return self._catalog.resolve_titles(list(titles))

    @staticmethod
    def _parse_source(
        source: ReleaseRecognitionSource,
    ) -> tuple[ParsedReleaseTitle, tuple[str, ...]]:
        parsed = parse_release_title(source.title)
        if source.feed_source_type != "single_anime":
            return parsed, extract_series_titles(parsed.source_title)

        declared_title = source.feed_name.strip()[:300]
        declared_key = normalize_series_key(declared_title)
        if not declared_key:
            return parsed, extract_series_titles(parsed.source_title)
        confidence = MatchConfidence.HIGH if parsed.episode_key else MatchConfidence.LOW
        reason_code = "feed_declared_anime_episode" if parsed.episode_key else parsed.reason_code
        return (
            replace(
                parsed,
                series_title=declared_title,
                series_key=declared_key,
                confidence=confidence,
                reason_code=reason_code,
            ),
            (declared_title,),
        )

    def recognize(self, release_id: str, feed_entry_id: str) -> str | None:
        source = self._sources.get_recognition_source(release_id, feed_entry_id)
        if source is None:
            return None
        parsed, title_variants = self._parse_source(source)
        catalog_match = self._resolve_catalog_match(title_variants)
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
                        trigger="initial",
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
                    .on_conflict_do_nothing(
                        index_elements=["feed_entry_id"],
                        index_where=MatchAttemptRecord.trigger == "initial",
                    )
                ),
            )
            if not result.rowcount:
                return session.scalar(
                    select(CandidateRecord.id).where(
                        CandidateRecord.release_id == release_id,
                        CandidateRecord.superseded_by_candidate_id.is_(None),
                    )
                )

            active = session.scalar(
                select(CandidateRecord).where(
                    CandidateRecord.release_id == release_id,
                    CandidateRecord.superseded_by_candidate_id.is_(None),
                )
            )
            active_source = None
            if active is not None:
                active_attempt = session.get(MatchAttemptRecord, active.attempt_id)
                if active_attempt is not None:
                    active_source = self._sources.get_recognition_source(
                        release_id, active_attempt.feed_entry_id
                    )
            active_was_manually_reviewed = (
                active is not None
                and session.scalar(
                    select(ManualActionRecord.id)
                    .where(ManualActionRecord.candidate_id == active.id)
                    .limit(1)
                )
                is not None
            )
            single_source_adoptable = (
                source.feed_source_type == "single_anime"
                and active is not None
                and not active_was_manually_reviewed
                and (active_source is None or active_source.feed_source_type != "single_anime")
                and parsed.confidence != MatchConfidence.LOW
                and all(
                    (
                        parsed.series_title,
                        parsed.series_key,
                        parsed.episode_start,
                        parsed.episode_key,
                    )
                )
            )
            if single_source_adoptable:
                assert active is not None
                candidate_id = self._supersede_candidate(
                    session,
                    release_id=release_id,
                    attempt_id=attempt_id,
                    parsed=parsed,
                    title_variants=title_variants,
                    catalog_match=catalog_match,
                    source_automation_eligible=source.automation_eligible,
                    first_seen_at=source.first_seen_at,
                    previous=active,
                    superseded_at=now,
                )
            else:
                candidate_id = self._create_candidate(
                    session,
                    release_id=release_id,
                    attempt_id=attempt_id,
                    parsed=parsed,
                    title_variants=title_variants,
                    catalog_match=catalog_match,
                    source_automation_eligible=source.automation_eligible,
                    first_seen_at=source.first_seen_at,
                )
                conflicting_single_sources = (
                    source.feed_source_type == "single_anime"
                    and active is not None
                    and active_source is not None
                    and active_source.feed_source_type == "single_anime"
                    and active.series_key != parsed.series_key
                )
                if conflicting_single_sources:
                    assert active is not None
                    append_event(
                        session,
                        name="ManualConfirmationRequired.v1",
                        payload={
                            "candidate_id": active.id,
                            "release_id": release_id,
                            "reason_code": "conflicting_single_anime_feeds",
                        },
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

    def rerun_release(
        self, release_id: str, *, feed_entry_id: str | None = None
    ) -> RecognitionRerun:
        now = self._clock()
        with self._session_factory.begin() as session:
            active = session.scalar(
                select(CandidateRecord).where(
                    CandidateRecord.release_id == release_id,
                    CandidateRecord.superseded_by_candidate_id.is_(None),
                )
            )
            previous_attempt = (
                session.get(MatchAttemptRecord, active.attempt_id)
                if active is not None
                else session.scalar(
                    select(MatchAttemptRecord)
                    .where(MatchAttemptRecord.release_id == release_id)
                    .order_by(MatchAttemptRecord.parsed_at.desc(), MatchAttemptRecord.id.desc())
                    .limit(1)
                )
            )
            if previous_attempt is None:
                raise CandidateNotFoundError(release_id)
            source_feed_entry_id = feed_entry_id or previous_attempt.feed_entry_id
            source = self._sources.get_recognition_source(release_id, source_feed_entry_id)
            if source is None:
                raise CandidateNotFoundError(release_id)

            parsed, title_variants = self._parse_source(source)
            catalog_match = self._resolve_catalog_match(title_variants)
            attempt_id = new_id()
            parsed_at = max(now, previous_attempt.parsed_at + timedelta(microseconds=1))
            session.add(
                MatchAttemptRecord(
                    id=attempt_id,
                    release_id=release_id,
                    feed_entry_id=source_feed_entry_id,
                    trigger="explicit_rerun",
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
                    parsed_at=parsed_at,
                )
            )
            previous_candidate_id = active.id if active is not None else None
            candidate_id = previous_candidate_id
            candidate_changed = False
            candidate_adopted = False
            structurally_valid = all(
                (parsed.series_title, parsed.series_key, parsed.episode_start, parsed.episode_key)
            )
            safely_adoptable = structurally_valid and parsed.confidence != MatchConfidence.LOW
            unchanged = active is not None and (
                self._attempt_matches_parsed(previous_attempt, parsed)
                or self._candidate_matches_parsed(active, parsed)
            )

            if safely_adoptable and not unchanged:
                candidate_id = self._supersede_candidate(
                    session,
                    release_id=release_id,
                    attempt_id=attempt_id,
                    parsed=parsed,
                    title_variants=title_variants,
                    catalog_match=catalog_match,
                    source_automation_eligible=source.automation_eligible,
                    first_seen_at=source.first_seen_at,
                    previous=active,
                    superseded_at=now,
                )
                candidate_changed = True
                candidate_adopted = True
            elif not safely_adoptable and active is None:
                append_event(
                    session,
                    name="ReleaseMappingRequired.v1",
                    payload={"release_id": release_id, "reason_code": parsed.reason_code},
                )

            record_event(
                session,
                event_type="recognition.release_rerun",
                entity_type="release",
                entity_id=release_id,
                payload={
                    "attempt_id": attempt_id,
                    "parser_version": parsed.parser_version,
                    "confidence": parsed.confidence.value,
                    "reason_code": parsed.reason_code,
                    "candidate_id": candidate_id,
                    "previous_candidate_id": previous_candidate_id,
                    "candidate_changed": candidate_changed,
                    "candidate_adopted": candidate_adopted,
                },
            )

        return RecognitionRerun(
            attempt_id=attempt_id,
            release_id=release_id,
            parser_version=parsed.parser_version,
            parsed_at=parsed_at,
            confidence=parsed.confidence.value,
            reason_code=parsed.reason_code,
            candidate_id=candidate_id,
            previous_candidate_id=previous_candidate_id,
            candidate_changed=candidate_changed,
            candidate_adopted=candidate_adopted,
        )

    def _supersede_candidate(
        self,
        session: Session,
        *,
        release_id: str,
        attempt_id: str,
        parsed: ParsedReleaseTitle,
        title_variants: tuple[str, ...],
        catalog_match: CatalogTitleMatch,
        source_automation_eligible: bool,
        first_seen_at: datetime,
        previous: CandidateRecord | None,
        superseded_at: datetime,
    ) -> str:
        assert parsed.series_title is not None
        assert parsed.series_key is not None
        assert parsed.episode_start is not None
        assert parsed.episode_key is not None
        candidate_id = new_id()
        if previous is not None:
            previous.superseded_by_candidate_id = candidate_id
            previous.superseded_at = superseded_at
            session.flush()
        recognition_eligible = (
            source_automation_eligible and parsed.confidence == MatchConfidence.HIGH
        )
        session.add(
            CandidateRecord(
                id=candidate_id,
                release_id=release_id,
                attempt_id=attempt_id,
                supersedes_candidate_id=previous.id if previous is not None else None,
                source_title=parsed.source_title,
                series_title=parsed.series_title,
                title_variants=list(title_variants),
                series_key=parsed.series_key,
                anime_id=catalog_match.anime_id,
                catalog_match_status=catalog_match.status,
                catalog_match_method=catalog_match.method,
                catalog_match_key=catalog_match.matched_key,
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
        )
        if previous is not None:
            append_event(
                session,
                name="CandidateSuperseded.v1",
                payload={
                    "release_id": release_id,
                    "previous_candidate_id": previous.id,
                    "candidate_id": candidate_id,
                    "previous_series_key": previous.series_key,
                    "previous_episode_key": previous.episode_key,
                    "episode_key": parsed.episode_key,
                    "trigger": "parser_rerun",
                },
            )
        append_event(
            session,
            name="CandidateEvaluated.v1",
            payload={
                "candidate_id": candidate_id,
                "release_id": release_id,
                "episode_key": parsed.episode_key,
                "trigger": "parser_rerun",
            },
        )
        if not recognition_eligible:
            append_event(
                session,
                name="ManualConfirmationRequired.v1",
                payload={"candidate_id": candidate_id, "release_id": release_id},
            )
        return candidate_id

    def _create_candidate(
        self,
        session: Session,
        *,
        release_id: str,
        attempt_id: str,
        parsed: ParsedReleaseTitle,
        title_variants: tuple[str, ...],
        catalog_match: CatalogTitleMatch,
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
                    title_variants=list(title_variants),
                    series_key=parsed.series_key,
                    anime_id=catalog_match.anime_id,
                    catalog_match_status=catalog_match.status,
                    catalog_match_method=catalog_match.method,
                    catalog_match_key=catalog_match.matched_key,
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
            identity = (
                f"anime:{record.anime_id}"
                if record.anime_id is not None
                else "title:"
                + title_variant_signature(record.title_variants or [record.series_title])
            )
            grouped[(identity, record.episode_key)].append(record)

        references = self._sources.get_references({record.release_id for record in records})
        groups = [
            self._to_group(key, candidates, references) for key, candidates in grouped.items()
        ]
        groups.sort(key=lambda group: (group.latest_seen_at, group.key), reverse=True)
        return groups[:limit]

    def list_unmatched(self, *, limit: int = 100) -> list[UnmatchedRelease]:
        with self._session_factory() as session:
            later_attempt = aliased(MatchAttemptRecord)
            latest_attempt_id = (
                select(later_attempt.id)
                .where(later_attempt.release_id == MatchAttemptRecord.release_id)
                .order_by(later_attempt.parsed_at.desc(), later_attempt.id.desc())
                .limit(1)
                .correlate(MatchAttemptRecord)
                .scalar_subquery()
            )
            active_candidate_exists = select(CandidateRecord.id).where(
                CandidateRecord.release_id == MatchAttemptRecord.release_id,
                CandidateRecord.superseded_by_candidate_id.is_(None),
            )
            dismissal_exists = select(DismissedReleaseRecord.release_id).where(
                DismissedReleaseRecord.release_id == MatchAttemptRecord.release_id
            )
            statement = (
                select(MatchAttemptRecord)
                .where(
                    MatchAttemptRecord.confidence == MatchConfidence.LOW.value,
                    MatchAttemptRecord.id == latest_attempt_id,
                    ~active_candidate_exists.exists(),
                    ~dismissal_exists.exists(),
                )
                .order_by(MatchAttemptRecord.parsed_at.desc())
                .limit(min(max(limit, 1), 500))
            )
            records = list(session.scalars(statement))
            references = self._sources.get_references({record.release_id for record in records})
            unmatched: list[UnmatchedRelease] = []
            for record in records:
                reference = references.get(record.release_id)
                unmatched.append(
                    UnmatchedRelease(
                        id=record.id,
                        release_id=record.release_id,
                        source_title=record.source_title,
                        confidence=record.confidence,
                        reason_code=record.reason_code,
                        content_kind=record.content_kind,
                        parsed_at=record.parsed_at,
                        source_url=reference.source_url if reference is not None else None,
                    )
                )
            return unmatched

    def dismiss_release(self, release_id: str) -> None:
        now = self._clock()
        with self._session_factory.begin() as session:
            attempt = session.scalar(
                select(MatchAttemptRecord)
                .where(MatchAttemptRecord.release_id == release_id)
                .order_by(MatchAttemptRecord.parsed_at.desc(), MatchAttemptRecord.id.desc())
                .limit(1)
            )
            if attempt is None:
                raise CandidateNotFoundError(release_id)
            active_candidate = session.scalar(
                select(CandidateRecord.id).where(
                    CandidateRecord.release_id == release_id,
                    CandidateRecord.superseded_by_candidate_id.is_(None),
                )
            )
            if active_candidate is not None or attempt.confidence != MatchConfidence.LOW.value:
                raise ReleaseDismissError("only unmatched releases can be dismissed")
            result = cast(
                CursorResult[object],
                session.execute(
                    insert(DismissedReleaseRecord)
                    .values(release_id=release_id, attempt_id=attempt.id, created_at=now)
                    .on_conflict_do_nothing(index_elements=["release_id"])
                ),
            )
            if result.rowcount:
                record_event(
                    session,
                    event_type="recognition.release_dismissed",
                    entity_type="release",
                    entity_id=release_id,
                    payload={"attempt_id": attempt.id, "reason_code": attempt.reason_code},
                )

    @staticmethod
    def _attempt_matches_parsed(attempt: MatchAttemptRecord, parsed: ParsedReleaseTitle) -> bool:
        return (
            attempt.source_title,
            attempt.release_group,
            attempt.series_title,
            attempt.series_key,
            attempt.season,
            attempt.episode_start,
            attempt.episode_end,
            attempt.episode_key,
            attempt.resolution,
            attempt.video_codec,
            attempt.subtitle_language,
            attempt.revision,
            attempt.content_kind,
            attempt.confidence,
            attempt.reason_code,
        ) == (
            parsed.source_title,
            parsed.release_group,
            parsed.series_title,
            parsed.series_key,
            parsed.season,
            parsed.episode_start,
            parsed.episode_end,
            parsed.episode_key,
            parsed.resolution,
            parsed.video_codec,
            parsed.subtitle_language,
            parsed.revision,
            parsed.content_kind.value,
            parsed.confidence.value,
            parsed.reason_code,
        )

    @staticmethod
    def _candidate_matches_parsed(candidate: CandidateRecord, parsed: ParsedReleaseTitle) -> bool:
        return (
            candidate.source_title,
            candidate.release_group,
            candidate.series_title,
            candidate.series_key,
            candidate.season,
            candidate.episode_start,
            candidate.episode_end,
            candidate.episode_key,
            candidate.resolution,
            candidate.video_codec,
            candidate.subtitle_language,
            candidate.revision,
            candidate.content_kind,
            candidate.confidence,
        ) == (
            parsed.source_title,
            parsed.release_group,
            parsed.series_title,
            parsed.series_key,
            parsed.season,
            parsed.episode_start,
            parsed.episode_end,
            parsed.episode_key,
            parsed.resolution,
            parsed.video_codec,
            parsed.subtitle_language,
            parsed.revision,
            parsed.content_kind.value,
            parsed.confidence.value,
        )

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
        catalog_match = self._catalog.resolve_titles([title])
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
                    title_variants=[title],
                    series_key=series_key,
                    anime_id=catalog_match.anime_id,
                    catalog_match_status=catalog_match.status,
                    catalog_match_method=catalog_match.method,
                    catalog_match_key=catalog_match.matched_key,
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
            if record is None:
                return None
            reference = self._sources.get_references({record.release_id}).get(record.release_id)
            return self._to_candidate(record, reference)

    def list_candidates_for_anime_id(self, anime_id: str) -> list[Candidate]:
        if not anime_id:
            return []
        with self._session_factory() as session:
            records = list(
                session.scalars(
                    select(CandidateRecord)
                    .where(
                        CandidateRecord.anime_id == anime_id,
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
    def _to_group(
        key: tuple[str, str],
        records: list[CandidateRecord],
        references: dict[str, ReleaseReference],
    ) -> EpisodeGroup:
        series_identity, episode_key = key
        candidates = [
            RecognitionService._to_candidate(record, references.get(record.release_id))
            for record in records
        ]
        latest_seen_at = max(candidate.first_seen_at for candidate in candidates)
        known_seasons = {
            candidate.season for candidate in candidates if candidate.season is not None
        }
        season = known_seasons.pop() if len(known_seasons) == 1 else None
        return EpisodeGroup(
            key=f"{series_identity}:{episode_key}",
            series_title=records[0].series_title,
            series_key=records[0].series_key,
            series_identity=series_identity,
            anime_id=records[0].anime_id,
            catalog_match_status=records[0].catalog_match_status,
            season=season,
            episode_key=episode_key,
            candidate_count=len(candidates),
            candidates=candidates,
            latest_seen_at=latest_seen_at,
        )

    @staticmethod
    def _to_candidate(
        record: CandidateRecord, reference: ReleaseReference | None = None
    ) -> Candidate:
        return Candidate(
            id=record.id,
            release_id=record.release_id,
            source_title=record.source_title,
            series_title=record.series_title,
            title_variants=list(record.title_variants or [record.series_title]),
            series_key=record.series_key,
            anime_id=record.anime_id,
            catalog_match_status=record.catalog_match_status,
            catalog_match_method=record.catalog_match_method,
            catalog_match_key=record.catalog_match_key,
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
            source_url=reference.source_url if reference is not None else None,
        )
