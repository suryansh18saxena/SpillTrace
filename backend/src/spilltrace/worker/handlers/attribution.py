"""``correlate`` and ``score`` — the attribution stages (FR-014…FR-016, AC-09, AC-10).

``correlate`` finds vessels compatible with the origin region and window.
``score`` runs the PRD Part J model over them and stores every factor separately.

Neither stage ever pads the candidate list, and neither writes a conclusion the evidence
does not support.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import delete, select

from spilltrace.core.correlation import (
    DEFAULT_BUFFER_KM,
    DEFAULT_TIME_TOLERANCE_HOURS,
    CandidateEvidence,
    correlate_track,
)
from spilltrace.core.disclaimers import ATTRIBUTION_DISCLAIMER
from spilltrace.core.enums import DataProvenance, JobType
from spilltrace.core.errors import NoDataError
from spilltrace.core.provenance import RunManifest, combine_provenance
from spilltrace.core.scoring import (
    DEFAULT_WEIGHTS,
    SCORING_VERSION,
    OriginContext,
    ScoringWeights,
    SpillContext,
    TrackContext,
    TrackSample,
    VesselContext,
    rank_candidates,
    score_candidate,
    shortfall_note,
)
from spilltrace.db.models import (
    AISPosition,
    Attribution,
    DriftRun,
    SpillDetection,
    Trajectory,
    Vessel,
)
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register


@register(JobType.CORRELATE)
async def correlate_vessels(ctx: JobContext) -> dict[str, Any]:
    drift_run = await _latest_drift_run(ctx)
    if drift_run.origin_geometry is None:
        raise NoDataError("The drift run produced no origin region, so no vessels were compared.")
    if drift_run.inferred_start is None or drift_run.inferred_end is None:
        raise NoDataError("The drift run produced no inferred discharge window.")

    origin_region = to_shape(drift_run.origin_geometry)
    contours = [
        (float(f["properties"]["probability_mass"]), f["geometry"])
        for f in (drift_run.contours or {}).get("features", [])
    ]

    buffer_km = float(ctx.payload.get("correlation_buffer_km", DEFAULT_BUFFER_KM))
    tolerance = float(ctx.payload.get("time_tolerance_hours", DEFAULT_TIME_TOLERANCE_HOURS))

    tracks = await _case_tracks(ctx)
    if not tracks:
        raise NoDataError(
            "No vessel tracks are available for this case, so no candidates could be "
            "identified. AIS coverage is not complete; absence of a vessel here is not "
            "evidence that none was present."
        )

    candidates: list[dict[str, Any]] = []
    for index, (mmsi, samples) in enumerate(sorted(tracks.items())):
        await ctx.progress(index / len(tracks), f"correlating MMSI {mmsi}")
        evidence = correlate_track(
            mmsi=mmsi,
            samples=samples,
            origin_region=origin_region,
            contours=contours,
            window_start=drift_run.inferred_start,
            window_end=drift_run.inferred_end,
            buffer_km=buffer_km,
            time_tolerance_hours=tolerance,
        )
        if evidence is not None:
            candidates.append(evidence.to_dict())

    await ctx.progress(1.0, f"{len(candidates)} candidate vessel(s) identified")
    note = shortfall_note(len(candidates))
    ctx.log("correlation_complete", candidates=len(candidates), considered=len(tracks))
    return {
        "drift_run_id": str(drift_run.id),
        "considered_vessels": len(tracks),
        "candidates": candidates,
        "buffer_km": buffer_km,
        "time_tolerance_hours": tolerance,
        "shortfall_note": note,
    }


@register(JobType.SCORE)
async def score_candidates(ctx: JobContext) -> dict[str, Any]:
    drift_run = await _latest_drift_run(ctx)
    detection = await ctx.session.get(SpillDetection, drift_run.spill_id)
    if detection is None:
        raise NoDataError("The detection this drift run was based on no longer exists.")
    if drift_run.origin_geometry is None:
        raise NoDataError("No origin region is available, so candidates cannot be scored.")
    if drift_run.inferred_start is None or drift_run.inferred_end is None:
        # Correlation already refuses this case; scoring must too, or it would compare
        # every vessel against a window of None and silently score them all on geometry.
        raise NoDataError(
            "The drift run produced no inferred discharge window, so time compatibility "
            "cannot be assessed and candidates cannot be scored."
        )

    weights = _weights_from(ctx.payload.get("weights"))
    origin_region = to_shape(drift_run.origin_geometry)
    contours = [
        (float(f["properties"]["probability_mass"]), f["geometry"])
        for f in (drift_run.contours or {}).get("features", [])
    ]
    centroid = to_shape(detection.centroid)

    spill = SpillContext(
        detection_time=detection.detected_at,
        centroid_lon=centroid.x,
        centroid_lat=centroid.y,
        geometry_geojson=_mapping(detection.geometry),
        data_provenance=DataProvenance(detection.data_provenance),
    )
    origin = OriginContext(
        region_geojson=_mapping(drift_run.origin_geometry),
        contours=contours,
        window_start=drift_run.inferred_start,
        window_end=drift_run.inferred_end,
        origin_confidence=drift_run.origin_confidence,
        data_provenance=DataProvenance(drift_run.data_provenance),
    )

    tracks = await _case_tracks(ctx)
    vessels = {v.mmsi: v for v in (await ctx.session.execute(select(Vessel))).scalars().all()}
    trajectories: dict[Any, list[Trajectory]] = {}
    for row in (
        (await ctx.session.execute(select(Trajectory).where(Trajectory.case_id == ctx.case_id)))
        .scalars()
        .all()
    ):
        trajectories.setdefault(row.vessel_id, []).append(row)

    rejected_by_mmsi = await _rejected_counts(ctx)

    buffer_km = float(ctx.payload.get("correlation_buffer_km", DEFAULT_BUFFER_KM))
    tolerance = float(ctx.payload.get("time_tolerance_hours", DEFAULT_TIME_TOLERANCE_HOURS))

    scored = []
    evidences: dict[int, CandidateEvidence] = {}
    for index, (mmsi, samples) in enumerate(sorted(tracks.items())):
        await ctx.progress(0.1 + 0.6 * index / max(1, len(tracks)), f"scoring MMSI {mmsi}")
        evidence = correlate_track(
            mmsi=mmsi,
            samples=samples,
            origin_region=origin_region,
            contours=contours,
            window_start=drift_run.inferred_start,
            window_end=drift_run.inferred_end,
            buffer_km=buffer_km,
            time_tolerance_hours=tolerance,
        )
        if evidence is None:
            continue
        evidences[mmsi] = evidence

        vessel = vessels.get(mmsi)
        if vessel is None:
            continue
        segments = trajectories.get(vessel.id, [])
        track = _track_context(samples, vessel, segments, rejected_by_mmsi.get(mmsi, 0))
        attribution = score_candidate(
            spill,
            origin,
            VesselContext(
                mmsi=mmsi,
                imo=vessel.imo,
                name=vessel.name,
                ship_type=vessel.ship_type_name,
                data_provenance=DataProvenance(vessel.data_provenance),
            ),
            track,
            weights,
        )
        scored.append((attribution, vessel, segments, evidence))

    if not scored:
        note = shortfall_note(0)
        ctx.log("scoring_no_candidates")
        return {"attributions": [], "candidate_count": 0, "shortfall_note": note}

    # The drift stage's own confidence in the region feeds the discrimination check:
    # candidates measured against a diffuse region are not strong evidence.
    ranked = rank_candidates([s[0] for s in scored], origin_confidence=drift_run.origin_confidence)
    by_mmsi = {a.vessel_ref.mmsi: a for a in ranked}

    await ctx.progress(0.8, "storing attribution results")
    await ctx.session.execute(
        delete(Attribution).where(
            Attribution.case_id == ctx.case_id,
            Attribution.scoring_version == SCORING_VERSION,
        )
    )
    await ctx.session.flush()

    manifest = RunManifest(
        stage="score",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        parameters={
            "weights": weights.to_dict(),
            "scoring_version": SCORING_VERSION,
            "correlation_buffer_km": buffer_km,
            "time_tolerance_hours": tolerance,
        },
        data_provenance=combine_provenance(detection.data_provenance, drift_run.data_provenance),
    ).note(ATTRIBUTION_DISCLAIMER)

    stored: list[dict[str, Any]] = []
    for _attribution, vessel, segments, evidence in scored:
        ranked_attribution = by_mmsi[vessel.mmsi]
        factors = {f.key.value: f for f in ranked_attribution.factors}
        ctx.session.add(
            Attribution(
                case_id=ctx.case_id,
                spill_id=detection.id,
                drift_run_id=drift_run.id,
                vessel_id=vessel.id,
                trajectory_id=segments[0].id if segments else None,
                origin_proximity=factors["origin_proximity"].score,
                time_match=factors["time_match"].score,
                trajectory_match=factors["trajectory_match"].score,
                heading_match=factors["heading_match"].score,
                speed_match=factors["speed_match"].score,
                ais_reliability=factors["ais_reliability"].score,
                final_score=ranked_attribution.final_score,
                rank=ranked_attribution.rank,
                weights=weights.to_dict(),
                factor_explanations={
                    key: {
                        "label": f.label,
                        "weight": f.weight,
                        "score": f.score,
                        "contribution": f.contribution,
                        "explanation": f.explanation,
                        "evidence": f.evidence,
                    }
                    for key, f in factors.items()
                },
                evidence={
                    "correlation": evidence.to_dict(),
                    "confidence_label": str(ranked_attribution.confidence_label),
                    "discrimination_note": ranked_attribution.discrimination_note,
                    "disclaimer": ATTRIBUTION_DISCLAIMER,
                },
                closest_approach_km=evidence.closest_approach_km,
                closest_approach_time=evidence.closest_approach_time,
                scoring_version=SCORING_VERSION,
                data_provenance=str(
                    combine_provenance(vessel.data_provenance, detection.data_provenance)
                ),
                run_manifest=manifest.to_dict(),
            )
        )
        stored.append(
            {
                "rank": ranked_attribution.rank,
                "mmsi": vessel.mmsi,
                "name": vessel.name,
                "final_score": round(ranked_attribution.final_score, 4),
                "confidence_label": str(ranked_attribution.confidence_label),
                "closest_approach_km": round(evidence.closest_approach_km, 2),
            }
        )

    await ctx.session.flush()
    await ctx.progress(1.0, f"{len(stored)} vessel(s) ranked")
    ctx.log("scoring_complete", ranked=len(stored))
    stored.sort(key=lambda row: row["rank"])
    return {
        "attributions": stored,
        "candidate_count": len(stored),
        "scoring_version": SCORING_VERSION,
        "weights": weights.to_dict(),
        "shortfall_note": shortfall_note(len(stored)),
        "disclaimer": ATTRIBUTION_DISCLAIMER,
    }


# --------------------------------------------------------------------------- helpers
async def _latest_drift_run(ctx: JobContext) -> DriftRun:
    run = (
        await ctx.session.execute(
            select(DriftRun)
            .where(DriftRun.case_id == ctx.case_id, DriftRun.status == "COMPLETED")
            .order_by(DriftRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        raise NoDataError(
            "No completed reverse-drift run exists for this case. Run the drift stage "
            "before correlating vessels."
        )
    return run


async def _case_tracks(
    ctx: JobContext,
) -> dict[int, list[tuple[Any, float, float, float | None, float | None]]]:
    """Valid AIS positions for the case window, grouped by MMSI.

    Only positions the cleaner accepted shape a track: a rejected fix stays in the
    record as evidence but must not move a vessel's apparent position.
    """
    from spilltrace.db.models import Case

    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        return {}

    rows = list(
        (
            await ctx.session.execute(
                select(AISPosition)
                .where(
                    AISPosition.is_valid,
                    AISPosition.timestamp >= case.start_time,
                    AISPosition.timestamp <= case.end_time,
                )
                .order_by(AISPosition.mmsi, AISPosition.timestamp)
            )
        )
        .scalars()
        .all()
    )
    tracks: dict[int, list[tuple[Any, float, float, float | None, float | None]]] = {}
    for row in rows:
        point = to_shape(row.position)
        tracks.setdefault(row.mmsi, []).append(
            (row.timestamp, point.x, point.y, row.sog_knots, row.cog_deg)
        )
    return tracks


def _track_context(
    samples: list[tuple[Any, float, float, float | None, float | None]],
    vessel: Vessel,
    segments: list[Trajectory],
    rejected_count: int,
) -> TrackContext:
    """Build the AIS-reliability inputs from a vessel's **whole** record.

    Trajectory rows are *segments*: ``build_trajectories`` splits a track wherever
    reporting stops for 30 minutes or more, so each segment has, by construction, no
    internal gap worth reporting.  Reading gap statistics off a single segment would
    therefore show a vessel with a 14-hour dark period as having no gaps at all — the
    reliability factor would silently stop measuring the thing it exists to measure.

    So the gaps *between* consecutive segments are reconstructed here and combined with
    whatever intra-segment gaps survived.
    """
    track_samples = [
        TrackSample(timestamp=t, lon=lon, lat=lat, sog_knots=sog, cog_deg=cog)
        for t, lon, lat, sog, cog in samples
    ]

    ordered = sorted(segments, key=lambda s: s.time_start)
    gap_count = sum(s.gap_count for s in ordered)
    max_gap = max((s.max_gap_minutes for s in ordered), default=0.0)
    total_gap = sum(s.total_gap_minutes for s in ordered)

    for previous, following in pairwise(ordered):
        between = (following.time_start - previous.time_end).total_seconds() / 60.0
        if between > 0:
            gap_count += 1
            total_gap += between
            max_gap = max(max_gap, between)

    # Coverage is measured across the span the vessel was observed over, so a vessel
    # seen briefly is not penalised for the hours before it arrived.
    coverage: float | None = None
    if ordered:
        span_minutes = (ordered[-1].time_end - ordered[0].time_start).total_seconds() / 60.0
        observed = sum(s.position_count for s in ordered)
        expected = max(1.0, span_minutes / 3.0)  # one report per 3 minutes, conservative
        coverage = min(1.0, observed / expected)

    return TrackContext(
        samples=track_samples,
        position_count=len(track_samples),
        rejected_count=rejected_count,
        coverage_ratio=coverage,
        gap_count=gap_count,
        max_gap_minutes=max_gap,
        total_gap_minutes=total_gap,
        static_completeness=vessel.static_completeness,
        data_provenance=DataProvenance(vessel.data_provenance),
    )


async def _rejected_counts(ctx: JobContext) -> dict[int, int]:
    """How many positions the cleaner rejected per vessel, for the cleanliness sub-score."""
    from sqlalchemy import func

    from spilltrace.db.models import Case

    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        return {}
    rows = (
        await ctx.session.execute(
            select(AISPosition.mmsi, func.count())
            .where(
                AISPosition.is_valid.is_(False),
                AISPosition.timestamp >= case.start_time,
                AISPosition.timestamp <= case.end_time,
            )
            .group_by(AISPosition.mmsi)
        )
    ).all()
    return {int(mmsi): int(count) for mmsi, count in rows}


def _weights_from(raw: Any) -> ScoringWeights:
    if not isinstance(raw, dict) or not raw:
        return DEFAULT_WEIGHTS
    weights = ScoringWeights(
        origin_proximity=float(raw.get("origin_proximity", DEFAULT_WEIGHTS.origin_proximity)),
        time_match=float(raw.get("time_match", DEFAULT_WEIGHTS.time_match)),
        trajectory_match=float(raw.get("trajectory_match", DEFAULT_WEIGHTS.trajectory_match)),
        heading_match=float(raw.get("heading_match", DEFAULT_WEIGHTS.heading_match)),
        speed_match=float(raw.get("speed_match", DEFAULT_WEIGHTS.speed_match)),
        ais_reliability=float(raw.get("ais_reliability", DEFAULT_WEIGHTS.ais_reliability)),
    )
    weights.validate()
    return weights


def _mapping(geometry: Any) -> dict[str, Any] | None:
    if geometry is None:
        return None
    from shapely.geometry import mapping

    return mapping(to_shape(geometry))


__all__ = ["correlate_vessels", "score_candidates"]
