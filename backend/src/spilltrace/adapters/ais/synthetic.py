"""Deterministic AIS traffic for an arbitrary bounding box and time window.

The demo scenario generator (``spilltrace.demo.ais``) produces a *curated cast* whose
geometry is arranged to exercise the scoring model.  This provider is different: it
answers the generic question "what vessels were in this box during this window" for any
case, so a REAL-mode pipeline can run end to end without an AIS account.

It is seeded from the bounding box and window themselves, so the same case always yields
the same traffic — a case an analyst re-opens tomorrow must not have different ships in
it.  Everything it emits is labelled ``SYNTHETIC`` and vessel names carry the suffix.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta

import numpy as np

from spilltrace.core.enums import DataProvenance
from spilltrace.core.geometry import destination_point
from spilltrace.core.ports import AISMessage
from spilltrace.core.provenance import label_synthetic

#: Reporting interval.  Class A transmits every 2-10 s under way; aggregators typically
#: deliver a decimated feed, and 3 minutes keeps a multi-day window tractable.
REPORT_INTERVAL_SECONDS = 180

#: How many vessels to place in a box.  Scaled by area so a small AOI is not implausibly
#: crowded and a large one is not implausibly empty.
VESSELS_PER_10000_KM2 = 4
MIN_VESSELS = 4
MAX_VESSELS = 14

_SHIP_TYPES: tuple[tuple[int, str], ...] = (
    (80, "Tanker"),
    (70, "Cargo"),
    (30, "Fishing"),
    (60, "Passenger"),
    (52, "Tug"),
)
_FLAGS: tuple[tuple[int, str], ...] = (
    (419, "India"),
    (477, "Hong Kong"),
    (636, "Liberia"),
    (538, "Marshall Islands"),
    (563, "Singapore"),
    (525, "Indonesia"),
)
_NAME_PARTS: tuple[tuple[str, ...], tuple[str, ...]] = (
    (
        "SAGAR",
        "EASTERN",
        "ATLANTIC",
        "PACIFIC",
        "STRAITS",
        "NORTHERN",
        "CORAL",
        "MONSOON",
        "ARABIAN",
        "GULF",
        "OCEAN",
        "SOUTHERN",
        "DELTA",
        "HORIZON",
    ),
    (
        "PRABHA",
        "ORCHID",
        "MERIDIAN",
        "HALCYON",
        "VOYAGER",
        "PIONEER",
        "TRADER",
        "SPIRIT",
        "MARINER",
        "STAR",
        "DAWN",
        "CREST",
        "HARMONY",
        "ENDEAVOUR",
    ),
)


def _seed_for(bbox: tuple[float, float, float, float], start: datetime, end: datetime) -> int:
    """A stable seed derived from the query itself.

    Using the query rather than a clock means re-running a case reproduces its traffic,
    which is what makes the synthetic path usable as a fixture rather than noise.
    """
    key = (
        f"{bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f}"
        f"|{start.isoformat()}|{end.isoformat()}"
    )
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % (2**31)


def _vessel_count(bbox: tuple[float, float, float, float]) -> int:
    from spilltrace.core.geometry import bbox_polygon, geodesic_area_km2

    area = geodesic_area_km2(bbox_polygon(*bbox))
    scaled = round(area / 10_000.0 * VESSELS_PER_10000_KM2)
    return max(MIN_VESSELS, min(MAX_VESSELS, scaled))


class SyntheticAISProvider:
    """Implements :class:`spilltrace.core.ports.AISProvider`."""

    name = "synthetic"

    async def historical(
        self, *, bbox: tuple[float, float, float, float], start: datetime, end: datetime
    ) -> list[AISMessage]:
        rng = np.random.default_rng(_seed_for(bbox, start, end))
        min_lon, min_lat, max_lon, max_lat = bbox
        count = _vessel_count(bbox)

        messages: list[AISMessage] = []
        for index in range(count):
            mid, flag = _FLAGS[int(rng.integers(len(_FLAGS)))]
            mmsi = int(mid) * 1_000_000 + int(rng.integers(100_000, 999_999))
            ship_type, type_name = _SHIP_TYPES[int(rng.integers(len(_SHIP_TYPES)))]
            first, second = _NAME_PARTS
            name = f"{first[index % len(first)]} {second[(index * 5 + 3) % len(second)]}"

            # A transit that crosses the box: enter on one edge, leave on another.
            course = float(rng.uniform(0.0, 360.0))
            speed = float(rng.uniform(3.0, 6.0) if ship_type == 30 else rng.uniform(9.0, 16.0))
            entry_lon = float(rng.uniform(min_lon, max_lon))
            entry_lat = float(rng.uniform(min_lat, max_lat))
            # Back the vessel up so its track spans the window rather than starting mid-box.
            span_hours = (end - start).total_seconds() / 3600.0
            back_m = speed * 0.514444 * (span_hours * 3600.0) / 2.0
            origin_lon, origin_lat = destination_point(
                entry_lon, entry_lat, (course + 180.0) % 360.0, back_m
            )

            messages.extend(
                self._track(
                    mmsi=mmsi,
                    name=name,
                    ship_type=ship_type,
                    type_name=type_name,
                    flag=flag,
                    origin=(origin_lon, origin_lat),
                    course=course,
                    speed_knots=speed,
                    start=start,
                    end=end,
                    rng=rng,
                )
            )

        messages.sort(key=lambda m: (m.timestamp, m.mmsi))
        return messages

    def stream(
        self,
        *,
        bboxes: Sequence[tuple[float, float, float, float]],
        message_types: Sequence[str] = ("PositionReport", "ShipStaticData"),
    ) -> AsyncIterator[AISMessage]:
        """Replay synthetic traffic as if it were arriving live."""

        async def _generate() -> AsyncIterator[AISMessage]:
            import asyncio

            from spilltrace.core.time import utcnow

            now = utcnow()
            for bbox in bboxes:
                for message in await self.historical(
                    bbox=bbox, start=now - timedelta(hours=1), end=now
                ):
                    if message.message_type in message_types:
                        yield message
                        await asyncio.sleep(0)

        return _generate()

    def _track(
        self,
        *,
        mmsi: int,
        name: str,
        ship_type: int,
        type_name: str,
        flag: str,
        origin: tuple[float, float],
        course: float,
        speed_knots: float,
        start: datetime,
        end: datetime,
        rng: np.random.Generator,
    ) -> list[AISMessage]:
        display_name = label_synthetic(name, DataProvenance.SYNTHETIC)
        step = timedelta(seconds=REPORT_INTERVAL_SECONDS)
        steps = int((end - start).total_seconds() // REPORT_INTERVAL_SECONDS) + 1
        speed_ms = speed_knots * 0.514444

        out: list[AISMessage] = []
        for i in range(steps):
            when = start + i * step
            distance = speed_ms * i * REPORT_INTERVAL_SECONDS
            lon, lat = destination_point(origin[0], origin[1], course, distance)
            out.append(
                AISMessage(
                    mmsi=mmsi,
                    timestamp=when,
                    latitude=round(lat + float(rng.normal(0.0, 0.00009)), 6),
                    longitude=round(lon + float(rng.normal(0.0, 0.00010)), 6),
                    message_type="PositionReport",
                    source="SYNTHETIC",
                    sog_knots=round(max(0.0, speed_knots + float(rng.normal(0.0, 0.25))), 2),
                    cog_deg=round(float((course + rng.normal(0.0, 1.6)) % 360.0), 1),
                    heading_deg=round(float((course + rng.normal(0.0, 1.1)) % 360.0), 0),
                    nav_status=0,
                    name=display_name,
                    data_provenance=DataProvenance.SYNTHETIC,
                    raw={"synthetic": True, "generator": "SyntheticAISProvider"},
                )
            )

        if out:
            middle = out[len(out) // 2]
            out.append(
                AISMessage(
                    mmsi=mmsi,
                    timestamp=middle.timestamp,
                    latitude=middle.latitude,
                    longitude=middle.longitude,
                    message_type="ShipStaticData",
                    source="SYNTHETIC",
                    name=display_name,
                    imo=9_000_000 + (mmsi % 999_999),
                    callsign=f"S{mmsi % 100000:05d}",
                    ship_type=ship_type,
                    destination="KANDLA" if mmsi % 2 == 0 else "MUNDRA",
                    length_m=float(round(rng.uniform(60.0, 250.0), 1)),
                    width_m=float(round(rng.uniform(12.0, 44.0), 1)),
                    data_provenance=DataProvenance.SYNTHETIC,
                    raw={"synthetic": True, "flag": flag, "ship_type_name": type_name},
                )
            )
        return out


__all__ = ["REPORT_INTERVAL_SECONDS", "SyntheticAISProvider"]
