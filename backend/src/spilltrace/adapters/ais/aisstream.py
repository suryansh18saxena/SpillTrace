"""AISStream.io WebSocket client (FR-011, docs/DECISIONS.md AD-21…AD-26).

AISStream is a *live stream*. It answers "what is transmitting now", never "what
transmitted last Tuesday" — so :meth:`historical` raises rather than returning an empty
list, keeping "no vessels were there" distinct from "this source cannot know".

Every wire quirk that was confirmed against the live API in AD-21 is handled here:

* the subscription must be the first frame and within 3 s; a resubscription *replaces*
  the previous one and is rate-limited to 1/s;
* ``BoundingBoxes`` corners are ``[latitude, longitude]`` — latitude first. Reversing
  them yields a connection that succeeds and then stays silent forever;
* an invalid subscription produces **no error frame**, so a missing
  ``SubscriptionConfirmation`` is treated as a hard failure;
* ``MetaData`` mixes casing (``MMSI`` capitalised, ``time_utc`` lowercase) and
  ``time_utc`` is Go's ``2006-01-02 15:04:05.999999999 -0700 MST`` with a
  variable-length fraction that ``datetime.fromisoformat`` cannot parse;
* a 90 s silence triggers a reconnect, because application-level pings would count
  against the 1/s subscription-replacement limit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

import websockets

from spilltrace.config import Settings, get_settings
from spilltrace.core.ais.validate import (
    normalise_cog,
    normalise_heading,
    normalise_latitude,
    normalise_longitude,
    normalise_ship_type,
    normalise_sog,
    parse_aisstream_timestamp,
)
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ProviderNotConfiguredError, ProviderUnavailableError
from spilltrace.core.ports import AISMessage
from spilltrace.core.time import utcnow
from spilltrace.logging import get_logger

log = get_logger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

#: No frame for this long → tear down and reconnect (AD-21 stall watchdog).
STALL_TIMEOUT_SECONDS = 90.0
#: Must see SubscriptionConfirmation within this window or the subscription is bad.
SUBSCRIBE_CONFIRM_TIMEOUT_SECONDS = 5.0
#: Reconnect backoff ceiling.
MAX_BACKOFF_SECONDS = 60.0


class AISStreamProvider:
    """Implements :class:`spilltrace.core.ports.AISProvider`."""

    name = "aisstream"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.aisstream_api_key:
            raise ProviderNotConfiguredError(
                "AISStream is selected but AISSTREAM_API_KEY is not set.",
                provider="aisstream",
            )

    # ------------------------------------------------------------------ historical
    async def historical(
        self, *, bbox: tuple[float, float, float, float], start: datetime, end: datetime
    ) -> list[AISMessage]:
        raise ProviderUnavailableError(
            "AISStream is a live feed and cannot return historical positions. Use the "
            "synthetic provider for a past time window, or ingest a live stream and "
            "replay it.",
            provider="aisstream",
        )

    # ------------------------------------------------------------------ stream
    def stream(
        self,
        *,
        bboxes: Sequence[tuple[float, float, float, float]],
        message_types: Sequence[str] = ("PositionReport", "ShipStaticData"),
    ) -> AsyncIterator[AISMessage]:
        return self._run(list(bboxes), list(message_types))

    async def _run(
        self, bboxes: list[tuple[float, float, float, float]], message_types: list[str]
    ) -> AsyncIterator[AISMessage]:
        subscription = self._subscription_frame(bboxes, message_types)
        backoff = 1.0
        while True:
            try:
                async for message in self._session(subscription, message_types):
                    yield message
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except (ProviderNotConfiguredError, ProviderUnavailableError):
                raise
            except Exception as exc:  # the stream must survive drops
                delay = min(MAX_BACKOFF_SECONDS, backoff) + random.uniform(0, 1)  # noqa: S311
                log.warning(
                    "aisstream_reconnecting",
                    error=type(exc).__name__,
                    detail=str(exc)[:200],
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)
                backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)

    async def _session(
        self, subscription: dict[str, Any], message_types: list[str]
    ) -> AsyncIterator[AISMessage]:
        async with websockets.connect(
            AISSTREAM_URL,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            max_queue=1024,
            compression="deflate",
        ) as ws:
            # First frame, within 3 s.
            await ws.send(json.dumps(subscription))
            await self._await_confirmation(ws)
            log.info("aisstream_subscribed", boxes=len(subscription["BoundingBoxes"]))

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=STALL_TIMEOUT_SECONDS)
                except TimeoutError as exc:
                    raise ConnectionError("no AIS frame for 90 s") from exc

                parsed = self._parse(raw, message_types)
                if parsed is not None:
                    yield parsed

    async def _await_confirmation(self, ws: Any) -> None:
        """A bad subscription is silent, so treat a missing confirmation as fatal."""
        deadline = asyncio.get_running_loop().time() + SUBSCRIBE_CONFIRM_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=SUBSCRIBE_CONFIRM_TIMEOUT_SECONDS)
            except TimeoutError:
                break
            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            mtype = envelope.get("MessageType") or envelope.get("messageType")
            if mtype == "SubscriptionConfirmation":
                return
            if mtype == "Error" or "error" in envelope:
                raise ProviderUnavailableError(
                    f"AISStream rejected the subscription: {envelope}",
                    provider="aisstream",
                )
        raise ProviderUnavailableError(
            "AISStream did not confirm the subscription within 5 s. The API key may be "
            "invalid, or the bounding box corners may be in the wrong order "
            "(AISStream wants [latitude, longitude]).",
            provider="aisstream",
        )

    # ------------------------------------------------------------------ framing
    def _subscription_frame(
        self, bboxes: list[tuple[float, float, float, float]], message_types: list[str]
    ) -> dict[str, Any]:
        # Our bboxes are (min_lon, min_lat, max_lon, max_lat).  AISStream wants
        # [[SW_lat, SW_lon], [NE_lat, NE_lon]] — latitude first.
        boxes = [
            [[min_lat, min_lon], [max_lat, max_lon]]
            for (min_lon, min_lat, max_lon, max_lat) in bboxes
        ]
        return {
            "APIKey": self._settings.aisstream_api_key,
            "BoundingBoxes": boxes,
            "FilterMessageTypes": list(message_types),
        }

    def _parse(self, raw: str | bytes, message_types: list[str]) -> AISMessage | None:
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        mtype = envelope.get("MessageType")
        if mtype not in message_types:
            return None

        meta = envelope.get("MetaData", {}) or {}
        payload = (envelope.get("Message", {}) or {}).get(mtype, {}) or {}

        mmsi = meta.get("MMSI") or payload.get("UserID") or payload.get("UserId")
        if mmsi is None:
            return None

        lat = normalise_latitude(payload.get("Latitude", meta.get("latitude")))
        lon = normalise_longitude(payload.get("Longitude", meta.get("longitude")))
        if mtype == "PositionReport" and (lat is None or lon is None):
            return None

        timestamp = self._timestamp(meta)
        name = (meta.get("ShipName") or payload.get("Name") or "").strip() or None

        return AISMessage(
            mmsi=int(mmsi),
            timestamp=timestamp,
            latitude=lat if lat is not None else 0.0,
            longitude=lon if lon is not None else 0.0,
            message_type=mtype,
            source="aisstream",
            sog_knots=normalise_sog(payload.get("Sog")),
            cog_deg=normalise_cog(payload.get("Cog")),
            heading_deg=normalise_heading(payload.get("TrueHeading")),
            rot=None,  # AISStream ROT units are UNCERTAIN and ROT is not used in scoring
            nav_status=payload.get("NavigationalStatus"),
            name=name,
            imo=payload.get("ImoNumber") or payload.get("IMONumber"),
            callsign=(payload.get("CallSign") or "").strip() or None,
            ship_type=normalise_ship_type(payload.get("Type") or payload.get("ShipType")),
            destination=(payload.get("Destination") or "").strip() or None,
            length_m=self._length(payload),
            width_m=self._width(payload),
            draught_m=_positive(payload.get("MaximumStaticDraught")),
            data_provenance=DataProvenance.REAL,
            raw={"metadata_time": meta.get("time_utc"), "message_type": mtype},
        )

    def _timestamp(self, meta: dict[str, Any]) -> datetime:
        value = meta.get("time_utc")
        if isinstance(value, str) and value:
            with contextlib.suppress(ValueError):
                return parse_aisstream_timestamp(value)
        # time_utc is server receipt time anyway; a missing one falls back to now.
        return utcnow()

    @staticmethod
    def _length(payload: dict[str, Any]) -> float | None:
        a, b = payload.get("Dimension", {}).get("A"), payload.get("Dimension", {}).get("B")
        if a is None and b is None:
            return None
        return float((a or 0) + (b or 0)) or None

    @staticmethod
    def _width(payload: dict[str, Any]) -> float | None:
        c, d = payload.get("Dimension", {}).get("C"), payload.get("Dimension", {}).get("D")
        if c is None and d is None:
            return None
        return float((c or 0) + (d or 0)) or None


def _positive(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


__all__ = ["AISSTREAM_URL", "STALL_TIMEOUT_SECONDS", "AISStreamProvider"]
