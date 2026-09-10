"""``env.fetch`` and ``drift.hindcast`` (FR-008, FR-009, FR-010, AC-06, AC-07).

The hindcast is where the product's central claim is made, so two properties matter more
than anything else here:

* **Reproducibility.** The seed, engine, parameters and forcing reference are all stored,
  and re-running with them produces the same origin region (AC-07).
* **Honest uncertainty.** The output is a set of nested probability contours plus an
  inferred discharge window, never a coordinate (CON-008).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import numpy as np
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, mapping
from sqlalchemy import select

from spilltrace.adapters.drift import build_drift_engine
from spilltrace.adapters.environmental import build_environmental_provider
from spilltrace.adapters.environmental.serialize import bundle_from_bytes, bundle_to_bytes
from spilltrace.adapters.storage import build_object_store
from spilltrace.core.density import (
    DEFAULT_CONTOUR_LEVELS,
    contours_to_geojson,
    particle_density,
    probability_contours,
)
from spilltrace.core.enums import (
    ArtifactType,
    DriftEngineName,
    DriftMode,
    JobType,
    VerificationStatus,
)
from spilltrace.core.errors import NoDataError, ProcessingError
from spilltrace.core.geometry import bbox_of, bbox_polygon, geodesic_area_km2
from spilltrace.core.provenance import RunManifest
from spilltrace.core.raster import write_geotiff
from spilltrace.db.models import (
    Case,
    DriftParticle,
    DriftRun,
    EnvironmentalRun,
    EvidenceArtifact,
    SpillDetection,
    VerificationResult,
)
from spilltrace.demo.environment import summarise
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register

#: How far back to integrate.  Long enough to cover a plausible transit since discharge,
#: short enough that accumulated forcing error does not swamp the signal.
DEFAULT_DURATION_HOURS = 18.0
DEFAULT_TIME_STEP_SECONDS = 900
DEFAULT_PARTICLES = 6000
DEFAULT_ENSEMBLE_MEMBERS = 6
#: Particle states written to the database for the map; the full run goes to storage.
MAX_PERSISTED_PARTICLES = 1200


@register(JobType.ENV_FETCH)
async def fetch_environment(ctx: JobContext) -> dict[str, Any]:
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")

    existing = (
        (
            await ctx.session.execute(
                select(EnvironmentalRun).where(EnvironmentalRun.case_id == case.id)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None and not ctx.payload.get("force"):
        ctx.log("environment_reused", environmental_run_id=str(existing.id))
        return {"environmental_run_id": str(existing.id), "reused": True}

    provider = build_environmental_provider(ctx.settings)
    aoi = to_shape(case.aoi)
    bbox = bbox_of(aoi, buffer_km=25.0)

    await ctx.progress(0.2, f"retrieving wind and current from {provider.name}")
    bundle = await provider.fetch(bbox=bbox, start=case.start_time, end=case.end_time)

    await ctx.progress(0.7, "storing environmental subset")
    store = build_object_store(ctx.settings)
    payload = bundle_to_bytes(bundle)
    stored = await store.put_bytes(
        f"environment/{case.id}/{uuid.uuid4()}.npz", payload, media_type="application/octet-stream"
    )

    run = EnvironmentalRun(
        case_id=case.id,
        source=bundle.source,
        provider=provider.name,
        dataset_id=next(iter(bundle.dataset_ids.values()), None),
        variables=[
            bundle.wind_u.variable,
            bundle.wind_v.variable,
            bundle.current_u.variable,
            bundle.current_v.variable,
        ],
        time_start=case.start_time,
        time_end=case.end_time,
        extent=from_shape(bbox_polygon(*bbox), srid=4326),
        grid_resolution_deg=abs(bundle.wind_u.lons[1] - bundle.wind_u.lons[0])
        if len(bundle.wind_u.lons) > 1
        else None,
        storage_uri=stored.uri,
        checksum_sha256=stored.checksum_sha256,
        size_bytes=stored.size_bytes,
        status="COMPLETED",
        summary=summarise(bundle),
        data_provenance=str(bundle.data_provenance),
        run_manifest=RunManifest(
            stage="env.fetch",
            software_version=ctx.settings.version,
            git_sha=ctx.settings.git_sha,
            provider=provider.name,
            provider_parameters={"bbox": list(bbox)},
            data_provenance=bundle.data_provenance,
        ).to_dict(),
    )
    ctx.session.add(run)
    await ctx.session.flush()
    await ctx.progress(1.0, "environmental data ready")
    return {"environmental_run_id": str(run.id), "source": bundle.source}


@register(JobType.DRIFT_HINDCAST)
async def run_hindcast(ctx: JobContext) -> dict[str, Any]:
    detection = await _select_detection(ctx)
    env_run, bundle = await _load_environment(ctx)

    params = ctx.payload.get("drift", {}) if isinstance(ctx.payload.get("drift"), dict) else {}
    duration_hours = float(params.get("duration_hours", DEFAULT_DURATION_HOURS))
    time_step = int(params.get("time_step_seconds", DEFAULT_TIME_STEP_SECONDS))
    particles = int(params.get("number_of_particles", DEFAULT_PARTICLES))
    members = int(params.get("ensemble_members", DEFAULT_ENSEMBLE_MEMBERS))
    seed = int(params.get("seed", ctx.payload.get("seed", 42)))

    engine = build_drift_engine(ctx.settings)
    await ctx.progress(0.05, f"running reverse drift with the {engine.name} engine")

    geometry = to_shape(detection.geometry)
    result = await engine.simulate(
        seed_geojson=mapping(geometry),
        start_time=detection.detected_at,
        mode=DriftMode.BACKWARD,
        duration_hours=duration_hours,
        time_step_seconds=time_step,
        number_of_particles=particles,
        environment=bundle,
        seed=seed,
        ensemble_members=members,
        parameters=params,
        progress=lambda *, fraction, message: ctx.progress(0.05 + 0.6 * fraction, message),
    )
    if not result.particles:
        raise ProcessingError("The drift engine returned no particles.")

    await ctx.progress(0.7, "aggregating particle density")
    final_step = max(p.step_index for p in result.particles)
    endpoints = [p for p in result.particles if p.step_index == final_step]
    lons = np.array([p.lon for p in endpoints])
    lats = np.array([p.lat for p in endpoints])

    grid = particle_density(lons, lats, resolution_deg=0.01)
    contours = probability_contours(grid, DEFAULT_CONTOUR_LEVELS)
    if not contours:
        raise ProcessingError("Particle density produced no probability contours.")

    # The outermost contour is the origin region; the tighter ones are stored alongside
    # so the UI and the scoring stage can say *how* deep inside a vessel was.
    origin_geometry = contours[0][1]

    await ctx.progress(0.8, "deriving the inferred discharge window")
    inferred_start, inferred_end = _inferred_window(
        result, detection.detected_at, duration_hours, origin_geometry
    )

    store = build_object_store(ctx.settings)
    density_tif = write_geotiff(
        grid.values.astype(np.float32),
        bounds=grid.bounds,
        band_descriptions=("origin_probability_density",),
        tags={"engine": result.engine, "seed": str(seed), "mode": "BACKWARD"},
    )
    density_stored = await store.put_bytes(
        f"drift/{ctx.case_id}/density-{uuid.uuid4()}.tif", density_tif, media_type="image/tiff"
    )

    manifest = RunManifest(
        stage="drift.hindcast",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider=result.engine,
        parameters={**result.parameters, "contour_levels": list(DEFAULT_CONTOUR_LEVELS)},
        seed=seed,
        data_provenance=result.data_provenance,
    )
    manifest.with_input("environmental_run", env_run.checksum_sha256 or str(env_run.id))
    manifest.with_input("spill_detection", str(detection.id))
    for note in result.notes:
        manifest.note(note)

    run = DriftRun(
        case_id=ctx.case_id,
        spill_id=detection.id,
        environmental_run_id=env_run.id,
        engine=DriftEngineName(result.engine).value,
        mode=DriftMode.BACKWARD.value,
        parameters=result.parameters,
        seed=seed,
        number_of_particles=particles,
        ensemble_members=members,
        duration_hours=duration_hours,
        time_step_seconds=time_step,
        origin_geometry=from_shape(origin_geometry, srid=4326),
        origin_confidence=_origin_confidence(grid, contours),
        density_grid_uri=density_stored.uri,
        contours=contours_to_geojson(contours),
        inferred_start=inferred_start,
        inferred_end=inferred_end,
        status="COMPLETED",
        data_provenance=str(result.data_provenance),
        run_manifest=manifest.to_dict(),
        completed_at=None,
    )
    ctx.session.add(run)
    await ctx.session.flush()

    ctx.session.add(
        EvidenceArtifact(
            case_id=ctx.case_id,
            artifact_type=ArtifactType.DENSITY_GRID.value,
            label=f"Origin probability density ({result.engine} engine)",
            storage_uri=density_stored.uri,
            media_type="image/tiff",
            size_bytes=density_stored.size_bytes,
            checksum_sha256=density_stored.checksum_sha256,
            related_table="drift_runs",
            related_id=run.id,
            artifact_metadata={"bounds": list(grid.bounds), "seed": seed},
            data_provenance=str(result.data_provenance),
        )
    )

    await ctx.progress(0.9, "storing particle tracks")
    await _persist_particles(ctx, run, result)

    from spilltrace.core.time import utcnow

    run.completed_at = utcnow()
    await ctx.session.flush()

    await ctx.progress(1.0, "origin probability region ready")
    ctx.log(
        "hindcast_complete",
        engine=result.engine,
        origin_area_km2=round(geodesic_area_km2(origin_geometry), 2),
        contours=[level for level, _ in contours],
    )
    return {
        "drift_run_id": str(run.id),
        "engine": result.engine,
        "seed": seed,
        "origin_area_km2": round(geodesic_area_km2(origin_geometry), 2),
        "contour_levels": [level for level, _ in contours],
        "inferred_start": inferred_start.isoformat() if inferred_start else None,
        "inferred_end": inferred_end.isoformat() if inferred_end else None,
        "manifest_fingerprint": manifest.fingerprint(),
    }


async def _select_detection(ctx: JobContext) -> SpillDetection:
    """Prefer a verified detection; fall back to uncertain, never to a rejected one."""
    rows = list(
        (
            await ctx.session.execute(
                select(SpillDetection, VerificationResult)
                .outerjoin(
                    VerificationResult,
                    (VerificationResult.spill_id == SpillDetection.id)
                    & VerificationResult.is_latest,
                )
                .where(SpillDetection.case_id == ctx.case_id)
                .order_by(SpillDetection.area_km2.desc())
            )
        ).all()
    )
    if not rows:
        raise NoDataError("No detection exists for this case, so there is nothing to back-track.")

    usable = [
        (d, v) for d, v in rows if v is None or v.status != VerificationStatus.FALSE_POSITIVE.value
    ]
    if not usable:
        raise NoDataError(
            "Every detection in this case was verified as a look-alike, so no reverse "
            "drift was run. Review the verification evidence before proceeding."
        )
    verified = [
        (d, v) for d, v in usable if v is not None and v.status == VerificationStatus.VERIFIED.value
    ]
    return (verified or usable)[0][0]


async def _load_environment(ctx: JobContext) -> tuple[EnvironmentalRun, Any]:
    run = (
        await ctx.session.execute(
            select(EnvironmentalRun)
            .where(EnvironmentalRun.case_id == ctx.case_id)
            .order_by(EnvironmentalRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or not run.storage_uri:
        raise NoDataError(
            "No environmental data has been retrieved for this case. Reverse drift "
            "cannot run without wind and current forcing."
        )
    store = build_object_store(ctx.settings)
    key = run.storage_uri.split("/", 3)[-1]
    return run, bundle_from_bytes(await store.get_bytes(key))


def _inferred_window(
    result: Any,
    detected_at: Any,
    duration_hours: float,
    origin_region: Any = None,
) -> tuple[Any, Any]:
    """The interval over which back-tracked particles occupy the origin region (A-02).

    The PRD uses an "inferred discharge time window" without defining it.  Taking
    percentiles of the *simulation duration* would be circular — it would return roughly
    the run length whatever the physics did.  Instead, every particle state that falls
    inside the origin region contributes its timestamp, and the window is the middle 50%
    of those times.  That is a statement about where the back-track actually converged,
    and it narrows when the forcing constrains the problem well.

    Falls back to the full back-track span when no region is available, which is honest:
    without a region there is nothing to be more precise about.
    """

    times = sorted({p.timestamp for p in result.particles})
    if len(times) < 2:
        return detected_at - timedelta(hours=duration_hours), detected_at

    occupancy: list[Any] = []
    if origin_region is not None and not origin_region.is_empty:
        from shapely.geometry import Point

        prepared = origin_region
        try:
            from shapely import prepared as shapely_prepared

            prepared = shapely_prepared.prep(origin_region)
        except Exception:
            prepared = origin_region
        for particle in result.particles:
            if prepared.contains(Point(particle.lon, particle.lat)):
                occupancy.append(particle.timestamp)

    if len(occupancy) >= 8:
        occupancy.sort()
        lower = occupancy[int(0.25 * (len(occupancy) - 1))]
        upper = occupancy[int(0.75 * (len(occupancy) - 1))]
    else:
        # Too few particles reached the region for a percentile to mean anything.
        lower, upper = times[0], times[-1]

    start, end = min(lower, upper), max(lower, upper)
    if start == end:
        start = end - timedelta(hours=1)
    return start, end


def _origin_confidence(grid: Any, contours: list[tuple[float, Any]]) -> float:
    """How concentrated the back-tracked distribution is.

    A tight 50% region relative to the 90% region means the run agrees with itself; a
    50% region almost as large as the 90% means the forcing barely constrained anything.
    Reported as its own quantity and never combined with detection or verification
    confidence (AD-28).
    """
    if len(contours) < 2:
        return 0.3
    areas = {level: geodesic_area_km2(geometry) for level, geometry in contours}
    tightest = min(areas)
    loosest = max(areas)
    if areas[loosest] <= 0:
        return 0.3
    ratio = areas[tightest] / areas[loosest]
    # ratio near 0 => highly concentrated; near 1 => diffuse and uninformative.
    return round(float(min(0.95, max(0.05, 1.0 - ratio))), 4)


async def _persist_particles(ctx: JobContext, run: DriftRun, result: Any) -> None:
    """Store a decimated subset for the map; the full output stays in object storage."""
    steps = sorted({p.step_index for p in result.particles})
    keep_steps = set(steps[:: max(1, len(steps) // 12)]) | {steps[-1]}
    candidates = [p for p in result.particles if p.step_index in keep_steps]

    if len(candidates) > MAX_PERSISTED_PARTICLES:
        stride = len(candidates) // MAX_PERSISTED_PARTICLES + 1
        candidates = candidates[::stride]

    for particle in candidates:
        ctx.session.add(
            DriftParticle(
                drift_run_id=run.id,
                particle_id=particle.particle_id,
                step_index=particle.step_index,
                member=particle.member,
                timestamp=particle.timestamp,
                position=from_shape(Point(particle.lon, particle.lat), srid=4326),
                status=particle.status,
            )
        )
    await ctx.session.flush()


__all__ = ["fetch_environment", "run_hindcast"]
