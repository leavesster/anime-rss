from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from anime_rss.modules.operations.api import ClaimedJob


def _empty_mapping() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class JobSchedule:
    job_kind: str
    dedupe_key: str
    due_at: datetime
    payload: dict[str, Any] = field(default_factory=_empty_mapping)
    payload_version: int = 1
    authoritative_due_at: bool = False


@dataclass(frozen=True, slots=True)
class JobResult:
    next_due_at: datetime | None
    details: dict[str, Any] = field(default_factory=_empty_mapping)


JobHandler = Callable[[ClaimedJob], JobResult]
ScheduleSource = Callable[[], list[JobSchedule]]


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    key: str
    label: str
    status: str
    summary: str
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FailedWork:
    key: str
    kind: str
    title: str
    detail: str
    error_code: str | None
    attention_kind: str
    occurred_at: datetime | None
    action_path: str | None = None


class DiagnosticsSource(Protocol):
    def dependencies(self) -> list[DependencyStatus]: ...

    def failed_work(self, *, limit: int) -> list[FailedWork]: ...
