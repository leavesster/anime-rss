from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from anime_rss.modules.operations.api import JobService
from anime_rss.modules.operations.ports import DiagnosticsSource
from anime_rss.modules.operations.worker import Scheduler

router = APIRouter(prefix="/operations", tags=["operations"])


class SchedulerStateResponse(BaseModel):
    state: str
    worker_id: str
    last_cycle_started_at: datetime | None
    last_cycle_finished_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    next_wake_at: datetime | None
    updated_at: datetime


class DependencyStatusResponse(BaseModel):
    key: str
    label: str
    status: str
    summary: str
    observed_at: datetime | None


class FailedWorkResponse(BaseModel):
    key: str
    kind: str
    title: str
    detail: str
    error_code: str | None
    occurred_at: datetime | None
    action_path: str | None


class OperationsOverviewResponse(BaseModel):
    scheduler: SchedulerStateResponse | None
    dependencies: list[DependencyStatusResponse]
    failed_work: list[FailedWorkResponse]
    pending_jobs: int


class ScheduledJobResponse(BaseModel):
    id: str
    job_kind: str
    dedupe_key: str
    due_at: datetime
    attempt: int
    lease_owner: str | None
    lease_until: datetime | None
    last_error_code: str | None
    updated_at: datetime


class JobRunResponse(BaseModel):
    id: str
    job_id: str
    job_kind: str
    dedupe_key: str
    worker_id: str
    attempt: int
    status: str
    error_code: str | None
    details: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None


class RunNowResponse(BaseModel):
    processed: int


class OperationsHttpServices(Protocol):
    jobs: JobService
    diagnostics: DiagnosticsSource
    scheduler: Scheduler


def _services(request: Request) -> OperationsHttpServices:
    return cast(OperationsHttpServices, request.app.state.services)


@router.get("/overview", response_model=OperationsOverviewResponse)
def get_operations_overview(request: Request) -> OperationsOverviewResponse:
    services = _services(request)
    jobs = services.jobs.list_jobs(limit=500)
    scheduler = services.jobs.get_scheduler_state()
    return OperationsOverviewResponse(
        scheduler=(SchedulerStateResponse.model_validate(asdict(scheduler)) if scheduler else None),
        dependencies=[
            DependencyStatusResponse.model_validate(asdict(item))
            for item in services.diagnostics.dependencies()
        ],
        failed_work=[
            FailedWorkResponse.model_validate(asdict(item))
            for item in services.diagnostics.failed_work(limit=100)
        ],
        pending_jobs=len(jobs),
    )


@router.get("/jobs", response_model=list[ScheduledJobResponse])
def list_scheduled_jobs(request: Request, limit: int = 200) -> list[ScheduledJobResponse]:
    return [
        ScheduledJobResponse.model_validate(asdict(item))
        for item in _services(request).jobs.list_jobs(limit=limit)
    ]


@router.get("/runs", response_model=list[JobRunResponse])
def list_job_runs(request: Request, limit: int = 100) -> list[JobRunResponse]:
    return [
        JobRunResponse.model_validate(asdict(item))
        for item in _services(request).jobs.list_runs(limit=limit)
    ]


@router.post("/run-now", response_model=RunNowResponse)
def run_scheduler_now(request: Request) -> RunNowResponse:
    return RunNowResponse(processed=_services(request).scheduler.run_once())
