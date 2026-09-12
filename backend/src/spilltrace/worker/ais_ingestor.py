"""``python -m spilltrace.worker.ais_ingestor`` — the long-lived AIS stream consumer.

The ``ais-ingestor`` container runs this module (ARCHITECTURE.md, AIS-011).  It has two
honest modes and no third:

* **Configured** (``SPILLTRACE_AIS_PROVIDER=aisstream`` with ``AISSTREAM_API_KEY``):
  subscribe to AISStream for the configured bounding boxes and upsert every position and
  static-data message into ``vessels`` / ``ais_positions`` in small batches, using the
  same persistence path as the ``ais.ingest`` job so both agree on validation and
  provenance.
* **Idle** (anything else): log one clear line explaining why there is nothing to
  stream and wait.  Exiting would make the container restart-loop, and pretending to
  stream would be worse.  Cases still get AIS from the ``ais.ingest`` job (synthetic
  provider in a demo), which is labelled as such.

Bounding boxes come from ``SPILLTRACE_AIS_STREAM_BBOXES`` as
``min_lon,min_lat,max_lon,max_lat[;…]``; the default covers Indian waters.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.config import Settings, get_settings
from spilltrace.core.errors import ProviderNotConfiguredError, ProviderUnavailableError
from spilltrace.logging import configure_logging, get_logger

log = get_logger(__name__)

#: Indian EEZ and approaches — Arabian Sea, Bay of Bengal, Lakshadweep, Andaman.
DEFAULT_BBOXES: tuple[tuple[float, float, float, float], ...] = ((60.0, 2.0, 98.0, 26.0),)
BATCH_SIZE = 200
FLUSH_SECONDS = 5.0


def parse_bboxes(raw: str | None) -> list[tuple[float, float, float, float]]:
    if not raw or not raw.strip():
        return list(DEFAULT_BBOXES)
    boxes: list[tuple[float, float, float, float]] = []
    for chunk in raw.split(";"):
        parts = [float(v) for v in chunk.split(",") if v.strip()]
        if len(parts) != 4:
            raise ValueError(f"A bounding box needs four numbers, got {chunk!r}.")
        min_lon, min_lat, max_lon, max_lat = parts
        if not (min_lon < max_lon and min_lat < max_lat):
            raise ValueError(f"Bounding box {chunk!r} is not min<max on both axes.")
        boxes.append((min_lon, min_lat, max_lon, max_lat))
    return boxes


def idle_reason(settings: Settings) -> str | None:
    """Why this process has nothing to stream, or ``None`` if it can stream."""
    if settings.ais_provider != "aisstream":
        return (
            f"SPILLTRACE_AIS_PROVIDER={settings.ais_provider!r}: only the 'aisstream' "
            "provider streams live AIS; the synthetic provider is served per case by "
            "the ais.ingest job and is labelled SYNTHETIC."
        )
    if not settings.aisstream_api_key:
        return "SPILLTRACE_AIS_PROVIDER=aisstream but AISSTREAM_API_KEY is not set."
    return None


@dataclass
class _StreamContext:
    """The slice of ``JobContext`` that ``_persist_messages`` actually uses."""

    session: AsyncSession
    settings: Settings


async def _stream_forever(settings: Settings, stop: asyncio.Event) -> None:
    from spilltrace.adapters.ais.aisstream import AISStreamProvider
    from spilltrace.db.session import session_scope
    from spilltrace.worker.handlers.ais import _persist_messages

    bboxes = parse_bboxes(os.environ.get("SPILLTRACE_AIS_STREAM_BBOXES"))
    provider = AISStreamProvider(settings)
    log.info("ais_ingestor_streaming", provider=provider.name, bboxes=bboxes)

    batch: list[Any] = []
    last_flush = asyncio.get_running_loop().time()
    total = 0

    async def flush() -> None:
        nonlocal batch, last_flush, total
        if not batch:
            return
        pending, batch = batch, []
        async with session_scope() as session:
            context = _StreamContext(session=session, settings=settings)
            await _persist_messages(cast("Any", context), pending)
        total += len(pending)
        last_flush = asyncio.get_running_loop().time()
        log.info("ais_ingestor_flushed", messages=len(pending), total=total)

    stream = provider.stream(bboxes=bboxes)
    try:
        async for message in stream:
            if stop.is_set():
                break
            batch.append(message)
            now = asyncio.get_running_loop().time()
            if len(batch) >= BATCH_SIZE or now - last_flush >= FLUSH_SECONDS:
                await flush()
    finally:
        await flush()


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # non-POSIX hosts
            loop.add_signal_handler(sig, stop.set)

    reason = idle_reason(settings)
    if reason:
        log.info(
            "ais_ingestor_idle",
            reason=reason,
            remedy="set SPILLTRACE_AIS_PROVIDER=aisstream and AISSTREAM_API_KEY (server side only)",
        )
        await stop.wait()
        return 0

    try:
        streamer = asyncio.create_task(_stream_forever(settings, stop))
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({streamer, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if streamer in done:
            streamer.result()
        else:
            streamer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await streamer
        waiter.cancel()
    except (ProviderNotConfiguredError, ProviderUnavailableError) as exc:
        log.error("ais_ingestor_provider_error", detail=str(exc))
        await stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
