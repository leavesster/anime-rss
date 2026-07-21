from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from anime_rss.infrastructure.events import IntegrationEvent, append_event
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import Clock, utc_now
from anime_rss.modules.audit.api import record_event
from anime_rss.modules.recognition.api import Candidate
from anime_rss.modules.selection.domain import (
    CandidateEvaluation,
    CandidateFacts,
    SelectionRules,
    evaluate_candidate,
    first_comparison_field,
)
from anime_rss.modules.selection.persistence import (
    DecisionRecord,
    EpisodeSlotRecord,
    EvaluationRecord,
    ManualActionRecord,
)
from anime_rss.modules.subscriptions.api import SelectionSubscription


class RecognitionQueries(Protocol):
    def get_candidate(self, candidate_id: str) -> Candidate | None: ...

    def list_candidates_for_series_keys(self, series_keys: set[str]) -> list[Candidate]: ...


class SubscriptionQueries(Protocol):
    def list_matching_for_selection(self, series_key: str) -> list[SelectionSubscription]: ...

    def get_for_selection(self, subscription_id: str) -> SelectionSubscription | None: ...


@dataclass(frozen=True, slots=True)
class EpisodeSlot:
    id: str
    subscription_id: str
    anime_title: str
    episode_key: str
    state: str
    fallback_deadline: datetime | None
    best_candidate_id: str | None
    selected_decision_id: str | None
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Decision:
    id: str
    subscription_id: str
    anime_title: str
    episode_key: str
    candidate_id: str
    release_id: str
    kind: str
    reason: dict[str, Any]
    candidate_snapshot: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PreviewCandidate:
    candidate_id: str
    source_title: str
    release_group: str | None
    eligible: bool
    preferred: bool
    rank: list[int | str]
    first_loss_field: str | None
    rejection_reasons: list[str]


@dataclass(frozen=True, slots=True)
class BackfillPreview:
    episode_key: str
    selected_candidate_id: str | None
    candidates: list[PreviewCandidate]


@dataclass(frozen=True, slots=True)
class ManualAction:
    id: str
    subscription_id: str
    slot_id: str | None
    episode_key: str
    candidate_id: str | None
    release_id: str | None
    action: str
    reason: dict[str, Any]
    created_at: datetime


class SelectionConflictError(RuntimeError):
    pass


class SelectionCommandError(ValueError):
    pass


class SelectionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        recognition: RecognitionQueries,
        subscriptions: SubscriptionQueries,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._recognition = recognition
        self._subscriptions = subscriptions
        self._clock = clock

    def handle_candidate_evaluated(self, event: IntegrationEvent) -> None:
        if event.name != "CandidateEvaluated.v1" or event.version != 1:
            return
        candidate_id = event.payload.get("candidate_id")
        if not isinstance(candidate_id, str):
            return
        candidate = self._recognition.get_candidate(candidate_id)
        if candidate is None:
            return
        for subscription in self._subscriptions.list_matching_for_selection(candidate.series_key):
            self._evaluate_automatic(subscription, candidate)

    def handle_candidate_remapped(self, event: IntegrationEvent) -> None:
        if event.name != "CandidateRemapped.v1" or event.version != 1:
            return
        previous_id = event.payload.get("previous_candidate_id")
        candidate_id = event.payload.get("candidate_id")
        release_id = event.payload.get("release_id")
        if not all(isinstance(value, str) for value in (previous_id, candidate_id, release_id)):
            return
        now = self._clock()
        with self._session_factory.begin() as session:
            slots = list(
                session.scalars(
                    select(EpisodeSlotRecord).where(
                        EpisodeSlotRecord.best_candidate_id == previous_id
                    )
                )
            )
            for slot in slots:
                action = (
                    "candidate_reassigned_after_decision"
                    if slot.selected_decision_id is not None
                    else "candidate_reassigned"
                )
                session.add(
                    ManualActionRecord(
                        id=new_id(),
                        subscription_id=slot.subscription_id,
                        slot_id=slot.id,
                        episode_key=slot.episode_key,
                        candidate_id=candidate_id,
                        release_id=release_id,
                        action=action,
                        reason={
                            "previous_candidate_id": previous_id,
                            "candidate_id": candidate_id,
                            "previous_series_key": event.payload.get("previous_series_key"),
                            "previous_episode_key": event.payload.get("previous_episode_key"),
                            "episode_key": event.payload.get("episode_key"),
                        },
                        created_at=now,
                    )
                )
                if slot.selected_decision_id is None:
                    slot.state = "open"
                    slot.best_candidate_id = None
                    slot.fallback_deadline = None
                    slot.version += 1
                    slot.updated_at = now

    def process_due(self, *, limit: int = 100) -> int:
        now = self._clock()
        with self._session_factory() as session:
            slot_ids = list(
                session.scalars(
                    select(EpisodeSlotRecord.id)
                    .where(
                        EpisodeSlotRecord.state == "waiting_fallback",
                        EpisodeSlotRecord.fallback_deadline <= now,
                    )
                    .order_by(EpisodeSlotRecord.fallback_deadline, EpisodeSlotRecord.id)
                    .limit(min(max(limit, 1), 500))
                )
            )
        committed = 0
        for slot_id in slot_ids:
            if self._commit_due_slot(slot_id, now):
                committed += 1
        return committed

    def list_slots(
        self, *, subscription_id: str | None = None, limit: int = 200
    ) -> list[EpisodeSlot]:
        with self._session_factory() as session:
            statement = select(EpisodeSlotRecord)
            if subscription_id is not None:
                statement = statement.where(EpisodeSlotRecord.subscription_id == subscription_id)
            records = list(
                session.scalars(
                    statement.order_by(
                        EpisodeSlotRecord.updated_at.desc(), EpisodeSlotRecord.id
                    ).limit(min(max(limit, 1), 500))
                )
            )
            return [self._to_slot(record) for record in records]

    def list_decisions(
        self, *, subscription_id: str | None = None, limit: int = 200
    ) -> list[Decision]:
        with self._session_factory() as session:
            statement = select(DecisionRecord, EpisodeSlotRecord.anime_title).join(
                EpisodeSlotRecord, EpisodeSlotRecord.id == DecisionRecord.slot_id
            )
            if subscription_id is not None:
                statement = statement.where(DecisionRecord.subscription_id == subscription_id)
            statement = statement.order_by(
                DecisionRecord.created_at.desc(), DecisionRecord.id
            ).limit(min(max(limit, 1), 500))
            return [
                Decision(
                    id=record.id,
                    subscription_id=record.subscription_id,
                    anime_title=anime_title,
                    episode_key=record.episode_key,
                    candidate_id=record.candidate_id,
                    release_id=record.release_id,
                    kind=record.kind,
                    reason=record.reason,
                    candidate_snapshot=record.candidate_snapshot,
                    created_at=record.created_at,
                )
                for record, anime_title in session.execute(statement)
            ]

    def preview_backfill(self, subscription_id: str) -> list[BackfillPreview]:
        subscription = self._subscriptions.get_for_selection(subscription_id)
        if subscription is None:
            raise LookupError("subscription not found")
        candidates = self._recognition.list_candidates_for_series_keys(set(subscription.match_keys))
        rejected = self._rejected_candidate_ids(subscription_id)
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.episode_key].append(candidate)
        return [
            self._preview_group(subscription, episode_key, items, rejected)
            for episode_key, items in sorted(grouped.items(), key=lambda item: item[0])
        ]

    def commit_backfill(self, subscription_id: str, episode_keys: list[str]) -> int:
        subscription = self._subscriptions.get_for_selection(subscription_id)
        if subscription is None:
            raise LookupError("subscription not found")
        wanted = set(episode_keys)
        previews = [
            preview
            for preview in self.preview_backfill(subscription_id)
            if preview.episode_key in wanted
        ]
        committed = 0
        for preview in previews:
            if preview.selected_candidate_id is None:
                continue
            candidate = self._recognition.get_candidate(preview.selected_candidate_id)
            if candidate is None:
                continue
            evaluation = evaluate_candidate(self._facts(candidate), self._rules(subscription))
            if self._commit_backfill_candidate(subscription, candidate, evaluation):
                committed += 1
        return committed

    def select_candidate(
        self,
        subscription_id: str,
        candidate_id: str,
        *,
        replace_existing: bool = False,
        override_filters: bool = False,
    ) -> str:
        subscription, candidate = self._validated_candidate(subscription_id, candidate_id)
        evaluation = evaluate_candidate(self._facts(candidate), self._rules(subscription))
        if not evaluation.eligible and not override_filters:
            reasons = [
                str(item["reason"])
                for item in evaluation.hard_filter_results
                if not bool(item["passed"])
            ]
            raise SelectionCommandError(
                "candidate is rejected by hard filters: " + ", ".join(reasons)
            )
        now = self._clock()
        with self._session_factory.begin() as session:
            self._persist_evaluation(
                session,
                subscription,
                candidate,
                evaluation,
                trigger="manual",
                now=now,
            )
            slot = self._get_or_create_slot(session, subscription, candidate.episode_key, now)
            current = (
                session.get(DecisionRecord, slot.selected_decision_id)
                if slot.selected_decision_id is not None
                else None
            )
            if current is not None and current.candidate_id == candidate.id:
                self._record_manual_action(
                    session,
                    subscription_id=subscription.id,
                    slot=slot,
                    candidate=candidate,
                    action="selected",
                    reason={"idempotent": True},
                    now=now,
                )
                return current.id
            if current is not None and not replace_existing:
                raise SelectionConflictError(
                    "episode already has a decision; replacement is required"
                )
            kind = "selected_manual_replacement" if current is not None else "selected_manual"
            decision_id = self._commit_decision(
                session,
                slot,
                subscription,
                candidate,
                evaluation,
                kind=kind,
                now=now,
                trigger="manual",
                supersede_current=current is not None,
            )
            self._record_manual_action(
                session,
                subscription_id=subscription.id,
                slot=slot,
                candidate=candidate,
                action="replaced" if current is not None else "selected",
                reason={
                    "decision_id": decision_id,
                    "superseded_decision_id": current.id if current is not None else None,
                    "override_filters": override_filters,
                },
                now=now,
            )
            return decision_id

    def reject_candidate(self, subscription_id: str, candidate_id: str) -> ManualAction:
        subscription, candidate = self._validated_candidate(subscription_id, candidate_id)
        now = self._clock()
        with self._session_factory.begin() as session:
            slot = self._get_or_create_slot(session, subscription, candidate.episode_key, now)
            if slot.selected_decision_id is not None:
                raise SelectionConflictError(
                    "reset the existing decision before rejecting its candidate"
                )
            action = self._record_manual_action(
                session,
                subscription_id=subscription.id,
                slot=slot,
                candidate=candidate,
                action="rejected",
                reason={"scope": "subscription"},
                now=now,
            )
            if slot.best_candidate_id == candidate.id:
                slot.best_candidate_id = None
                slot.fallback_deadline = None
                slot.state = "open"
                slot.version += 1
                slot.updated_at = now
            action_id = action.id
        return self.get_manual_action(action_id)

    def reset_episode(self, subscription_id: str, episode_key: str) -> ManualAction:
        now = self._clock()
        with self._session_factory.begin() as session:
            slot = session.scalar(
                select(EpisodeSlotRecord).where(
                    EpisodeSlotRecord.subscription_id == subscription_id,
                    EpisodeSlotRecord.episode_key == episode_key,
                )
            )
            if slot is None or slot.selected_decision_id is None:
                raise SelectionConflictError("episode has no decision to reset")
            previous_decision_id = slot.selected_decision_id
            action = self._record_manual_action(
                session,
                subscription_id=subscription_id,
                slot=slot,
                candidate=None,
                action="reset",
                reason={"previous_decision_id": previous_decision_id},
                now=now,
            )
            slot.state = "open"
            slot.selected_decision_id = None
            slot.best_candidate_id = None
            slot.fallback_deadline = None
            slot.version += 1
            slot.updated_at = now
            action_id = action.id
        return self.get_manual_action(action_id)

    def mark_acquired_elsewhere(self, subscription_id: str, episode_key: str) -> ManualAction:
        subscription = self._subscriptions.get_for_selection(subscription_id)
        if subscription is None:
            raise LookupError("subscription not found")
        value = episode_key.strip()
        if not value or len(value) > 52:
            raise SelectionCommandError("episode key is required")
        now = self._clock()
        with self._session_factory.begin() as session:
            slot = self._get_or_create_slot(session, subscription, value, now)
            if slot.selected_decision_id is not None:
                raise SelectionConflictError("episode already has a download decision")
            action = self._record_manual_action(
                session,
                subscription_id=subscription_id,
                slot=slot,
                candidate=None,
                action="acquired_elsewhere",
                reason={},
                now=now,
            )
            slot.state = "acquired_elsewhere"
            slot.best_candidate_id = None
            slot.fallback_deadline = None
            slot.version += 1
            slot.updated_at = now
            action_id = action.id
        return self.get_manual_action(action_id)

    def list_manual_actions(
        self, *, subscription_id: str | None = None, limit: int = 200
    ) -> list[ManualAction]:
        with self._session_factory() as session:
            statement = select(ManualActionRecord)
            if subscription_id is not None:
                statement = statement.where(ManualActionRecord.subscription_id == subscription_id)
            records = list(
                session.scalars(
                    statement.order_by(
                        ManualActionRecord.created_at.desc(), ManualActionRecord.id
                    ).limit(min(max(limit, 1), 500))
                )
            )
            return [self._to_manual_action(record) for record in records]

    def get_manual_action(self, action_id: str) -> ManualAction:
        with self._session_factory() as session:
            record = session.get(ManualActionRecord, action_id)
            if record is None:
                raise LookupError("manual action not found")
            return self._to_manual_action(record)

    def _validated_candidate(
        self, subscription_id: str, candidate_id: str
    ) -> tuple[SelectionSubscription, Candidate]:
        subscription = self._subscriptions.get_for_selection(subscription_id)
        if subscription is None:
            raise LookupError("subscription not found")
        candidate = self._recognition.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("candidate not found")
        if candidate.series_key not in subscription.match_keys:
            raise SelectionCommandError("candidate does not match this subscription")
        return subscription, candidate

    @staticmethod
    def _get_or_create_slot(
        session: Session,
        subscription: SelectionSubscription,
        episode_key: str,
        now: datetime,
    ) -> EpisodeSlotRecord:
        slot = session.scalar(
            select(EpisodeSlotRecord).where(
                EpisodeSlotRecord.subscription_id == subscription.id,
                EpisodeSlotRecord.episode_key == episode_key,
            )
        )
        if slot is None:
            slot = EpisodeSlotRecord(
                id=new_id(),
                subscription_id=subscription.id,
                anime_title=subscription.anime_title,
                episode_key=episode_key,
                state="open",
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(slot)
            session.flush()
        return slot

    @staticmethod
    def _record_manual_action(
        session: Session,
        *,
        subscription_id: str,
        slot: EpisodeSlotRecord,
        candidate: Candidate | None,
        action: str,
        reason: dict[str, Any],
        now: datetime,
    ) -> ManualActionRecord:
        record = ManualActionRecord(
            id=new_id(),
            subscription_id=subscription_id,
            slot_id=slot.id,
            episode_key=slot.episode_key,
            candidate_id=candidate.id if candidate is not None else None,
            release_id=candidate.release_id if candidate is not None else None,
            action=action,
            reason=reason,
            created_at=now,
        )
        session.add(record)
        record_event(
            session,
            event_type=f"selection.manual_{action}",
            entity_type="episode_slot",
            entity_id=slot.id,
            payload={
                "subscription_id": subscription_id,
                "episode_key": slot.episode_key,
                "candidate_id": record.candidate_id,
            },
        )
        return record

    @staticmethod
    def _candidate_is_rejected(session: Session, subscription_id: str, candidate_id: str) -> bool:
        latest = session.scalar(
            select(ManualActionRecord)
            .where(
                ManualActionRecord.subscription_id == subscription_id,
                ManualActionRecord.candidate_id == candidate_id,
            )
            .order_by(ManualActionRecord.created_at.desc(), ManualActionRecord.id.desc())
            .limit(1)
        )
        return latest is not None and latest.action == "rejected"

    def _rejected_candidate_ids(self, subscription_id: str) -> set[str]:
        with self._session_factory() as session:
            candidate_ids = set(
                session.scalars(
                    select(ManualActionRecord.candidate_id)
                    .where(
                        ManualActionRecord.subscription_id == subscription_id,
                        ManualActionRecord.candidate_id.is_not(None),
                    )
                    .distinct()
                )
            )
            return {
                candidate_id
                for candidate_id in candidate_ids
                if candidate_id is not None
                and self._candidate_is_rejected(session, subscription_id, candidate_id)
            }

    def _evaluate_automatic(
        self, subscription: SelectionSubscription, candidate: Candidate
    ) -> None:
        if subscription.state in {"paused", "archived"}:
            return
        if candidate.first_seen_at < subscription.activation_at:
            return
        rules = self._rules(subscription)
        evaluation = evaluate_candidate(self._facts(candidate), rules)
        now = self._clock()
        with self._session_factory.begin() as session:
            evaluation_record = self._persist_evaluation(
                session,
                subscription,
                candidate,
                evaluation,
                trigger="automatic",
                now=now,
            )
            if self._candidate_is_rejected(session, subscription.id, candidate.id):
                return
            if not evaluation.eligible:
                if candidate.confidence != "high":
                    self._ensure_confirmation_slot(session, subscription, candidate, now)
                return
            slot = session.scalar(
                select(EpisodeSlotRecord).where(
                    EpisodeSlotRecord.subscription_id == subscription.id,
                    EpisodeSlotRecord.episode_key == candidate.episode_key,
                )
            )
            if slot is None and subscription.state == "completed":
                return
            if slot is None:
                slot = EpisodeSlotRecord(
                    id=new_id(),
                    subscription_id=subscription.id,
                    anime_title=subscription.anime_title,
                    episode_key=candidate.episode_key,
                    state="open",
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(slot)
                session.flush()
            if slot.state == "decided":
                self._maybe_commit_upgrade(session, slot, subscription, candidate, evaluation, now)
                return
            if subscription.state == "completed":
                return
            if evaluation.preferred:
                self._commit_decision(
                    session,
                    slot,
                    subscription,
                    candidate,
                    evaluation,
                    kind="selected_preferred",
                    now=now,
                )
                return
            if slot.best_candidate_id is None or self._is_better(
                session, evaluation_record, slot.best_candidate_id
            ):
                slot.best_candidate_id = candidate.id
            if subscription.rules.fallback_wait_minutes == 0:
                self._commit_decision(
                    session,
                    slot,
                    subscription,
                    candidate,
                    evaluation,
                    kind="selected_fallback",
                    now=now,
                )
                return
            waiting_started = slot.fallback_deadline is None
            if waiting_started:
                slot.fallback_deadline = now + timedelta(
                    minutes=subscription.rules.fallback_wait_minutes
                )
            slot.state = "waiting_fallback"
            slot.version += 1
            slot.updated_at = now
            if waiting_started:
                assert slot.fallback_deadline is not None
                append_event(
                    session,
                    name="DecisionWaitingStarted.v1",
                    payload={
                        "slot_id": slot.id,
                        "deadline": slot.fallback_deadline.isoformat(),
                    },
                )

    def _commit_due_slot(self, slot_id: str, now: datetime) -> bool:
        with self._session_factory.begin() as session:
            slot = session.get(EpisodeSlotRecord, slot_id)
            if (
                slot is None
                or slot.state != "waiting_fallback"
                or slot.fallback_deadline is None
                or slot.fallback_deadline > now
                or slot.best_candidate_id is None
            ):
                return False
            subscription = self._subscriptions.get_for_selection(slot.subscription_id)
            candidate = self._recognition.get_candidate(slot.best_candidate_id)
            if subscription is None or candidate is None or subscription.state != "following":
                return False
            if candidate.first_seen_at < subscription.activation_at:
                slot.state = "open"
                slot.fallback_deadline = None
                slot.best_candidate_id = None
                slot.version += 1
                slot.updated_at = now
                return False
            evaluation_record = session.scalar(
                select(EvaluationRecord).where(
                    EvaluationRecord.subscription_id == slot.subscription_id,
                    EvaluationRecord.candidate_id == candidate.id,
                )
            )
            if evaluation_record is None or not evaluation_record.eligible:
                return False
            if self._candidate_is_rejected(session, slot.subscription_id, candidate.id):
                slot.state = "open"
                slot.fallback_deadline = None
                slot.best_candidate_id = None
                slot.version += 1
                slot.updated_at = now
                return False
            evaluation = self._evaluation_from_record(evaluation_record)
            self._commit_decision(
                session,
                slot,
                subscription,
                candidate,
                evaluation,
                kind="selected_fallback",
                now=now,
            )
            return True

    def _commit_backfill_candidate(
        self,
        subscription: SelectionSubscription,
        candidate: Candidate,
        evaluation: CandidateEvaluation,
    ) -> bool:
        now = self._clock()
        with self._session_factory.begin() as session:
            self._persist_evaluation(
                session,
                subscription,
                candidate,
                evaluation,
                trigger="backfill",
                now=now,
            )
            slot = session.scalar(
                select(EpisodeSlotRecord).where(
                    EpisodeSlotRecord.subscription_id == subscription.id,
                    EpisodeSlotRecord.episode_key == candidate.episode_key,
                )
            )
            if slot is not None and slot.state == "decided":
                return False
            if slot is None:
                slot = EpisodeSlotRecord(
                    id=new_id(),
                    subscription_id=subscription.id,
                    anime_title=subscription.anime_title,
                    episode_key=candidate.episode_key,
                    state="open",
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(slot)
                session.flush()
            self._commit_decision(
                session,
                slot,
                subscription,
                candidate,
                evaluation,
                kind="selected_backfill",
                now=now,
            )
            return True

    def _commit_decision(
        self,
        session: Session,
        slot: EpisodeSlotRecord,
        subscription: SelectionSubscription,
        candidate: Candidate,
        evaluation: CandidateEvaluation,
        *,
        kind: str,
        now: datetime,
        trigger: str | None = None,
        supersede_current: bool = False,
    ) -> str:
        decision_id = new_id()
        supersedes_decision_id = slot.selected_decision_id if supersede_current else None
        rules_snapshot = self._rules_snapshot(subscription)
        candidate_snapshot = {
            "source_title": candidate.source_title,
            "release_group": candidate.release_group,
            "resolution": candidate.resolution,
            "video_codec": candidate.video_codec,
            "subtitle_language": candidate.subtitle_language,
            "revision": candidate.revision,
        }
        session.add(
            DecisionRecord(
                id=decision_id,
                slot_id=slot.id,
                subscription_id=subscription.id,
                episode_key=candidate.episode_key,
                candidate_id=candidate.id,
                release_id=candidate.release_id,
                kind=kind,
                reason={
                    "preferred": evaluation.preferred,
                    "rank": list(evaluation.rank),
                    "trigger": trigger
                    or ("backfill" if kind == "selected_backfill" else "automatic"),
                },
                rules_snapshot=rules_snapshot,
                candidate_snapshot=candidate_snapshot,
                created_at=now,
            )
        )
        slot.state = "decided"
        slot.best_candidate_id = candidate.id
        slot.selected_decision_id = decision_id
        slot.fallback_deadline = None
        slot.version += 1
        slot.updated_at = now
        append_event(
            session,
            name="DecisionCommitted.v1",
            payload={"decision_id": decision_id, "candidate_id": candidate.id, "kind": kind},
        )
        if supersedes_decision_id is not None:
            append_event(
                session,
                name="DownloadCancellationRequested.v1",
                payload={
                    "decision_id": supersedes_decision_id,
                    "replacement_decision_id": decision_id,
                },
            )
        append_event(
            session,
            name="DownloadRequested.v1",
            payload={
                "decision_id": decision_id,
                "release_id": candidate.release_id,
                "subscription_id": subscription.id,
                "supersedes_decision_id": supersedes_decision_id,
            },
        )
        record_event(
            session,
            event_type="selection.decision_committed",
            entity_type="decision",
            entity_id=decision_id,
            payload={"kind": kind, "candidate_id": candidate.id},
        )
        return decision_id

    def _maybe_commit_upgrade(
        self,
        session: Session,
        slot: EpisodeSlotRecord,
        subscription: SelectionSubscription,
        candidate: Candidate,
        evaluation: CandidateEvaluation,
        now: datetime,
    ) -> None:
        if not evaluation.eligible or slot.selected_decision_id is None:
            return
        current = session.get(DecisionRecord, slot.selected_decision_id)
        if current is None:
            return
        snapshot = current.candidate_snapshot
        current_group = snapshot.get("release_group")
        current_revision = snapshot.get("revision", 1)
        if (
            isinstance(current_revision, int)
            and candidate.release_group == current_group
            and candidate.revision > current_revision
        ):
            self._commit_decision(
                session,
                slot,
                subscription,
                candidate,
                evaluation,
                kind="selected_upgrade",
                now=now,
                supersede_current=True,
            )

    def _persist_evaluation(
        self,
        session: Session,
        subscription: SelectionSubscription,
        candidate: Candidate,
        evaluation: CandidateEvaluation,
        *,
        trigger: str,
        now: datetime,
    ) -> EvaluationRecord:
        evaluation_id = new_id()
        result = cast(
            CursorResult[object],
            session.execute(
                insert(EvaluationRecord)
                .values(
                    id=evaluation_id,
                    subscription_id=subscription.id,
                    candidate_id=candidate.id,
                    release_id=candidate.release_id,
                    episode_key=candidate.episode_key,
                    eligible=evaluation.eligible,
                    preferred=evaluation.preferred,
                    hard_filter_results=evaluation.hard_filter_results,
                    rank=list(evaluation.rank),
                    rules_snapshot=self._rules_snapshot(subscription),
                    evaluated_at=now,
                    trigger=trigger,
                )
                .on_conflict_do_nothing(index_elements=["subscription_id", "candidate_id"])
            ),
        )
        if result.rowcount:
            record = session.get(EvaluationRecord, evaluation_id)
        else:
            record = session.scalar(
                select(EvaluationRecord).where(
                    EvaluationRecord.subscription_id == subscription.id,
                    EvaluationRecord.candidate_id == candidate.id,
                )
            )
            assert record is not None
            record.release_id = candidate.release_id
            record.episode_key = candidate.episode_key
            record.eligible = evaluation.eligible
            record.preferred = evaluation.preferred
            record.hard_filter_results = evaluation.hard_filter_results
            record.rank = list(evaluation.rank)
            record.rules_snapshot = self._rules_snapshot(subscription)
            record.evaluated_at = now
            record.trigger = trigger
        assert record is not None
        return record

    @staticmethod
    def _ensure_confirmation_slot(
        session: Session,
        subscription: SelectionSubscription,
        candidate: Candidate,
        now: datetime,
    ) -> None:
        existing = session.scalar(
            select(EpisodeSlotRecord.id).where(
                EpisodeSlotRecord.subscription_id == subscription.id,
                EpisodeSlotRecord.episode_key == candidate.episode_key,
            )
        )
        if existing is None:
            session.add(
                EpisodeSlotRecord(
                    id=new_id(),
                    subscription_id=subscription.id,
                    anime_title=subscription.anime_title,
                    episode_key=candidate.episode_key,
                    state="needs_confirmation",
                    best_candidate_id=candidate.id,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )

    @staticmethod
    def _is_better(
        session: Session, candidate: EvaluationRecord, current_candidate_id: str
    ) -> bool:
        current = session.scalar(
            select(EvaluationRecord).where(
                EvaluationRecord.subscription_id == candidate.subscription_id,
                EvaluationRecord.candidate_id == current_candidate_id,
            )
        )
        return current is None or tuple(candidate.rank) < tuple(current.rank)

    def _preview_group(
        self,
        subscription: SelectionSubscription,
        episode_key: str,
        candidates: list[Candidate],
        rejected_candidate_ids: set[str],
    ) -> BackfillPreview:
        evaluated = [
            (candidate, evaluate_candidate(self._facts(candidate), self._rules(subscription)))
            for candidate in candidates
        ]
        evaluated.sort(key=lambda item: item[1].rank)
        winner = next(
            (
                item
                for item in evaluated
                if item[1].eligible and item[0].id not in rejected_candidate_ids
            ),
            None,
        )
        preview_candidates: list[PreviewCandidate] = []
        for candidate, evaluation in evaluated:
            reasons = [
                str(check["reason"])
                for check in evaluation.hard_filter_results
                if not bool(check["passed"])
            ]
            if candidate.id in rejected_candidate_ids:
                reasons.append("manually_rejected")
            preview_candidates.append(
                PreviewCandidate(
                    candidate_id=candidate.id,
                    source_title=candidate.source_title,
                    release_group=candidate.release_group,
                    eligible=evaluation.eligible and candidate.id not in rejected_candidate_ids,
                    preferred=evaluation.preferred,
                    rank=list(evaluation.rank),
                    first_loss_field=(
                        first_comparison_field(winner[1], evaluation)
                        if winner is not None and candidate.id != winner[0].id
                        else None
                    ),
                    rejection_reasons=reasons,
                )
            )
        return BackfillPreview(
            episode_key=episode_key,
            selected_candidate_id=winner[0].id if winner is not None else None,
            candidates=preview_candidates,
        )

    @staticmethod
    def _rules(subscription: SelectionSubscription) -> SelectionRules:
        rules = subscription.rules
        return SelectionRules(
            allowed_groups=rules.allowed_groups,
            allowed_subtitles=rules.allowed_subtitles,
            allowed_resolutions=rules.allowed_resolutions,
            allowed_codecs=rules.allowed_codecs,
            allowed_content_kinds=rules.allowed_content_kinds,
            preferred_groups=rules.preferred_groups,
            preferred_subtitles=rules.preferred_subtitles,
            preferred_resolutions=rules.preferred_resolutions,
            preferred_codecs=rules.preferred_codecs,
            fallback_wait_minutes=rules.fallback_wait_minutes,
        )

    @staticmethod
    def _rules_snapshot(subscription: SelectionSubscription) -> dict[str, Any]:
        return {"schema_version": 1, **subscription.rules.to_dict()}

    @staticmethod
    def _facts(candidate: Candidate) -> CandidateFacts:
        return CandidateFacts(
            candidate_id=candidate.id,
            release_id=candidate.release_id,
            release_group=candidate.release_group,
            subtitle_language=candidate.subtitle_language,
            resolution=candidate.resolution,
            video_codec=candidate.video_codec,
            content_kind=candidate.content_kind,
            confidence=candidate.confidence,
            recognition_eligible=candidate.recognition_eligible,
            revision=candidate.revision,
            first_seen_at=candidate.first_seen_at,
        )

    @staticmethod
    def _evaluation_from_record(record: EvaluationRecord) -> CandidateEvaluation:
        return CandidateEvaluation(
            eligible=record.eligible,
            preferred=record.preferred,
            hard_filter_results=record.hard_filter_results,
            rank=tuple(record.rank),
        )

    @staticmethod
    def _to_slot(record: EpisodeSlotRecord) -> EpisodeSlot:
        return EpisodeSlot(
            id=record.id,
            subscription_id=record.subscription_id,
            anime_title=record.anime_title,
            episode_key=record.episode_key,
            state=record.state,
            fallback_deadline=record.fallback_deadline,
            best_candidate_id=record.best_candidate_id,
            selected_decision_id=record.selected_decision_id,
            version=record.version,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_manual_action(record: ManualActionRecord) -> ManualAction:
        return ManualAction(
            id=record.id,
            subscription_id=record.subscription_id,
            slot_id=record.slot_id,
            episode_key=record.episode_key,
            candidate_id=record.candidate_id,
            release_id=record.release_id,
            action=record.action,
            reason=record.reason,
            created_at=record.created_at,
        )
