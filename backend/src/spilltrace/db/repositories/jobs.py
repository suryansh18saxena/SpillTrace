"""Job persistence.

The database is the source of truth for job state; Redis is only the transport (AD-3).
Every state transition goes through this repository so the transition table is enforced
in exactly one place.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select

from spilltrace.core.enums import JobStatus, JobType
from spilltrace.core.errors import ConflictError, NotFoundError
from spilltrace.core.jsonsafe import to_json_safe
from spilltrace.core.time import utcnow
from spilltrace.db.models import Job
from spilltrace.db.repositories.base import Page, Repository

#: Allowed status transitions.  Anything else is a bug and is rejected loudly.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.QUEUED}
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),  # retry
    JobStatus.CANCELLED: frozenset({JobStatus.QUEUED}),  # re-run
}


class JobRepository(Repository[Job]):
    model = Job

    async def get(self, job_id: uuid.UUID) -> Job:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found.", job_id=str(job_id))
        return job

    async def create(
        self,
        *,
        job_type: JobType,
        case_id: uuid.UUID | None = None,
        pipeline_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        depends_on: list[uuid.UUID] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
    ) -> Job:
        job = Job(
            case_id=case_id,
            pipeline_id=pipeline_id,
            job_type=job_type.value,
            status=JobStatus.QUEUED.value,
            payload=payload or {},
            depends_on=depends_on or [],
            priority=priority,
            max_attempts=max_attempts,
            queued_at=utcnow(),
        )
        return await self.add(job)

    async def list_for_case(
        self, case_id: uuid.UUID, *, limit: int, offset: int, status: str | None = None
    ) -> Page[Job]:
        stmt: Select[Any] = select(Job).where(Job.case_id == case_id)
        if status:
            stmt = stmt.where(Job.status == status)
        stmt = stmt.order_by(Job.created_at.desc())
        return await self.paginate(stmt, limit=limit, offset=offset)

    # ------------------------------------------------------------------ transitions
    def _check_transition(self, job: Job, target: JobStatus) -> None:
        current = JobStatus(job.status)
        if target not in ALLOWED_TRANSITIONS[current]:
            raise ConflictError(
                f"A job cannot move from {current.value} to {target.value}.",
                job_id=str(job.id),
                current=current.value,
                target=target.value,
            )

    async def mark_running(self, job: Job, *, worker_id: str) -> Job:
        self._check_transition(job, JobStatus.RUNNING)
        job.status = JobStatus.RUNNING.value
        job.attempt += 1
        job.worker_id = worker_id
        job.started_at = utcnow()
        job.heartbeat_at = utcnow()
        job.progress = 0
        job.error_code = None
        job.error_message = None
        await self.session.flush()
        return job

    async def heartbeat(
        self, job: Job, *, progress: int | None = None, step: str | None = None
    ) -> None:
        job.heartbeat_at = utcnow()
        if progress is not None:
            job.progress = max(0, min(100, progress))
        if step is not None:
            job.step = step[:200]
        await self.session.flush()

    async def mark_completed(self, job: Job, *, result_ref: dict[str, Any] | None = None) -> Job:
        self._check_transition(job, JobStatus.COMPLETED)
        job.status = JobStatus.COMPLETED.value
        job.progress = 100
        # Normalised here rather than trusting the handler: a datetime or enum reaching
        # JSONB fails at flush time, far from the code that produced it.
        job.result_ref = to_json_safe(result_ref or {})
        job.finished_at = utcnow()
        await self.session.flush()
        return job

    async def mark_failed(self, job: Job, *, code: str, message: str) -> Job:
        self._check_transition(job, JobStatus.FAILED)
        job.status = JobStatus.FAILED.value
        job.error_code = code[:64]
        # Truncated and already sanitised by the caller; never contains credentials.
        job.error_message = message[:2000]
        job.finished_at = utcnow()
        await self.session.flush()
        return job

    async def mark_cancelled(self, job: Job) -> Job:
        self._check_transition(job, JobStatus.CANCELLED)
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
        await self.session.flush()
        return job

    async def requeue(self, job: Job) -> Job:
        """Retry a failed or cancelled job."""
        self._check_transition(job, JobStatus.QUEUED)
        if job.attempt >= job.max_attempts:
            raise ConflictError(
                f"This job has already been attempted {job.attempt} times "
                f"(limit {job.max_attempts}).",
                job_id=str(job.id),
            )
        job.status = JobStatus.QUEUED.value
        job.progress = 0
        job.step = None
        job.error_code = None
        job.error_message = None
        job.started_at = None
        job.finished_at = None
        job.queued_at = utcnow()
        await self.session.flush()
        return job

    # ------------------------------------------------------------------ recovery
    async def reclaim_stale(self, *, ttl_seconds: int) -> list[Job]:
        """Return RUNNING jobs whose worker stopped sending heartbeats.

        This is what makes a worker crash recoverable rather than a job stuck at
        RUNNING forever (P6-007).
        """
        cutoff = utcnow() - timedelta(seconds=ttl_seconds)
        stmt = select(Job).where(
            and_(Job.status == JobStatus.RUNNING.value, Job.heartbeat_at < cutoff)
        )
        stale = list((await self.session.execute(stmt)).scalars().all())
        for job in stale:
            if job.attempt < job.max_attempts:
                job.status = JobStatus.QUEUED.value
                job.queued_at = utcnow()
                job.step = "requeued after worker heartbeat timeout"
            else:
                job.status = JobStatus.FAILED.value
                job.error_code = "WORKER_TIMEOUT"
                job.error_message = (
                    "The worker processing this job stopped responding and the retry "
                    "limit was reached."
                )
                job.finished_at = utcnow()
        await self.session.flush()
        return stale

    async def stats(self, *, hours: int = 24) -> dict[str, int]:
        since = utcnow() - timedelta(hours=hours)
        out: dict[str, int] = {}
        for key, condition in (
            ("queued", Job.status == JobStatus.QUEUED.value),
            ("running", Job.status == JobStatus.RUNNING.value),
        ):
            stmt = select(func.count()).select_from(Job).where(condition)
            out[key] = int((await self.session.execute(stmt)).scalar_one())
        for key, status in (("completed", JobStatus.COMPLETED), ("failed", JobStatus.FAILED)):
            stmt = (
                select(func.count())
                .select_from(Job)
                .where(Job.status == status.value, Job.finished_at >= since)
            )
            out[f"{key}_{hours}h"] = int((await self.session.execute(stmt)).scalar_one())
        return out

    async def recent(self, *, limit: int = 10, status: JobStatus | None = None) -> list[Job]:
        stmt: Select[Any] = select(Job)
        if status:
            stmt = stmt.where(Job.status == status.value)
        stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = ["ALLOWED_TRANSITIONS", "JobRepository"]
