"""Worker runtime: claim, execute, report, retry, shut down cleanly."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import signal
import socket
from pathlib import Path

from spilltrace.config import Settings, get_settings
from spilltrace.core.enums import JobStatus, JobType
from spilltrace.core.errors import NoDataError, ProviderError, SpilltraceError
from spilltrace.db.models import Job
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.db.session import dispose_engine, session_scope
from spilltrace.logging import configure_logging, get_logger, job_id_var
from spilltrace.worker.context import JobCancelledError, JobContext
from spilltrace.worker.queue import JobQueue, QueuedJob
from spilltrace.worker.registry import Handler, get_handler, load_handlers, registered_types

log = get_logger(__name__)

#: Touched every loop; the container healthcheck checks its mtime.
LIVENESS_FILE = Path("/tmp/spilltrace-worker.alive")  # noqa: S108 - container-local


class Worker:
    def __init__(self, settings: Settings | None = None, *, worker_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.queue = JobQueue(self.settings)
        self._stopping = asyncio.Event()
        self._active: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        load_handlers()
        log.info(
            "worker_starting",
            worker_id=self.worker_id,
            concurrency=self.settings.worker_concurrency,
            handlers=[t.value for t in registered_types()],
        )
        recovered = await self.queue.recover_orphans(self.worker_id)
        if recovered:
            log.info("worker_recovered_orphans", count=recovered)
        reconciled = await self._reconcile_queued()
        if reconciled:
            log.info("worker_reconciled_queued", count=reconciled)

        reaper = asyncio.create_task(self._reaper_loop())
        try:
            await self._claim_loop()
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            if self._active:
                log.info("worker_draining", in_flight=len(self._active))
                await asyncio.gather(*self._active, return_exceptions=True)
            await self.queue.close()
            await dispose_engine()
            log.info("worker_stopped", worker_id=self.worker_id)

    def request_stop(self) -> None:
        log.info("worker_stop_requested", worker_id=self.worker_id)
        self._stopping.set()

    async def _claim_loop(self) -> None:
        semaphore = asyncio.Semaphore(self.settings.worker_concurrency)
        while not self._stopping.is_set():
            # One touch() per claim loop; the container healthcheck reads its mtime.
            LIVENESS_FILE.touch(exist_ok=True)  # noqa: ASYNC240
            await semaphore.acquire()
            if self._stopping.is_set():
                semaphore.release()
                break
            claimed = await self.queue.claim(self.worker_id, timeout_seconds=5)
            if claimed is None:
                semaphore.release()
                continue

            task = asyncio.create_task(self._execute_and_release(claimed, semaphore))
            self._active.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Surface exceptions that escaped ``execute``.

        Without this, an error raised outside the handler's own try/except — while
        marking the job complete, say — would be swallowed by asyncio and the job would
        sit at RUNNING until the reaper noticed. Silent failure is the worst failure
        mode for a job system, so it is logged loudly here and the reaper still recovers
        the job.
        """
        self._active.discard(task)
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            log.error(
                "worker_task_crashed",
                error=str(error),
                error_type=type(error).__name__,
                exc_info=error,
            )

    async def _execute_and_release(self, claimed: QueuedJob, semaphore: asyncio.Semaphore) -> None:
        try:
            await self.execute(claimed)
        finally:
            semaphore.release()

    async def _reaper_loop(self) -> None:
        """Requeue jobs whose worker stopped heartbeating (P6-007)."""
        interval = max(30, self.settings.job_claim_ttl_seconds // 2)
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            try:
                async with session_scope() as session:
                    stale = await JobRepository(session).reclaim_stale(
                        ttl_seconds=self.settings.job_claim_ttl_seconds
                    )
                for job in stale:
                    if job.status == JobStatus.QUEUED.value:
                        await self.queue.enqueue(job.id, priority=job.priority)
                    log.warning("job_reclaimed", job_id=str(job.id), new_status=job.status)
            except Exception as exc:
                log.error("reaper_failed", error=str(exc), exc_info=True)

    # ------------------------------------------------------------------ execution
    async def execute(self, claimed: QueuedJob) -> None:
        token = job_id_var.set(str(claimed.job_id))
        try:
            async with session_scope() as session:
                repo = JobRepository(session)
                try:
                    job = await repo.get(claimed.job_id)
                except SpilltraceError:
                    log.warning("job_missing_for_queue_entry", job_id=str(claimed.job_id))
                    await self.queue.acknowledge(self.worker_id, claimed)
                    return

                if job.status != JobStatus.QUEUED.value:
                    # Duplicate delivery, or the job was cancelled after being queued.
                    log.info("job_skipped", job_id=str(job.id), status=job.status)
                    await self.queue.acknowledge(self.worker_id, claimed)
                    return

                if await self.queue.is_cancel_requested(job.id):
                    await repo.mark_cancelled(job)
                    await self.queue.clear_cancel(job.id)
                    await self.queue.acknowledge(self.worker_id, claimed)
                    return

                handler = get_handler(JobType(job.job_type))
                if handler is None:
                    await repo.mark_failed(
                        job,
                        code="NO_HANDLER",
                        message=f"No handler is registered for job type '{job.job_type}'.",
                    )
                    await self.queue.acknowledge(self.worker_id, claimed)
                    return

                await repo.mark_running(job, worker_id=self.worker_id)
                await session.commit()
                await self.queue.publish_event(
                    {
                        "type": "started",
                        "job_id": str(job.id),
                        "case_id": str(job.case_id) if job.case_id else None,
                        "job_type": job.job_type,
                    }
                )

                context = JobContext(
                    job=job,
                    session=session,
                    settings=self.settings,
                    queue=self.queue,
                    worker_id=self.worker_id,
                )
                await self._run_handler(handler, context, repo, job, claimed)
        finally:
            job_id_var.reset(token)

    async def _run_handler(
        self,
        handler: Handler,
        context: JobContext,
        repo: JobRepository,
        job: Job,
        claimed: QueuedJob,
    ) -> None:
        try:
            result = await handler(context)
        except JobCancelledError:
            await repo.mark_cancelled(job)
            await self.queue.clear_cancel(job.id)
            log.info("job_cancelled", job_id=str(job.id))
        except NoDataError as exc:
            # A legitimate empty result, not a failure: no scenes in the AOI, no slick in
            # the scene, no vessels in the origin region.  Reporting it as FAILED would
            # be dishonest about what happened (A-10).
            await repo.mark_completed(job, result_ref={"no_data": True, "reason": exc.message})
            log.info("job_completed_no_data", job_id=str(job.id), reason=exc.message)
        except ProviderError as exc:
            await self._fail_or_retry(repo, job, claimed, code=exc.code, message=exc.message)
        except SpilltraceError as exc:
            await self._fail_or_retry(repo, job, claimed, code=exc.code, message=exc.message)
        except Exception as exc:
            log.error("job_crashed", job_id=str(job.id), error=str(exc), exc_info=True)
            await self._fail_or_retry(
                repo,
                job,
                claimed,
                code="INTERNAL_ERROR",
                # The exception text may contain internals; the type name is enough for
                # a user-facing message and the traceback is in the logs.
                message=f"An unexpected error occurred ({type(exc).__name__}).",
            )
        else:
            await repo.mark_completed(job, result_ref=result or {})
            log.info("job_completed", job_id=str(job.id), job_type=job.job_type)
        finally:
            await context.session.commit()
            await self.queue.acknowledge(self.worker_id, claimed)
            await self.queue.publish_event(
                {
                    "type": "finished",
                    "job_id": str(job.id),
                    "case_id": str(job.case_id) if job.case_id else None,
                    "job_type": job.job_type,
                    "status": job.status,
                }
            )
            if job.status == JobStatus.COMPLETED.value:
                await self._advance_pipeline(context, job)

    async def _reconcile_queued(self) -> int:
        """Re-enqueue jobs the database calls QUEUED but Redis has forgotten.

        A retry waits out its backoff inside the worker process, so a restart during that
        sleep leaves the row QUEUED with nothing in the list to claim — the job would wait
        forever and the case would sit at RUNNING.  Reconciling at startup makes a worker
        restart safe at any moment.
        """
        from sqlalchemy import select

        in_redis = await self.queue.queued_ids()
        count = 0
        async with session_scope() as session:
            rows = (
                await session.execute(select(Job).where(Job.status == JobStatus.QUEUED.value))
            ).scalars()
            for job in rows:
                if str(job.id) in in_redis:
                    continue
                await self.queue.enqueue(job.id, priority=job.priority)
                count += 1
        return count

    async def _fail_or_retry(
        self, repo: JobRepository, job: Job, claimed: QueuedJob, *, code: str, message: str
    ) -> None:
        if job.attempt < job.max_attempts:
            await repo.mark_failed(job, code=code, message=message)
            await repo.requeue(job)
            # Bounded exponential backoff with jitter.  The sleep holds one concurrency
            # slot, which is the point: when a provider is failing we want to slow down,
            # not spin through the whole queue burning retries.
            delay = min(30.0, 2.0 ** (job.attempt - 1)) + random.uniform(0, 1)  # noqa: S311
            log.warning(
                "job_retrying",
                job_id=str(job.id),
                attempt=job.attempt,
                delay_seconds=round(delay, 2),
                code=code,
            )
            await asyncio.sleep(delay)
            await self.queue.enqueue(job.id, priority=job.priority)
        else:
            await repo.mark_failed(job, code=code, message=message)
            log.error("job_failed", job_id=str(job.id), code=code, attempts=job.attempt)

    async def _advance_pipeline(self, context: JobContext, job: Job) -> None:
        """Queue the next stage of a pipeline once this one succeeds."""
        if job.pipeline_id is None:
            return
        from spilltrace.worker.pipeline import advance

        try:
            queued = await advance(context.session, job)
            await context.session.commit()
            for next_job in queued:
                await self.queue.enqueue(next_job.id, priority=next_job.priority)
        except Exception as exc:
            log.error("pipeline_advance_failed", job_id=str(job.id), error=str(exc), exc_info=True)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "development")
    worker = Worker(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.request_stop)
    await worker.run()


def run() -> None:
    asyncio.run(main())


__all__ = ["LIVENESS_FILE", "Worker", "main", "run"]
