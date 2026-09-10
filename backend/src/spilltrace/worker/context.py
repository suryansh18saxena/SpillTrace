"""Execution context handed to every job handler."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.config import Settings
from spilltrace.core.errors import SpilltraceError
from spilltrace.db.models import Job
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.logging import get_logger
from spilltrace.worker.queue import JobQueue

log = get_logger(__name__)


class JobCancelledError(SpilltraceError):
    code = "JOB_CANCELLED"
    http_status = 409


@dataclass(slots=True)
class JobContext:
    """What a handler is given.

    Handlers receive this rather than raw sessions/clients so that progress reporting,
    cancellation and logging are uniform and cannot be forgotten.
    """

    job: Job
    session: AsyncSession
    settings: Settings
    queue: JobQueue
    worker_id: str
    _last_progress: int = field(default=-1, repr=False)

    @property
    def job_id(self) -> uuid.UUID:
        return self.job.id

    @property
    def case_id(self) -> uuid.UUID | None:
        return self.job.case_id

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload or {}

    async def progress(self, fraction: float, message: str) -> None:
        """Report progress and check for cancellation.

        Cancellation is checked here because it is the one place every long-running
        handler is guaranteed to call periodically.
        """
        percent = max(0, min(100, round(fraction * 100)))
        if percent != self._last_progress or message != (self.job.step or ""):
            self._last_progress = percent
            await JobRepository(self.session).heartbeat(self.job, progress=percent, step=message)
            await self.session.commit()
            await self.queue.publish_event(
                {
                    "type": "progress",
                    "job_id": str(self.job.id),
                    "case_id": str(self.job.case_id) if self.job.case_id else None,
                    "job_type": self.job.job_type,
                    "progress": percent,
                    "step": message,
                }
            )
        if await self.queue.is_cancel_requested(self.job.id):
            raise JobCancelledError("This job was cancelled.", job_id=str(self.job.id))

    async def heartbeat(self) -> None:
        await JobRepository(self.session).heartbeat(self.job)
        await self.session.commit()

    def log(self, event: str, **fields: Any) -> None:
        log.info(event, job_id=str(self.job.id), job_type=self.job.job_type, **fields)


__all__ = ["JobCancelledError", "JobContext"]
