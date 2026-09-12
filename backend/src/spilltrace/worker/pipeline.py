"""Pipeline orchestration.

A pipeline is the PRD's investigation chain expressed as a linear DAG of jobs on one
case.  Each stage declares what it depends on; a stage becomes runnable when every
dependency has COMPLETED.  Keeping the dependency data on the job row (rather than in a
scheduler's memory) means a restart resumes rather than restarts.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.core.enums import PIPELINE_ORDER, CaseStatus, JobStatus, JobType
from spilltrace.db.models import Case, Job
from spilltrace.db.provenance import rollup_case_provenance
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.logging import get_logger

log = get_logger(__name__)

#: The demo path replaces every provider-backed stage with a single seeded generator, so
#: the whole chain is exercised with zero external calls (FR-020).
DEMO_ORDER: tuple[JobType, ...] = (
    JobType.DEMO_SEED,
    # demo.seed already writes the environmental run, so verification has its wind.
    JobType.DETECT_VERIFY,
    JobType.DRIFT_HINDCAST,
    JobType.AIS_CLEAN,
    JobType.TRAJ_BUILD,
    JobType.CORRELATE,
    JobType.SCORE,
    JobType.REPORT_BUILD,
)


async def create_pipeline(
    session: AsyncSession,
    *,
    case: Case,
    mode: str = "REAL",
    stages: list[JobType] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, list[Job]]:
    """Create the job DAG for a case and return ``(pipeline_id, jobs)``.

    Only the first stage is left runnable; the rest wait on their predecessor.  The
    caller enqueues whatever comes back from :func:`runnable_jobs`.
    """
    order = tuple(stages) if stages else (DEMO_ORDER if mode == "DEMO" else PIPELINE_ORDER)
    pipeline_id = uuid.uuid4()
    repo = JobRepository(session)

    jobs: list[Job] = []
    previous_id: uuid.UUID | None = None
    for index, job_type in enumerate(order):
        job = await repo.create(
            job_type=job_type,
            case_id=case.id,
            pipeline_id=pipeline_id,
            payload={
                "mode": mode,
                "stage_index": index,
                "case_id": str(case.id),
                **(params or {}),
            },
            depends_on=[previous_id] if previous_id else [],
            priority=0,
        )
        jobs.append(job)
        previous_id = job.id

    case.status = CaseStatus.QUEUED.value
    await session.flush()
    log.info(
        "pipeline_created",
        pipeline_id=str(pipeline_id),
        case_id=str(case.id),
        mode=mode,
        stages=[t.value for t in order],
    )
    return pipeline_id, jobs


async def runnable_jobs(session: AsyncSession, pipeline_id: uuid.UUID) -> list[Job]:
    """QUEUED jobs whose dependencies have all COMPLETED."""
    stmt = select(Job).where(Job.pipeline_id == pipeline_id)
    jobs = list((await session.execute(stmt)).scalars().all())
    by_id = {job.id: job for job in jobs}
    ready: list[Job] = []
    for job in jobs:
        if job.status != JobStatus.QUEUED.value:
            continue
        deps = [by_id.get(dep) for dep in (job.depends_on or [])]
        if all(d is not None and d.status == JobStatus.COMPLETED.value for d in deps):
            ready.append(job)
    return ready


async def advance(session: AsyncSession, completed_job: Job) -> list[Job]:
    """Return the jobs unblocked by ``completed_job`` finishing.

    Also settles the case status when the pipeline reaches a terminal state.
    """
    if completed_job.pipeline_id is None:
        return []
    ready = await runnable_jobs(session, completed_job.pipeline_id)

    stmt = select(Job).where(Job.pipeline_id == completed_job.pipeline_id)
    all_jobs = list((await session.execute(stmt)).scalars().all())
    statuses = {j.status for j in all_jobs}

    if completed_job.case_id is not None:
        case = await session.get(Case, completed_job.case_id)
        if case is not None:
            if statuses <= {JobStatus.COMPLETED.value}:
                case.status = CaseStatus.COMPLETED.value
            elif JobStatus.FAILED.value in statuses and not ready:
                case.status = CaseStatus.FAILED.value
            else:
                case.status = CaseStatus.RUNNING.value
            # The case's provenance label must describe the evidence it now holds
            # (CON-009): a "real" investigation fed by fixture scenes is not REAL.
            await rollup_case_provenance(session, case)
            await session.flush()
    return ready


async def pipeline_summary(session: AsyncSession, pipeline_id: uuid.UUID) -> dict[str, Any]:
    stmt = select(Job).where(Job.pipeline_id == pipeline_id).order_by(Job.created_at)
    jobs = list((await session.execute(stmt)).scalars().all())
    if not jobs:
        return {"pipeline_id": str(pipeline_id), "stages": [], "status": "UNKNOWN"}
    statuses = {j.status for j in jobs}
    if statuses <= {JobStatus.COMPLETED.value}:
        overall = "COMPLETED"
    elif JobStatus.RUNNING.value in statuses:
        overall = "RUNNING"
    elif JobStatus.FAILED.value in statuses:
        overall = "FAILED"
    elif statuses <= {JobStatus.CANCELLED.value, JobStatus.COMPLETED.value}:
        overall = "CANCELLED"
    else:
        overall = "QUEUED"
    return {
        "pipeline_id": str(pipeline_id),
        "status": overall,
        "stages": [
            {
                "job_id": str(j.id),
                "job_type": j.job_type,
                "status": j.status,
                "progress": j.progress,
                "step": j.step,
                "error_code": j.error_code,
                "error_message": j.error_message,
            }
            for j in jobs
        ],
    }


__all__ = ["DEMO_ORDER", "advance", "create_pipeline", "pipeline_summary", "runnable_jobs"]
