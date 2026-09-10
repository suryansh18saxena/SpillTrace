"""Map layers (UI-004, FR-017).

The frontend does not hard-code which layers exist: it asks for a manifest and builds
the map from it.  That way a new pipeline stage can add a layer without a frontend
release, and a case missing a stage simply reports fewer layers instead of rendering
empty controls.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select

from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import SessionDep
from spilltrace.core.disclaimers import (
    AIS_COVERAGE_DISCLAIMER,
    AIS_GAP_DISCLAIMER,
    DETECTION_DISCLAIMER,
    ORIGIN_REGION_DISCLAIMER,
)
from spilltrace.core.errors import NotFoundError
from spilltrace.core.geometry import geodesic_area_km2
from spilltrace.core.time import isoformat_utc
from spilltrace.db.models import (
    AISPosition,
    Case,
    CaseScene,
    DriftParticle,
    DriftRun,
    SatelliteScene,
    SpillDetection,
    Trajectory,
    Vessel,
)
from spilltrace.db.repositories.cases import CaseRepository

router = APIRouter(prefix="/api/v1/cases/{case_id}/layers", tags=["layers"])

#: Draw order, bottom to top.  Deliberate: the AOI is context, the origin region is the
#: analytical result, and vessels sit on top because they are what the analyst clicks.
LAYER_ORDER: tuple[str, ...] = (
    "aoi",
    "scene_footprint",
    "origin_region",
    "drift_particles",
    "oil_probability",
    "spill",
    "trajectories",
    "vessels",
)


def _feature(
    geometry: Any, properties: dict[str, Any], feature_id: str | None = None
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": mapping(to_shape(geometry)) if geometry is not None else None,
        "properties": properties,
    }


def _collection(features: list[dict[str, Any]], **properties: Any) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features, "properties": properties}


@router.get("", summary="Layer manifest for the investigation map")
async def layer_manifest(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    case = await CaseRepository(session).get_for_user(case_id, user)
    base = f"/api/v1/cases/{case_id}/layers"

    async def count(model: Any, column: Any) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(model).where(column == case_id)
        return int((await session.execute(stmt)).scalar_one())

    detections = await count(SpillDetection, SpillDetection.case_id)
    drift_runs = await count(DriftRun, DriftRun.case_id)
    trajectories = await count(Trajectory, Trajectory.case_id)
    scenes = await count(CaseScene, CaseScene.case_id)

    definitions: list[dict[str, Any]] = [
        {
            "id": "aoi",
            "title": "Area of interest",
            "type": "geojson",
            "geometry": "polygon",
            "available": True,
            "visible": True,
            "feature_count": 1,
        },
        {
            "id": "scene_footprint",
            "title": "Sentinel-1 scene footprint",
            "type": "geojson",
            "geometry": "polygon",
            "available": scenes > 0,
            "visible": False,
            "feature_count": scenes,
        },
        {
            "id": "origin_region",
            "title": "Origin probability region",
            "type": "geojson",
            "geometry": "polygon",
            "available": drift_runs > 0,
            "visible": True,
            "feature_count": drift_runs,
            "notice": ORIGIN_REGION_DISCLAIMER,
        },
        {
            "id": "drift_particles",
            "title": "Reverse-drift particles",
            "type": "geojson",
            "geometry": "point",
            "available": drift_runs > 0,
            "visible": False,
            "animated": True,
        },
        {
            "id": "oil_probability",
            "title": "Oil probability",
            "type": "raster",
            "available": detections > 0,
            "visible": False,
            "notice": DETECTION_DISCLAIMER,
        },
        {
            "id": "spill",
            "title": "Detected slick",
            "type": "geojson",
            "geometry": "polygon",
            "available": detections > 0,
            "visible": True,
            "feature_count": detections,
            "notice": DETECTION_DISCLAIMER,
        },
        {
            "id": "trajectories",
            "title": "Vessel trajectories",
            "type": "geojson",
            "geometry": "line",
            "available": trajectories > 0,
            "visible": True,
            "feature_count": trajectories,
            "notice": AIS_GAP_DISCLAIMER,
        },
        {
            "id": "vessels",
            "title": "Vessels",
            "type": "geojson",
            "geometry": "point",
            "available": trajectories > 0,
            "visible": True,
            "notice": AIS_COVERAGE_DISCLAIMER,
        },
    ]
    by_id = {d["id"]: d for d in definitions}
    ordered = [by_id[layer_id] for layer_id in LAYER_ORDER if layer_id in by_id]
    for layer in ordered:
        layer["url"] = (
            f"{base}/{layer['id']}"
            if layer["type"] == "geojson"
            else f"/api/v1/cases/{case_id}/probability/{{z}}/{{x}}/{{y}}.png"
        )
    return {
        "case_id": str(case_id),
        "data_provenance": case.data_provenance,
        "layers": ordered,
    }


@router.get("/{layer_id}", summary="One map layer as GeoJSON")
async def layer(
    case_id: uuid.UUID, layer_id: str, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    case = await CaseRepository(session).get_for_user(case_id, user)

    builders = {
        "aoi": _aoi_layer,
        "scene_footprint": _scene_layer,
        "spill": _spill_layer,
        "origin_region": _origin_layer,
        "drift_particles": _particles_layer,
        "trajectories": _trajectories_layer,
        "vessels": _vessels_layer,
    }
    builder = builders.get(layer_id)
    if builder is None:
        raise NotFoundError(f"Unknown layer '{layer_id}'.", available=sorted(builders))
    return await builder(session, case)


async def _aoi_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    aoi = to_shape(case.aoi)
    return _collection(
        [
            _feature(
                case.aoi,
                {
                    "case_ref": case.case_ref,
                    "title": case.title,
                    "area_km2": round(geodesic_area_km2(aoi), 1),
                    "start_time": isoformat_utc(case.start_time),
                    "end_time": isoformat_utc(case.end_time),
                },
                str(case.id),
            )
        ],
        layer="aoi",
    )


async def _scene_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(SatelliteScene, CaseScene)
            .join(CaseScene, CaseScene.scene_id == SatelliteScene.id)
            .where(CaseScene.case_id == case.id)
        )
    ).all()
    return _collection(
        [
            _feature(
                scene.footprint,
                {
                    "product_id": scene.product_id,
                    "provider": scene.provider,
                    "acquisition_time": isoformat_utc(scene.acquisition_time),
                    "polarizations": scene.polarizations,
                    "orbit_direction": scene.orbit_direction,
                    "is_selected": link.is_selected,
                    "data_provenance": scene.data_provenance,
                },
                str(scene.id),
            )
            for scene, link in rows
        ],
        layer="scene_footprint",
    )


async def _spill_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    from spilltrace.db.models import VerificationResult

    rows = (
        await session.execute(
            select(SpillDetection, VerificationResult)
            .outerjoin(
                VerificationResult,
                (VerificationResult.spill_id == SpillDetection.id) & VerificationResult.is_latest,
            )
            .where(SpillDetection.case_id == case.id)
        )
    ).all()
    return _collection(
        [
            _feature(
                detection.geometry,
                {
                    "area_km2": round(detection.area_km2, 2),
                    "detection_confidence": detection.detection_confidence,
                    "detected_at": isoformat_utc(detection.detected_at),
                    "verification_status": verification.status if verification else None,
                    "verification_confidence": (
                        verification.verification_confidence if verification else None
                    ),
                    "data_provenance": detection.data_provenance,
                },
                str(detection.id),
            )
            for detection, verification in rows
        ],
        layer="spill",
        notice=DETECTION_DISCLAIMER,
    )


async def _origin_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    run = (
        await session.execute(
            select(DriftRun)
            .where(DriftRun.case_id == case.id, DriftRun.status == "COMPLETED")
            .order_by(DriftRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or not run.contours:
        return _collection([], layer="origin_region", notice=ORIGIN_REGION_DISCLAIMER)

    from shapely.geometry import shape

    features = []
    for feature in run.contours.get("features", []):
        mass = feature["properties"]["probability_mass"]
        features.append(
            {
                "type": "Feature",
                "id": f"{run.id}-{round(mass * 100)}",
                "geometry": feature["geometry"],
                "properties": {
                    "probability_mass": mass,
                    "label": feature["properties"].get("label"),
                    "area_km2": round(geodesic_area_km2(shape(feature["geometry"])), 1),
                    "engine": run.engine,
                    "origin_confidence": run.origin_confidence,
                    "inferred_start": (
                        isoformat_utc(run.inferred_start) if run.inferred_start else None
                    ),
                    "inferred_end": (isoformat_utc(run.inferred_end) if run.inferred_end else None),
                    "data_provenance": run.data_provenance,
                },
            }
        )
    return _collection(
        features,
        layer="origin_region",
        drift_run_id=str(run.id),
        notice=ORIGIN_REGION_DISCLAIMER,
    )


async def _particles_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    run = (
        await session.execute(
            select(DriftRun)
            .where(DriftRun.case_id == case.id, DriftRun.status == "COMPLETED")
            .order_by(DriftRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return _collection([], layer="drift_particles")

    particles = (
        (
            await session.execute(
                select(DriftParticle)
                .where(DriftParticle.drift_run_id == run.id)
                .order_by(DriftParticle.step_index, DriftParticle.particle_id)
            )
        )
        .scalars()
        .all()
    )
    steps = sorted({p.step_index for p in particles})
    return _collection(
        [
            _feature(
                particle.position,
                {
                    "particle_id": particle.particle_id,
                    "step_index": particle.step_index,
                    "member": particle.member,
                    "timestamp": isoformat_utc(particle.timestamp),
                },
            )
            for particle in particles
        ],
        layer="drift_particles",
        drift_run_id=str(run.id),
        steps=steps,
        engine=run.engine,
    )


async def _trajectories_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Trajectory, Vessel)
            .join(Vessel, Vessel.id == Trajectory.vessel_id)
            .where(Trajectory.case_id == case.id)
            .order_by(Trajectory.time_start)
        )
    ).all()
    return _collection(
        [
            _feature(
                trajectory.geometry,
                {
                    "vessel_id": str(vessel.id),
                    "mmsi": vessel.mmsi,
                    "name": vessel.name,
                    "ship_type": vessel.ship_type_name,
                    "time_start": isoformat_utc(trajectory.time_start),
                    "time_end": isoformat_utc(trajectory.time_end),
                    "position_count": trajectory.position_count,
                    "distance_km": round(trajectory.distance_km, 2),
                    "gap_count": trajectory.gap_count,
                    "max_gap_minutes": round(trajectory.max_gap_minutes, 1),
                    "coverage_ratio": round(trajectory.coverage_ratio, 3),
                    "quality_score": round(trajectory.quality_score, 3),
                    "data_provenance": trajectory.data_provenance,
                },
                str(trajectory.id),
            )
            for trajectory, vessel in rows
        ],
        layer="trajectories",
        notice=AIS_GAP_DISCLAIMER,
    )


async def _vessels_layer(session: SessionDep, case: Case) -> dict[str, Any]:
    """Last known position of every vessel with a trajectory in this case."""
    from sqlalchemy import func

    trajectory_vessels = select(Trajectory.vessel_id).where(Trajectory.case_id == case.id)
    latest = (
        select(AISPosition.vessel_id, func.max(AISPosition.timestamp).label("latest"))
        .where(
            AISPosition.is_valid,
            AISPosition.vessel_id.in_(trajectory_vessels),
            AISPosition.timestamp <= case.end_time,
        )
        .group_by(AISPosition.vessel_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(AISPosition, Vessel)
            .join(
                latest,
                (AISPosition.vessel_id == latest.c.vessel_id)
                & (AISPosition.timestamp == latest.c.latest),
            )
            .join(Vessel, Vessel.id == AISPosition.vessel_id)
        )
    ).all()
    return _collection(
        [
            _feature(
                position.position,
                {
                    "vessel_id": str(vessel.id),
                    "mmsi": vessel.mmsi,
                    "imo": vessel.imo,
                    "name": vessel.name,
                    "ship_type": vessel.ship_type_name,
                    "flag_country": vessel.flag_country,
                    "timestamp": isoformat_utc(position.timestamp),
                    "sog_knots": position.sog_knots,
                    "cog_deg": position.cog_deg,
                    "heading_deg": position.heading_deg,
                    "data_provenance": vessel.data_provenance,
                },
                str(vessel.id),
            )
            for position, vessel in rows
        ],
        layer="vessels",
        notice=AIS_COVERAGE_DISCLAIMER,
    )


__all__ = ["LAYER_ORDER", "router"]
