"""Redis job queue with at-least-once delivery.

Why not just ``LPUSH``/``BRPOP``: a plain pop removes the job from Redis before the
worker has finished, so a crash loses it.  ``BLMOVE`` atomically moves the id to a
per-worker *processing* list, where it stays until the worker acknowledges.  Combined
with the database heartbeat and the reaper in ``JobRepository.reclaim_stale``, a crashed
worker's job is recovered rather than lost.

Delivery is **at-least-once**, so handlers must be idempotent.  That is a deliberate
trade: for this workload, running a stage twice is recoverable; silently dropping one is
not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

from spilltrace.config import Settings, get_settings
from spilltrace.logging import get_logger

log = get_logger(__name__)

QUEUE_KEY = "spilltrace:jobs:queued"
PROCESSING_KEY_PREFIX = "spilltrace:jobs:processing:"
CANCEL_KEY = "spilltrace:jobs:cancelled"
EVENTS_CHANNEL = "spilltrace:jobs:events"


@dataclass(frozen=True, slots=True)
class QueuedJob:
    job_id: uuid.UUID
    raw: str


class JobQueue:
    """Thin, testable abstraction over Redis lists."""

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or aioredis.from_url(self._settings.redis_url, decode_responses=True)

    @property
    def client(self) -> Any:
        return self._client

    def processing_key(self, worker_id: str) -> str:
        return f"{PROCESSING_KEY_PREFIX}{worker_id}"

    async def enqueue(self, job_id: uuid.UUID, *, priority: int = 0) -> None:
        """Higher priority goes to the head of the queue.

        Two buckets rather than a sorted set: the workload has a handful of urgent
        interactive jobs and a long tail of pipeline stages, and a full priority queue
        would add contention for no practical gain.
        """
        if priority > 0:
            await self._client.rpush(QUEUE_KEY, str(job_id))
        else:
            await self._client.lpush(QUEUE_KEY, str(job_id))
        await self.publish_event({"type": "queued", "job_id": str(job_id)})

    async def claim(self, worker_id: str, *, timeout_seconds: int = 5) -> QueuedJob | None:
        """Block until a job is available, moving it to this worker's processing list."""
        raw = await self._client.blmove(
            QUEUE_KEY, self.processing_key(worker_id), timeout_seconds, "RIGHT", "LEFT"
        )
        if raw is None:
            return None
        try:
            return QueuedJob(job_id=uuid.UUID(raw), raw=raw)
        except ValueError:
            log.warning("queue_discarded_malformed_entry", entry=raw[:64])
            await self._client.lrem(self.processing_key(worker_id), 1, raw)
            return None

    async def acknowledge(self, worker_id: str, job: QueuedJob) -> None:
        await self._client.lrem(self.processing_key(worker_id), 1, job.raw)

    async def release(self, worker_id: str, job: QueuedJob) -> None:
        """Return a claimed job to the queue (used on shutdown mid-job)."""
        await self._client.lrem(self.processing_key(worker_id), 1, job.raw)
        await self._client.lpush(QUEUE_KEY, job.raw)

    async def recover_orphans(self, worker_id: str) -> int:
        """Push anything left in this worker's processing list back onto the queue.

        Called at start-up, so a worker restarting after a crash re-queues its own
        in-flight work immediately instead of waiting for the heartbeat reaper.
        """
        key = self.processing_key(worker_id)
        moved = 0
        while (raw := await self._client.rpoplpush(key, QUEUE_KEY)) is not None:
            moved += 1
            log.info("queue_recovered_orphan", job_id=raw, worker_id=worker_id)
        return moved

    # ------------------------------------------------------------------ cancellation
    async def request_cancel(self, job_id: uuid.UUID) -> None:
        await self._client.sadd(CANCEL_KEY, str(job_id))
        await self._client.expire(CANCEL_KEY, 86_400)

    async def is_cancel_requested(self, job_id: uuid.UUID) -> bool:
        return bool(await self._client.sismember(CANCEL_KEY, str(job_id)))

    async def clear_cancel(self, job_id: uuid.UUID) -> None:
        await self._client.srem(CANCEL_KEY, str(job_id))

    # ------------------------------------------------------------------ events
    async def publish_event(self, payload: dict[str, Any]) -> None:
        """Fan-out for the SSE stream.  Best-effort: never fails a job."""
        try:
            import orjson

            await self._client.publish(EVENTS_CHANNEL, orjson.dumps(payload).decode())
        except Exception as exc:
            log.debug("event_publish_failed", error=type(exc).__name__)

    async def depth(self) -> int:
        return int(await self._client.llen(QUEUE_KEY))

    async def queued_ids(self) -> set[str]:
        """Every job id currently waiting in the Redis list (for reconciliation)."""
        raw = await self._client.lrange(QUEUE_KEY, 0, -1)
        return {item.decode() if isinstance(item, bytes) else str(item) for item in raw}

    async def close(self) -> None:
        await self._client.aclose()


__all__ = [
    "CANCEL_KEY",
    "EVENTS_CHANNEL",
    "PROCESSING_KEY_PREFIX",
    "QUEUE_KEY",
    "JobQueue",
    "QueuedJob",
]
