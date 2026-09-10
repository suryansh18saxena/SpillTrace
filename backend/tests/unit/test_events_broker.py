"""The SSE fan-out broker.

The defect this replaces was found by load, not by review: opening streams in a loop took
the API container unhealthy, because Redis connections and event-loop tasks scaled with
*viewers* rather than with work. These tests pin the properties that fix depends on.
"""

from __future__ import annotations

import asyncio

import pytest

from spilltrace.api.events_broker import (
    MAX_SUBSCRIBERS,
    SUBSCRIBER_QUEUE_SIZE,
    EventBroker,
    TooManyStreamsError,
)


class StubBroker(EventBroker):
    """A broker whose Redis pump is replaced by a no-op.

    The fan-out logic is what matters here; the Redis client is exercised by the
    integration suite and by the live load test recorded in docs/TESTING.md.
    """

    async def _pump(self) -> None:  # type: ignore[override]
        await asyncio.Event().wait()


@pytest.fixture
async def broker():
    instance = StubBroker()
    yield instance
    await instance.close()


class TestFanOut:
    async def test_one_pump_serves_many_subscribers(self, broker: StubBroker) -> None:
        # The whole point: connection cost is independent of viewer count.
        subscribers = [await broker.subscribe("case-1") for _ in range(25)]
        assert broker.subscriber_count == 25
        assert broker._task is not None
        for subscriber in subscribers:
            await broker.unsubscribe(subscriber)
        assert broker.subscriber_count == 0

    async def test_the_pump_stops_when_the_last_client_leaves(self, broker: StubBroker) -> None:
        subscriber = await broker.subscribe("case-1")
        assert broker._task is not None
        await broker.unsubscribe(subscriber)
        assert broker._task is None

    async def test_events_reach_only_the_matching_case(self, broker: StubBroker) -> None:
        watching = await broker.subscribe("case-1")
        other = await broker.subscribe("case-2")
        watching.offer({"case_id": "case-1", "type": "progress"})
        assert watching.queue.qsize() == 1
        assert other.queue.qsize() == 0


class TestBackpressure:
    async def test_a_slow_client_drops_the_oldest_events(self, broker: StubBroker) -> None:
        # Job status is current-state: a client that stalled wants the latest event,
        # not a backlog of stale ones, and must never make the broker buffer unbounded.
        subscriber = await broker.subscribe("case-1")
        for index in range(SUBSCRIBER_QUEUE_SIZE + 20):
            subscriber.offer({"case_id": "case-1", "progress": index})

        assert subscriber.queue.qsize() == SUBSCRIBER_QUEUE_SIZE
        assert subscriber.dropped == 20

        first = subscriber.queue.get_nowait()
        assert first["progress"] == 20  # the oldest 20 were discarded

    async def test_offer_never_blocks(self, broker: StubBroker) -> None:
        subscriber = await broker.subscribe("case-1")
        await asyncio.wait_for(
            asyncio.to_thread(
                lambda: [subscriber.offer({"case_id": "case-1", "n": i}) for i in range(500)]
            ),
            timeout=5.0,
        )
        assert subscriber.queue.qsize() == SUBSCRIBER_QUEUE_SIZE


class TestAdmissionControl:
    async def test_the_subscriber_cap_is_enforced(self, broker: StubBroker) -> None:
        held = [await broker.subscribe("case-1") for _ in range(MAX_SUBSCRIBERS)]
        with pytest.raises(TooManyStreamsError) as excinfo:
            await broker.subscribe("case-1")
        # A clear 503 with a retry hint beats degrading the service for everyone.
        assert excinfo.value.http_status == 503
        assert "poll the job endpoints" in excinfo.value.message
        for subscriber in held:
            await broker.unsubscribe(subscriber)

    async def test_capacity_is_returned_when_a_client_leaves(self, broker: StubBroker) -> None:
        held = [await broker.subscribe("case-1") for _ in range(MAX_SUBSCRIBERS)]
        await broker.unsubscribe(held.pop())
        reclaimed = await broker.subscribe("case-1")
        assert reclaimed is not None
        for subscriber in [*held, reclaimed]:
            await broker.unsubscribe(subscriber)

    async def test_close_releases_everything(self, broker: StubBroker) -> None:
        for _ in range(10):
            await broker.subscribe("case-1")
        await broker.close()
        assert broker.subscriber_count == 0
        assert broker._task is None
