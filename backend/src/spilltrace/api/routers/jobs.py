"""Job and pipeline endpoints (FR-019, NFR-003)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, status

from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import PaginationDep, SessionDep, SettingsDep, StatusQuery
from spilltrace.api.ratelimit import JOB_LIMIT, client_key, enforce
from spilltrace.api.schemas.common import PageResponse
from spilltrace.api.schemas.jobs import JobCreate, JobOut, PipelineOut, PipelineStart
from spilltrace.core.enums import JobStatus
from spilltrace.core.errors import ConflictError, NotFoundError
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.logging import get_logger
from spilltrace.worker.pipeline import create_pipeline, pipeline_summary, runnable_jobs
from spilltrace.worker.queue import JobQueue

router = APIRouter(prefix="/api/v1", tags=["jobs"])
log = get_logger(__name__)


@router.post(
    "/cases/{case_id}/pipeline",
    response_model=PipelineOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the investigation pipeline",
)
async def start_pipeline(
    case_id: uuid.UUID,
    body: PipelineStart,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> PipelineOut:
    await enforce(JOB_LIMIT, client_key(request, str(user.id)))
    case = await CaseRepository(session).get_for_user(case_id, user)

    existing = await JobRepository(session).list_for_case(
        case_id, limit=1, offset=0, status=JobStatus.RUNNING.value
    )
    if existing.total:
        raise ConflictError(
            "A pipeline is already running for this case. Wait for it to finish or "
            "cancel it first.",
            case_id=str(case_id),
        )

    pipeline_id, jobs = await create_pipeline(
        session, case=case, mode=body.mode, stages=body.stages, params=body.params
    )
    ready = await runnable_jobs(session, pipeline_id)
    await session.commit()

    queue = JobQueue(settings)
    try:
        for job in ready:
            await queue.enqueue(job.id, priority=job.priority)
    finally:
        await queue.close()

    log.info("pipeline_started", pipeline_id=str(pipeline_id), case_id=str(case_id), mode=body.mode)
    return PipelineOut(
        pipeline_id=pipeline_id,
        case_id=case_id,
        mode=body.mode,
        jobs=[JobOut.model_validate(j) for j in jobs],
    )


@router.get("/cases/{case_id}/pipeline", summary="Pipeline status")
async def get_pipeline(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    page = await JobRepository(session).list_for_case(case_id, limit=1, offset=0)
    pipeline_ids = [j.pipeline_id for j in page.items if j.pipeline_id]
    if not pipeline_ids:
        raise NotFoundError("No pipeline has been started for this case.", case_id=str(case_id))
    return await pipeline_summary(session, pipeline_ids[0])


@router.post(
    "/cases/{case_id}/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a single stage",
)
async def create_job(
    case_id: uuid.UUID,
    body: JobCreate,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> JobOut:
    await enforce(JOB_LIMIT, client_key(request, str(user.id)))
    await CaseRepository(session).get_for_user(case_id, user)
    job = await JobRepository(session).create(
        job_type=body.job_type,
        case_id=case_id,
        payload={**body.payload, "case_id": str(case_id)},
        priority=body.priority,
        max_attempts=settings.job_max_attempts,
    )
    await session.commit()

    queue = JobQueue(settings)
    try:
        await queue.enqueue(job.id, priority=job.priority)
    finally:
        await queue.close()
    return JobOut.model_validate(job)


@router.get("/cases/{case_id}/jobs", response_model=PageResponse[JobOut])
async def list_jobs(
    case_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
    status_filter: StatusQuery = None,
) -> PageResponse[JobOut]:
    await CaseRepository(session).get_for_user(case_id, user)
    page = await JobRepository(session).list_for_case(
        case_id, limit=pagination.limit, offset=pagination.offset, status=status_filter
    )
    return PageResponse[JobOut](
        items=[JobOut.model_validate(j) for j in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> JobOut:
    job = await JobRepository(session).get(job_id)
    if job.case_id is not None:
        await CaseRepository(session).get_for_user(job.case_id, user)
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> JobOut:
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if job.case_id is not None:
        await CaseRepository(session).get_for_user(job.case_id, user)

    queue = JobQueue(settings)
    try:
        if job.status == JobStatus.RUNNING.value:
            # A running handler checks for cancellation at its next progress report.
            await queue.request_cancel(job.id)
        else:
            await repo.mark_cancelled(job)
            await session.commit()
    finally:
        await queue.close()
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> JobOut:
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if job.case_id is not None:
        await CaseRepository(session).get_for_user(job.case_id, user)
    await repo.requeue(job)
    await session.commit()

    queue = JobQueue(settings)
    try:
        await queue.enqueue(job.id, priority=job.priority)
    finally:
        await queue.close()
    return JobOut.model_validate(job)


__all__ = ["router"]
