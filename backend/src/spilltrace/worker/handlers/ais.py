"""``ais.clean`` and ``traj.build`` (FR-012, FR-013, AC-08).

These handlers are thin: all the judgement lives in ``spilltrace.core.ais``, which is
pure and unit-tested.  Their job is to move rows in and out of PostGIS and to record
what the cleaner decided, including for the positions it rejected — evidence is never
deleted, only annotated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import select

from spilltrace.adapters.ais import build_ais_provider
from spilltrace.core.ais import (
    build_trajectories,
    clean_track,
    cleaning_summary,
    summarise_gaps,
)
from spilltrace.core.disclaimers import AIS_COVERAGE_DISCLAIMER
from spilltrace.core.enums import DataProvenance, JobType
from spilltrace.core.errors import NoDataError, ProviderError
from spilltrace.core.geometry import bbox_of
from spilltrace.core.ports import AISMessage
from spilltrace.core.time import utcnow
from spilltrace.db.models import AISPosition, Case, Trajectory, Vessel
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register


@register(JobType.AIS_CLEAN)
async def clean_ais(ctx: JobContext) -> dict[str, Any]:
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")

    rows = list(
        (
            await ctx.session.execute(
                select(AISPosition)
                .where(
                    AISPosition.timestamp >= case.start_time,
                    AISPosition.timestamp <= case.end_time,
                )
                .order_by(AISPosition.mmsi, AISPosition.timestamp)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise NoDataError(
            "No AIS positions are stored for this case's time window. AIS coverage is "
            "not complete, so this may mean no vessel was there, or that none was seen."
        )

    by_mmsi: dict[int, list[AISPosition]] = defaultdict(list)
    for row in rows:
        by_mmsi[row.mmsi].append(row)

    now = utcnow()
    totals = {"total": 0, "valid": 0, "rejected": 0}
    per_vessel: list[dict[str, Any]] = []

    for index, (mmsi, positions) in enumerate(sorted(by_mmsi.items())):
        await ctx.progress(
            index / len(by_mmsi), f"cleaning AIS for MMSI {mmsi} ({index + 1}/{len(by_mmsi)})"
        )
        messages = [_to_message(p) for p in positions]
        cleaned = clean_track(messages, now=now)

        # clean_track returns positions in time order; pair them back to their rows by
        # (timestamp, lon, lat) rather than by index, because ordering may differ.
        lookup = {
            (p.timestamp, round(to_shape(p.position).x, 6), round(to_shape(p.position).y, 6)): p
            for p in positions
        }
        for result in cleaned:
            key = (
                result.message.timestamp,
                round(result.message.longitude, 6),
                round(result.message.latitude, 6),
            )
            matched = lookup.get(key)
            if matched is None:
                continue
            row = matched
            row.is_valid = result.is_valid
            row.quality_flags = [f.value for f in result.flags]
            row.rejection_reason = result.rejection_reason

        summary = cleaning_summary(cleaned)
        totals["total"] += len(cleaned)
        totals["valid"] += sum(1 for c in cleaned if c.is_valid)
        totals["rejected"] += sum(1 for c in cleaned if not c.is_valid)
        per_vessel.append({"mmsi": mmsi, **{k: v for k, v in summary.items() if k != "notes"}})

    await ctx.session.flush()
    await ctx.progress(1.0, "AIS cleaning complete")
    ctx.log("ais_cleaned", **totals, vessels=len(by_mmsi))
    return {
        "vessels": len(by_mmsi),
        **totals,
        "per_vessel": per_vessel,
        "note": (
            "Rejected positions are retained and flagged, not deleted. A rejection "
            "records a data-quality judgement about a message, not about a vessel."
        ),
    }


@register(JobType.TRAJ_BUILD)
async def build_case_trajectories(ctx: JobContext) -> dict[str, Any]:
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")

    rows = list(
        (
            await ctx.session.execute(
                select(AISPosition)
                .where(
                    AISPosition.timestamp >= case.start_time,
                    AISPosition.timestamp <= case.end_time,
                )
                .order_by(AISPosition.mmsi, AISPosition.timestamp)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise NoDataError("No AIS positions are available, so no trajectories were built.")

    vessels = {v.mmsi: v for v in (await ctx.session.execute(select(Vessel))).scalars().all()}

    # Replace this case's trajectories so a re-run does not accumulate duplicates.
    for existing in (
        (await ctx.session.execute(select(Trajectory).where(Trajectory.case_id == case.id)))
        .scalars()
        .all()
    ):
        await ctx.session.delete(existing)
    await ctx.session.flush()

    by_mmsi: dict[int, list[AISPosition]] = defaultdict(list)
    for row in rows:
        by_mmsi[row.mmsi].append(row)

    now = utcnow()
    built: list[dict[str, Any]] = []
    for index, (mmsi, positions) in enumerate(sorted(by_mmsi.items())):
        await ctx.progress(index / len(by_mmsi), f"building trajectory for MMSI {mmsi}")
        vessel = vessels.get(mmsi)
        if vessel is None:
            continue

        provenance = DataProvenance(vessel.data_provenance or DataProvenance.REAL.value)
        cleaned = clean_track([_to_message(p, provenance=provenance) for p in positions], now=now)
        segments = build_trajectories(cleaned)
        for segment in segments:
            if len(segment.geometry) < 2:
                # A single sighting is a real observation but not a line; it is recorded
                # in the AIS positions and reported in the statistics below.
                built.append(
                    {
                        "mmsi": mmsi,
                        "position_count": segment.position_count,
                        "geometry": False,
                        "quality_flags": [f.value for f in segment.quality_flags],
                    }
                )
                continue
            gap_summary = summarise_gaps(segment.gaps)
            ctx.session.add(
                Trajectory(
                    vessel_id=vessel.id,
                    case_id=case.id,
                    time_start=segment.start_time,
                    time_end=segment.end_time,
                    geometry=from_shape(LineString(segment.geometry), srid=4326),
                    position_count=segment.position_count,
                    distance_km=segment.distance_km,
                    duration_hours=segment.duration_hours,
                    mean_sog_knots=segment.mean_sog_knots,
                    max_sog_knots=segment.max_sog_knots,
                    gap_count=segment.gap_count,
                    max_gap_minutes=segment.max_gap_minutes,
                    total_gap_minutes=segment.total_gap_minutes,
                    coverage_ratio=segment.coverage_ratio,
                    quality_score=segment.quality_score,
                    quality_flags=[f.value for f in segment.quality_flags],
                    data_provenance=vessel.data_provenance or DataProvenance.REAL.value,
                )
            )
            built.append(
                {
                    "mmsi": mmsi,
                    "position_count": segment.position_count,
                    "distance_km": round(segment.distance_km, 3),
                    "duration_hours": round(segment.duration_hours, 3),
                    "coverage_ratio": round(segment.coverage_ratio, 3),
                    "quality_score": round(segment.quality_score, 3),
                    "gap_count": segment.gap_count,
                    "max_gap_minutes": round(segment.max_gap_minutes, 1),
                    "geometry": True,
                    "gaps": gap_summary,
                }
            )

    await ctx.session.flush()
    await ctx.progress(1.0, "trajectories built")
    with_geometry = sum(1 for b in built if b["geometry"])
    ctx.log("trajectories_built", segments=with_geometry, vessels=len(by_mmsi))
    return {"vessels": len(by_mmsi), "segments": with_geometry, "detail": built}


def _to_message(
    row: AISPosition, *, provenance: DataProvenance = DataProvenance.REAL
) -> AISMessage:
    """Convert a stored position into the cleaner's input type.

    Provenance is passed in rather than read from ``row.vessel``: touching a lazy
    relationship here would trigger implicit IO inside an async context and fail with
    ``MissingGreenlet``.
    """
    point = to_shape(row.position)
    return AISMessage(
        mmsi=row.mmsi,
        timestamp=row.timestamp,
        latitude=point.y,
        longitude=point.x,
        message_type=row.message_type or "PositionReport",
        source=row.source,
        sog_knots=row.sog_knots,
        cog_deg=row.cog_deg,
        heading_deg=row.heading_deg,
        rot=row.rot,
        nav_status=row.nav_status,
        raw=row.raw or {},
        data_provenance=provenance,
    )


@register(JobType.AIS_INGEST)
async def ingest_ais(ctx: JobContext) -> dict[str, Any]:
    """``ais.ingest`` — fetch AIS for the case bounding box and time window (FR-011).

    Positions are stored **raw**: ``is_valid`` stays true and no quality flag is set,
    because deciding validity is ``ais.clean``'s job. Pre-filtering here would hide the
    defects the cleaning stage exists to find, and would make the two stages disagree
    about what the feed actually contained.
    """
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")

    provider = build_ais_provider(ctx.settings)
    bbox = bbox_of(to_shape(case.aoi), buffer_km=25.0)

    await ctx.progress(0.1, f"requesting AIS from {provider.name}")
    try:
        messages = await provider.historical(bbox=bbox, start=case.start_time, end=case.end_time)
    except ProviderError as exc:
        # A live stream genuinely cannot answer a question about the past.  What it
        # *can* do is have been listening: the ais-ingestor stores every message it
        # receives, so if the case window is covered by stored positions the later
        # stages can proceed on those.  Either way the situation is stated, never
        # disguised as "no vessels were there".
        stored = await _stored_positions_in_window(ctx, bbox, case.start_time, case.end_time)
        if stored:
            raise NoDataError(
                f"{provider.name} is a live feed and cannot return past positions "
                f"({exc.message}). {stored} position(s) already stored for this area "
                "and window will be used by the following stages."
            ) from exc
        raise

    if not messages:
        raise NoDataError(
            "The AIS provider returned no messages for this area and time window. AIS "
            "coverage is not complete, so this may mean no vessel was present, or that "
            "none was observed."
        )

    await ctx.progress(0.4, f"persisting {len(messages)} AIS messages")
    counts = await _persist_messages(ctx, messages)

    await ctx.progress(1.0, "AIS ingestion complete")
    ctx.log("ais_ingested", provider=provider.name, **counts)
    return {
        "provider": provider.name,
        "bbox": list(bbox),
        **counts,
        "notice": AIS_COVERAGE_DISCLAIMER,
    }


async def _stored_positions_in_window(
    ctx: JobContext,
    bbox: tuple[float, float, float, float],
    start: Any,
    end: Any,
) -> int:
    """How many AIS positions the database already holds for this box and window."""
    from sqlalchemy import func

    envelope = func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
    stmt = select(func.count(AISPosition.id)).where(
        AISPosition.timestamp >= start,
        AISPosition.timestamp <= end,
        func.ST_Intersects(AISPosition.position, envelope),
    )
    return int((await ctx.session.execute(stmt)).scalar_one() or 0)


async def _persist_messages(ctx: JobContext, messages: list[AISMessage]) -> dict[str, Any]:
    """Upsert vessels and positions.

    AIS is a global store keyed by ``(mmsi, timestamp, source)``: two cases covering
    overlapping water and time legitimately see the same broadcasts, so re-ingesting is
    an upsert, not a duplicate.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    static_by_mmsi: dict[int, AISMessage] = {
        m.mmsi: m for m in messages if m.message_type == "ShipStaticData"
    }

    vessels: dict[int, Vessel] = {}
    for mmsi in sorted({m.mmsi for m in messages}):
        existing = (
            await ctx.session.execute(select(Vessel).where(Vessel.mmsi == mmsi))
        ).scalar_one_or_none()
        static = static_by_mmsi.get(mmsi)
        if existing is None:
            vessel = Vessel(
                mmsi=mmsi,
                imo=static.imo if static else None,
                name=static.name if static else None,
                callsign=static.callsign if static else None,
                ship_type=static.ship_type if static else None,
                ship_type_name=(static.raw or {}).get("ship_type_name") if static else None,
                flag_country=(static.raw or {}).get("flag") if static else None,
                flag_mid=int(str(mmsi)[:3]),
                length_m=static.length_m if static else None,
                width_m=static.width_m if static else None,
                draught_m=static.draught_m if static else None,
                destination=static.destination if static else None,
                source=static.source if static else "AIS",
                data_provenance=str(static.data_provenance if static else DataProvenance.REAL),
            )
            ctx.session.add(vessel)
        else:
            vessel = existing
        vessels[mmsi] = vessel
    await ctx.session.flush()

    # Static-data completeness feeds the identity component of AIS reliability.
    for vessel in vessels.values():
        present = sum(
            1.0
            for value in (
                vessel.imo,
                vessel.name,
                vessel.callsign,
                vessel.ship_type,
                vessel.length_m,
            )
            if value
        )
        vessel.static_completeness = round(present / 5.0, 3)

    rows: list[dict[str, Any]] = []
    now = utcnow()
    for message in messages:
        if message.message_type == "ShipStaticData":
            continue
        vessel = vessels[message.mmsi]
        rows.append(
            {
                "vessel_id": vessel.id,
                "mmsi": message.mmsi,
                "timestamp": message.timestamp,
                "position": from_shape(Point(message.longitude, message.latitude), srid=4326),
                "sog_knots": message.sog_knots,
                "cog_deg": message.cog_deg,
                "heading_deg": message.heading_deg,
                "rot": message.rot,
                "nav_status": message.nav_status,
                "message_type": message.message_type,
                "source": message.source,
                "is_valid": True,
                "quality_flags": [],
                "raw": message.raw,
                "ingested_at": now,
            }
        )
        if vessel.first_seen is None or message.timestamp < vessel.first_seen:
            vessel.first_seen = message.timestamp
        if vessel.last_seen is None or message.timestamp > vessel.last_seen:
            vessel.last_seen = message.timestamp

    inserted = 0
    for start in range(0, len(rows), 500):
        statement = (
            pg_insert(AISPosition)
            .values(rows[start : start + 500])
            .on_conflict_do_nothing(constraint="uq_ais_positions_dedup")
        )
        result = await ctx.session.execute(statement)
        inserted += int(getattr(result, "rowcount", 0) or 0)
        await ctx.progress(
            0.4 + 0.5 * min(1.0, (start + 500) / max(1, len(rows))),
            f"persisted {min(start + 500, len(rows))}/{len(rows)} positions",
        )

    await ctx.session.flush()
    return {
        "vessels": len(vessels),
        "messages": len(messages),
        "positions_inserted": inserted,
        "positions_already_present": len(rows) - inserted,
    }


__all__ = ["build_case_trajectories", "clean_ais", "ingest_ais"]
