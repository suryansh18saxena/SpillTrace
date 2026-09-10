"""``demo.seed`` — materialise a scenario's synthetic *observations*.

This handler writes only what a real deployment would have *observed*: a satellite
scene, an oil-like slick with its probability raster, wind and current fields, and raw
AIS messages complete with the defects a real feed contains.

It deliberately does **not** write verification results, drift runs, trajectories,
candidates, scores or a report.  Those are produced by the same handlers a real case
uses, running their real algorithms on this synthetic input — which is the only way a
demonstration says anything true about the system (FR-020).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from spilltrace.adapters.environmental.serialize import bundle_to_bytes
from spilltrace.adapters.environmental.synthetic import SyntheticEnvironmentProvider
from spilltrace.adapters.storage import build_object_store
from spilltrace.core.enums import (
    ArtifactType,
    DataProvenance,
    DownloadStatus,
    JobType,
)
from spilltrace.core.geometry import (
    bbox_polygon,
    geodesic_area_km2,
    geodesic_perimeter_km,
)
from spilltrace.core.provenance import RunManifest, sha256_of_bytes
from spilltrace.core.raster import write_geotiff
from spilltrace.core.time import utcnow
from spilltrace.db.models import (
    AISPosition,
    Case,
    CaseScene,
    EnvironmentalRun,
    EvidenceArtifact,
    ModelVersion,
    SatelliteScene,
    SpillDetection,
    Vessel,
)
from spilltrace.demo.ais import generate_scenario_messages
from spilltrace.demo.environment import summarise
from spilltrace.demo.scenarios import Scenario, get_scenario
from spilltrace.demo.slick import probability_grid, slick_metrics, synthetic_slick
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register


@register(JobType.DEMO_SEED)
async def seed_demo_case(ctx: JobContext) -> dict[str, Any]:
    scenario_key = str(ctx.payload.get("scenario") or "kutch-01")
    seed = int(ctx.payload.get("seed") or 42)
    scenario = get_scenario(scenario_key)

    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        from spilltrace.core.errors import NotFoundError

        raise NotFoundError("The case for this job no longer exists.")

    case.scenario = scenario.key
    case.seed = seed
    case.data_provenance = DataProvenance.SYNTHETIC.value

    store = build_object_store(ctx.settings)
    manifest = RunManifest(
        stage="demo.seed",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider="demo",
        parameters={"scenario": scenario.key},
        seed=seed,
        data_provenance=DataProvenance.SYNTHETIC,
    ).note(
        "Synthetic observations generated deterministically from the scenario and seed. "
        "No real satellite, environmental or AIS observation was used."
    )

    await ctx.progress(0.05, "creating synthetic Sentinel-1 scene")
    scene = await _create_scene(ctx, scenario, seed)

    await ctx.progress(0.20, "generating oil-like slick and probability raster")
    detection, prob_bytes, prob_bounds = await _create_detection(
        ctx, case, scene, scenario, seed, manifest
    )
    prob_key = f"probability/{case.id}/{detection.id}.tif"
    stored = await store.put_bytes(prob_key, prob_bytes, media_type="image/tiff")
    detection.probability_raster_uri = stored.uri
    ctx.session.add(
        EvidenceArtifact(
            case_id=case.id,
            artifact_type=ArtifactType.PROBABILITY_RASTER.value,
            label="Oil probability raster (SYNTHETIC)",
            storage_uri=stored.uri,
            media_type="image/tiff",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            related_table="spill_detections",
            related_id=detection.id,
            artifact_metadata={"bounds": list(prob_bounds), "band": "oil_probability"},
            data_provenance=DataProvenance.SYNTHETIC.value,
        )
    )

    await ctx.progress(0.45, "generating wind and current fields")
    env_run = await _create_environment(ctx, case, scenario, seed, store)

    await ctx.progress(0.70, "generating raw AIS messages")
    counts = await _create_ais(ctx, scenario, seed)

    await ctx.progress(1.0, "synthetic observations ready")
    ctx.log(
        "demo_seeded",
        scenario=scenario.key,
        vessels=counts["vessels"],
        positions=counts["positions"],
    )
    return {
        "scenario": scenario.key,
        "seed": seed,
        "scene_id": str(scene.id),
        "spill_id": str(detection.id),
        "environmental_run_id": str(env_run.id),
        "vessels": counts["vessels"],
        "ais_positions": counts["positions"],
        "data_provenance": DataProvenance.SYNTHETIC.value,
    }


async def _create_scene(ctx: JobContext, scenario: Scenario, seed: int) -> SatelliteScene:
    footprint = bbox_polygon(*scenario.aoi_bbox)
    product_id = f"S1A_IW_GRDH_1SDV_{scenario.acquisition_time:%Y%m%dT%H%M%S}_SYNTHETIC_{seed:04d}"
    existing = (
        await ctx.session.execute(
            select(SatelliteScene).where(SatelliteScene.product_id == product_id)
        )
    ).scalar_one_or_none()
    scene = existing or SatelliteScene(
        product_id=product_id,
        provider="SYNTHETIC",
        mission="SENTINEL-1",
        platform="S1A",
        product_type="IW_GRDH_1S",
        sensor_mode="IW",
        acquisition_time=scenario.acquisition_time,
        footprint=from_shape(footprint, srid=4326),
        bbox=from_shape(footprint, srid=4326),
        polarizations=["VV", "VH"],
        orbit_direction="DESCENDING",
        relative_orbit=107,
        resolution_m=10.0,
        provider_ref={"synthetic": True, "scenario": scenario.key},
        download_status=DownloadStatus.DOWNLOADED.value,
        data_provenance=DataProvenance.SYNTHETIC.value,
    )
    if existing is None:
        ctx.session.add(scene)
        await ctx.session.flush()

    link = await ctx.session.get(CaseScene, (ctx.case_id, scene.id))
    if link is None:
        ctx.session.add(
            CaseScene(
                case_id=ctx.case_id,
                scene_id=scene.id,
                is_selected=True,
                coverage_fraction=1.0,
                rank=1,
            )
        )
        await ctx.session.flush()
    return scene


async def _create_detection(
    ctx: JobContext,
    case: Case,
    scene: SatelliteScene,
    scenario: Scenario,
    seed: int,
    manifest: RunManifest,
) -> tuple[SpillDetection, bytes, tuple[float, float, float, float]]:
    geometry = synthetic_slick(
        centre=scenario.slick_centre,
        length_km=scenario.slick_length_km,
        width_km=scenario.slick_width_km,
        bearing_deg=scenario.slick_bearing_deg,
        seed=seed,
    )
    metrics = slick_metrics(geometry)
    grid, bounds = probability_grid(geometry, seed=seed)

    model_version = await _ensure_demo_model(ctx)
    centroid: Point = geometry.centroid

    detection = SpillDetection(
        case_id=case.id,
        scene_id=scene.id,
        model_version_id=model_version.id,
        geometry=from_shape(geometry, srid=4326),
        centroid=from_shape(centroid, srid=4326),
        area_km2=geodesic_area_km2(geometry),
        perimeter_km=geodesic_perimeter_km(geometry),
        detection_confidence=round(float(grid[grid > 0].mean()), 4),
        mean_probability=round(float(grid[grid > 0].mean()), 4),
        max_probability=round(float(grid.max()), 4),
        threshold=0.5,
        pixel_count=int((grid >= 0.5).sum()),
        detected_at=scenario.acquisition_time,
        run_manifest={**manifest.to_dict(), "shape_metrics": metrics},
        data_provenance=DataProvenance.SYNTHETIC.value,
    )
    ctx.session.add(detection)
    await ctx.session.flush()

    raster = write_geotiff(
        grid,
        bounds=bounds,
        nodata=0.0,
        band_descriptions=("oil_probability",),
        tags={
            "provenance": "SYNTHETIC",
            "scenario": scenario.key,
            "seed": str(seed),
            "note": "Synthetic demonstration raster; not a real Sentinel-1 observation.",
        },
    )
    return detection, raster, bounds


async def _ensure_demo_model(ctx: JobContext) -> ModelVersion:
    """The model row for synthetic detections.

    Its ``metrics`` are deliberately empty: no model was evaluated, so publishing a
    number here would be fabricating a benchmark (AD-10).
    """
    existing = (
        await ctx.session.execute(
            select(ModelVersion).where(
                ModelVersion.name == "synthetic-generator", ModelVersion.version == "1.0.0"
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    model = ModelVersion(
        name="synthetic-generator",
        version="1.0.0",
        framework="numpy",
        task="oil-slick-generation",
        metrics={},
        params={"note": "Deterministic generator, not a trained model."},
        training_manifest={},
        input_channels=2,
        is_active=False,
        notes=(
            "Produces synthetic demonstration slicks. No training was performed and no "
            "performance metrics exist for it."
        ),
    )
    ctx.session.add(model)
    await ctx.session.flush()
    return model


async def _create_environment(
    ctx: JobContext, case: Case, scenario: Scenario, seed: int, store: Any
) -> EnvironmentalRun:
    provider = SyntheticEnvironmentProvider(
        wind_speed_ms=scenario.wind_speed_ms,
        wind_direction_deg=scenario.wind_direction_deg,
        current_speed_ms=scenario.current_speed_ms,
        current_direction_deg=scenario.current_direction_deg,
        seed=seed,
    )
    bundle = await provider.fetch(
        bbox=scenario.aoi_bbox, start=scenario.case_start, end=scenario.case_end
    )
    payload = bundle_to_bytes(bundle)
    key = f"environment/{case.id}/{uuid.uuid4()}.npz"
    stored = await store.put_bytes(key, payload, media_type="application/octet-stream")

    run = EnvironmentalRun(
        case_id=case.id,
        source="SYNTHETIC",
        provider="synthetic",
        dataset_id=None,
        variables=["eastward_wind", "northward_wind", "eastward_current", "northward_current"],
        time_start=scenario.case_start,
        time_end=scenario.case_end,
        extent=from_shape(bbox_polygon(*scenario.aoi_bbox), srid=4326),
        grid_resolution_deg=0.05,
        storage_uri=stored.uri,
        checksum_sha256=stored.checksum_sha256,
        size_bytes=stored.size_bytes,
        status="COMPLETED",
        summary=summarise(bundle),
        data_provenance=DataProvenance.SYNTHETIC.value,
        run_manifest=RunManifest(
            stage="env.fetch",
            software_version=ctx.settings.version,
            provider="synthetic",
            parameters={
                "wind_speed_ms": scenario.wind_speed_ms,
                "wind_direction_deg": scenario.wind_direction_deg,
                "current_speed_ms": scenario.current_speed_ms,
                "current_direction_deg": scenario.current_direction_deg,
            },
            seed=seed,
            data_provenance=DataProvenance.SYNTHETIC,
        ).to_dict(),
    )
    ctx.session.add(run)
    await ctx.session.flush()
    ctx.session.add(
        EvidenceArtifact(
            case_id=case.id,
            artifact_type=ArtifactType.ENV_NETCDF.value,
            label="Wind and current fields (SYNTHETIC)",
            storage_uri=stored.uri,
            media_type="application/octet-stream",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            related_table="environmental_runs",
            related_id=run.id,
            artifact_metadata={"format": "npz", "sha256": sha256_of_bytes(payload)},
            data_provenance=DataProvenance.SYNTHETIC.value,
        )
    )
    return run


async def _create_ais(ctx: JobContext, scenario: Scenario, seed: int) -> dict[str, int]:
    """Insert vessels and *raw* AIS positions.

    Positions go in unvalidated, with ``is_valid`` left true, because the ``ais.clean``
    stage is what decides validity.  Pre-cleaning them here would hide the one thing the
    cleaning stage exists to demonstrate.
    """
    # Each vessel's closest approach sits on the drift corridor — where the oil was at
    # that moment — so the correlation and scoring stages solve a real geometry rather
    # than one arranged around the observed slick.
    messages = generate_scenario_messages(scenario, seed=seed)

    vessels: dict[int, Vessel] = {}
    for profile in scenario.vessels:
        existing = (
            await ctx.session.execute(select(Vessel).where(Vessel.mmsi == profile.mmsi))
        ).scalar_one_or_none()
        vessel = existing or Vessel(
            mmsi=profile.mmsi,
            imo=profile.imo,
            name=f"{profile.name} (SYNTHETIC)",
            callsign=f"S{profile.mmsi % 100000:05d}",
            ship_type=profile.ship_type,
            ship_type_name=profile.ship_type_name,
            flag_country=profile.flag_country,
            flag_mid=int(str(profile.mmsi)[:3]),
            length_m=profile.length_m,
            width_m=profile.width_m,
            draught_m=round(profile.length_m / 18.0, 1),
            source="SYNTHETIC",
            data_provenance=DataProvenance.SYNTHETIC.value,
        )
        if existing is None:
            ctx.session.add(vessel)
        vessels[profile.mmsi] = vessel
    await ctx.session.flush()

    # AIS positions are a global store keyed by (mmsi, timestamp, source), so a second
    # demo case built from the same scenario and seed produces rows that already exist.
    # Reusing them is the correct semantics — the observation happened once — so this is
    # an upsert, not an insert.  It is also far faster than 3,000 ORM objects.
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, Any]] = set()
    now = utcnow()
    for message in messages:
        if message.message_type != "PositionReport":
            continue
        vessel = vessels[message.mmsi]

        # Exact duplicates are deliberate demo content (a multi-receiver relay), but the
        # database key would collapse them, so they are nudged by a microsecond — which
        # is how a real relayed duplicate actually arrives.
        key = (message.mmsi, message.timestamp)
        timestamp = message.timestamp
        if key in seen:
            timestamp = timestamp + timedelta(microseconds=len(seen) % 900 + 1)
        seen.add(key)

        rows.append(
            {
                "vessel_id": vessel.id,
                "mmsi": message.mmsi,
                "timestamp": timestamp,
                "position": from_shape(Point(message.longitude, message.latitude), srid=4326),
                "sog_knots": None if (message.sog_knots or 0) >= 102.2 else message.sog_knots,
                "cog_deg": None if (message.cog_deg or 0) >= 360 else message.cog_deg,
                "heading_deg": None if (message.heading_deg or 0) >= 511 else message.heading_deg,
                "nav_status": message.nav_status,
                "message_type": message.message_type,
                "source": "SYNTHETIC",
                "is_valid": True,
                "quality_flags": [],
                "raw": message.raw,
                "ingested_at": now,
            }
        )

    inserted = 0
    for start in range(0, len(rows), 500):
        chunk = rows[start : start + 500]
        statement = (
            pg_insert(AISPosition)
            .values(chunk)
            .on_conflict_do_nothing(constraint="uq_ais_positions_dedup")
        )
        result = await ctx.session.execute(statement)
        inserted += int(getattr(result, "rowcount", 0) or 0)
    await ctx.session.flush()

    # Static data drives the identity component of AIS reliability.
    for message in messages:
        if message.message_type != "ShipStaticData":
            continue
        vessel = vessels[message.mmsi]
        vessel.destination = message.destination
        vessel.static_completeness = round(
            sum(
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
            / 5.0,
            3,
        )

    for message in messages:
        vessel = vessels[message.mmsi]
        if vessel.first_seen is None or message.timestamp < vessel.first_seen:
            vessel.first_seen = message.timestamp
        if vessel.last_seen is None or message.timestamp > vessel.last_seen:
            vessel.last_seen = message.timestamp

    await ctx.session.flush()
    return {"vessels": len(vessels), "positions": inserted}


__all__ = ["seed_demo_case"]
