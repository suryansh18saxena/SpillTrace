"""One Redis subscription, fanned out to every connected client.

The naive SSE implementation opened a Redis pub/sub connection per browser tab. That is
fine with three analysts and fatal with thirty: Redis connections, event-loop tasks and
file descriptors all scale with viewers rather than with work, and the API becomes
unhealthy while doing nothing useful. It was reproduced during development by opening
streams in a loop.

So the process keeps **one** subscriber to the events channel and fans messages out to
in-process asyncio queues. Redis connection count is now independent of client count.

Two further protections:

* **A bounded queue per subscriber.** A client that stops reading (a suspended laptop, a
  throttled background tab) must not make the broker buffer without limit. Its queue
  drops the oldest event and marks it lagged; job status is a *current-state* signal, so
  a slow client wants the latest event, not a backlog of stale ones.
* **A cap on concurrent subscribers**, so a misbehaving client cannot exhaust the
  process. Past the cap the endpoint returns 503 with a retry hint rather than degrading
  the service for everyone.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import orjson

from spilltrace.config import Settings, get_settings
from spilltrace.core.errors import SpilltraceError
from spilltrace.logging import get_logger
from spilltrace.worker.queue import EVENTS_CHANNEL

log = get_logger(__name__)

#: Events buffered per client before the oldest are dropped.
SUBSCRIBER_QUEUE_SIZE = 64

#: Concurrent event streams this process will serve.
MAX_SUBSCRIBERS = 64


class TooManyStreamsError(SpilltraceError):
    code = "TOO_MANY_STREAMS"
    http_status = 503


class _Subscriber:
    __slots__ = ("case_id", "dropped", "queue")

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self.dropped = 0

    def offer(self, payload: dict[str, Any]) -> None:
        """Never blocks. Drops the oldest event when the client is not keeping up."""
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.dropped += 1
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(payload)


class EventBroker:
    """Process-wide fan-out for job events."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._subscribers: set[_Subscriber] = set()
        self._task: asyncio.Task[None] | None = None
        self._client: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def subscribe(self, case_id: str) -> _Subscriber:
        async with self._lock:
            if len(self._subscribers) >= MAX_SUBSCRIBERS:
                raise TooManyStreamsError(
                    "This server is already serving the maximum number of live event "
                    "streams. Retry shortly, or poll the job endpoints instead.",
                    limit=MAX_SUBSCRIBERS,
                )
            subscriber = _Subscriber(case_id)
            self._subscribers.add(subscriber)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._pump())
            return subscriber

    async def unsubscribe(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber)
            if subscriber.dropped:
                log.info(
                    "event_stream_lagged",
                    case_id=subscriber.case_id,
                    dropped=subscriber.dropped,
                )
            if not self._subscribers:
                await self._stop()

    async def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None

    async def close(self) -> None:
        async with self._lock:
            self._subscribers.clear()
            await self._stop()

    async def _pump(self) -> None:
        """The single Redis subscription. Reconnects on its own if the link drops."""
        import redis.asyncio as aioredis

        backoff = 1.0
        while True:
            try:
                self._client = aioredis.from_url(self._settings.redis_url)
                pubsub = self._client.pubsub()
                await pubsub.subscribe(EVENTS_CHANNEL)
                backoff = 1.0
                log.info("event_broker_connected", subscribers=len(self._subscribers))
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                    if message is None:
                        continue
                    try:
                        payload = orjson.loads(message["data"])
                    except (orjson.JSONDecodeError, TypeError, KeyError):
                        continue
                    case_id = payload.get("case_id")
                    for subscriber in tuple(self._subscribers):
                        if subscriber.case_id == case_id:
                            subscriber.offer(payload)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
                raise
            except Exception as exc:  # the broker must survive a Redis restart
                log.warning(
                    "event_broker_reconnecting",
                    error=type(exc).__name__,
                    delay_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)


_broker: EventBroker | None = None


def get_broker() -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker()
    return _broker


async def shutdown_broker() -> None:
    global _broker
    if _broker is not None:
        await _broker.close()
    _broker = None


__all__ = [
    "MAX_SUBSCRIBERS",
    "SUBSCRIBER_QUEUE_SIZE",
    "EventBroker",
    "TooManyStreamsError",
    "get_broker",
    "shutdown_broker",
]
