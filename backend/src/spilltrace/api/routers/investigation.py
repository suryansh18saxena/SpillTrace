"""Investigation detail endpoints: detections, drift, vessels, attributions, report.

Every attribution-bearing response carries the mandated disclaimer as a *field*, not as
a note in the documentation, so a client cannot render a score without it (AC-13).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import func, select

from spilltrace.adapters.storage import build_object_store
from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import PaginationDep, SessionDep, SettingsDep
from spilltrace.core.disclaimers import (
    AIS_COVERAGE_DISCLAIMER,
    AIS_GAP_DISCLAIMER,
    ATTRIBUTION_DISCLAIMER,
    DETECTION_DISCLAIMER,
    ORIGIN_REGION_DISCLAIMER,
    PROXIMITY_DISCLAIMER,
    SCORE_DISCLAIMER,
)
from spilltrace.core.errors import NotFoundError
from spilltrace.core.geometry import geodesic_area_km2
from spilltrace.core.scoring import shortfall_note
from spilltrace.core.time import isoformat_utc
from spilltrace.db.models import (
    AISPosition,
    Attribution,
    DriftParticle,
    DriftRun,
    EnvironmentalRun,
    EvidenceArtifact,
    SpillDetection,
    Trajectory,
    VerificationResult,
    Vessel,
)
from spilltrace.db.repositories.cases import CaseRepository

router = APIRouter(prefix="/api/v1", tags=["investigation"])


def _geojson(geometry: Any) -> dict[str, Any] | None:
    return mapping(to_shape(geometry)) if geometry is not None else None


# ------------------------------------------------------------------ detections
@router.get("/cases/{case_id}/detections", summary="Slick detections for a case")
async def list_detections(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        await session.execute(
            select(SpillDetection, VerificationResult)
            .outerjoin(
                VerificationResult,
                (VerificationResult.spill_id == SpillDetection.id) & VerificationResult.is_latest,
            )
            .where(SpillDetection.case_id == case_id)
            .order_by(SpillDetection.area_km2.desc())
        )
    ).all()
    return {
        "items": [_detection_payload(d, v) for d, v in rows],
        "total": len(rows),
        "notice": DETECTION_DISCLAIMER,
    }


@router.get("/detections/{spill_id}", summary="Detection detail")
async def get_detection(
    spill_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    detection = await session.get(SpillDetection, spill_id)
    if detection is None:
        raise NotFoundError("Detection not found.", spill_id=str(spill_id))
    await CaseRepository(session).get_for_user(detection.case_id, user)
    verification = (
        await session.execute(
            select(VerificationResult).where(
                VerificationResult.spill_id == spill_id, VerificationResult.is_latest
            )
        )
    ).scalar_one_or_none()
    payload = _detection_payload(detection, verification)
    payload["geometry"] = _geojson(detection.geometry)
    payload["run_manifest"] = detection.run_manifest
    return payload


@router.get("/detections/{spill_id}/verification", summary="Look-alike verification result")
async def get_verification(
    spill_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    detection = await session.get(SpillDetection, spill_id)
    if detection is None:
        raise NotFoundError("Detection not found.", spill_id=str(spill_id))
    await CaseRepository(session).get_for_user(detection.case_id, user)
    verification = (
        await session.execute(
            select(VerificationResult).where(
                VerificationResult.spill_id == spill_id, VerificationResult.is_latest
            )
        )
    ).scalar_one_or_none()
    if verification is None:
        raise NotFoundError("This detection has not been verified.", spill_id=str(spill_id))
    return {
        "spill_id": str(spill_id),
        "status": verification.status,
        "verification_confidence": verification.verification_confidence,
        "explanation": verification.explanation,
        "rules": verification.rules,
        "features": verification.features,
        "wind": {
            "speed_ms": verification.wind_speed_ms,
            "direction_deg": verification.wind_direction_deg,
            "source": verification.wind_source,
        },
        "classifier": {
            "name": verification.classifier_name,
            "score": verification.classifier_score,
        },
        "created_at": isoformat_utc(verification.created_at),
        "notice": DETECTION_DISCLAIMER,
    }


def _detection_payload(
    detection: SpillDetection, verification: VerificationResult | None
) -> dict[str, Any]:
    return {
        "id": str(detection.id),
        "case_id": str(detection.case_id),
        "scene_id": str(detection.scene_id) if detection.scene_id else None,
        "detected_at": isoformat_utc(detection.detected_at),
        "area_km2": round(detection.area_km2, 3),
        "perimeter_km": round(detection.perimeter_km, 3) if detection.perimeter_km else None,
        # Model confidence only; never combined with verification or origin confidence.
        "detection_confidence": detection.detection_confidence,
        "mean_probability": detection.mean_probability,
        "max_probability": detection.max_probability,
        "threshold": detection.threshold,
        "centroid": _geojson(detection.centroid),
        "probability_raster_uri": detection.probability_raster_uri,
        "data_provenance": detection.data_provenance,
        "verification": (
            {
                "status": verification.status,
                "confidence": verification.verification_confidence,
                "explanation": verification.explanation,
            }
            if verification
            else None
        ),
    }


# ------------------------------------------------------------------ environment & drift
@router.get("/cases/{case_id}/environment", summary="Environmental data retrieved for a case")
async def list_environment(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        (
            await session.execute(
                select(EnvironmentalRun)
                .where(EnvironmentalRun.case_id == case_id)
                .order_by(EnvironmentalRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(run.id),
                "source": run.source,
                "provider": run.provider,
                "dataset_id": run.dataset_id,
                "variables": run.variables,
                "time_start": isoformat_utc(run.time_start),
                "time_end": isoformat_utc(run.time_end),
                "grid_resolution_deg": run.grid_resolution_deg,
                "summary": run.summary,
                "storage_uri": run.storage_uri,
                "checksum_sha256": run.checksum_sha256,
                "status": run.status,
                "data_provenance": run.data_provenance,
            }
            for run in rows
        ],
        "total": len(rows),
    }


@router.get("/cases/{case_id}/drift-runs", summary="Drift runs for a case")
async def list_drift_runs(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        (
            await session.execute(
                select(DriftRun)
                .where(DriftRun.case_id == case_id)
                .order_by(DriftRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_drift_payload(run) for run in rows],
        "total": len(rows),
        "notice": ORIGIN_REGION_DISCLAIMER,
    }


@router.get("/drift-runs/{run_id}", summary="Drift run detail")
async def get_drift_run(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    run = await session.get(DriftRun, run_id)
    if run is None:
        raise NotFoundError("Drift run not found.", run_id=str(run_id))
    await CaseRepository(session).get_for_user(run.case_id, user)
    payload = _drift_payload(run)
    payload["contours"] = run.contours
    payload["run_manifest"] = run.run_manifest
    payload["origin_geometry"] = _geojson(run.origin_geometry)
    return payload


@router.get("/drift-runs/{run_id}/particles", summary="Particle positions for animation")
async def get_particles(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    step: int | None = None,
) -> dict[str, Any]:
    run = await session.get(DriftRun, run_id)
    if run is None:
        raise NotFoundError("Drift run not found.", run_id=str(run_id))
    await CaseRepository(session).get_for_user(run.case_id, user)

    stmt = select(DriftParticle).where(DriftParticle.drift_run_id == run_id)
    if step is not None:
        stmt = stmt.where(DriftParticle.step_index == step)
    particles = (
        (await session.execute(stmt.order_by(DriftParticle.step_index, DriftParticle.particle_id)))
        .scalars()
        .all()
    )
    return {
        "drift_run_id": str(run_id),
        "engine": run.engine,
        "steps": sorted({p.step_index for p in particles}),
        "features": [
            {
                "type": "Feature",
                "geometry": _geojson(p.position),
                "properties": {
                    "particle_id": p.particle_id,
                    "step_index": p.step_index,
                    "member": p.member,
                    "timestamp": isoformat_utc(p.timestamp),
                },
            }
            for p in particles
        ],
    }


def _drift_payload(run: DriftRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "case_id": str(run.case_id),
        "spill_id": str(run.spill_id),
        "engine": run.engine,
        "mode": run.mode,
        "seed": run.seed,
        "number_of_particles": run.number_of_particles,
        "ensemble_members": run.ensemble_members,
        "duration_hours": run.duration_hours,
        "time_step_seconds": run.time_step_seconds,
        "parameters": run.parameters,
        "origin_confidence": run.origin_confidence,
        "origin_area_km2": (
            round(geodesic_area_km2(to_shape(run.origin_geometry)), 1)
            if run.origin_geometry is not None
            else None
        ),
        "inferred_start": isoformat_utc(run.inferred_start) if run.inferred_start else None,
        "inferred_end": isoformat_utc(run.inferred_end) if run.inferred_end else None,
        "density_grid_uri": run.density_grid_uri,
        "status": run.status,
        "data_provenance": run.data_provenance,
        "created_at": isoformat_utc(run.created_at),
    }


# ------------------------------------------------------------------ vessels
@router.get("/cases/{case_id}/vessels", summary="Vessels observed in a case")
async def list_case_vessels(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        await session.execute(
            select(Vessel, Trajectory)
            .join(Trajectory, Trajectory.vessel_id == Vessel.id)
            .where(Trajectory.case_id == case_id)
            .order_by(Vessel.mmsi, Trajectory.time_start)
        )
    ).all()

    by_vessel: dict[uuid.UUID, dict[str, Any]] = {}
    for vessel, trajectory in rows:
        entry = by_vessel.setdefault(vessel.id, {**_vessel_payload(vessel), "segments": []})
        entry["segments"].append(
            {
                "trajectory_id": str(trajectory.id),
                "time_start": isoformat_utc(trajectory.time_start),
                "time_end": isoformat_utc(trajectory.time_end),
                "position_count": trajectory.position_count,
                "distance_km": round(trajectory.distance_km, 2),
                "gap_count": trajectory.gap_count,
                "max_gap_minutes": round(trajectory.max_gap_minutes, 1),
                "coverage_ratio": round(trajectory.coverage_ratio, 3),
                "quality_score": round(trajectory.quality_score, 3),
                "quality_flags": trajectory.quality_flags,
            }
        )
    return {
        "items": list(by_vessel.values()),
        "total": len(by_vessel),
        "notice": AIS_COVERAGE_DISCLAIMER,
    }


@router.get("/vessels/{vessel_id}", summary="Vessel detail")
async def get_vessel(
    vessel_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    vessel = await session.get(Vessel, vessel_id)
    if vessel is None:
        raise NotFoundError("Vessel not found.", vessel_id=str(vessel_id))
    # A vessel is only visible through a case the caller may read.
    trajectory = (
        await session.execute(select(Trajectory).where(Trajectory.vessel_id == vessel_id).limit(1))
    ).scalar_one_or_none()
    if trajectory is not None and trajectory.case_id is not None:
        await CaseRepository(session).get_for_user(trajectory.case_id, user)

    counts = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(AISPosition.is_valid.is_(False)),
                func.min(AISPosition.timestamp),
                func.max(AISPosition.timestamp),
            ).where(AISPosition.vessel_id == vessel_id)
        )
    ).one()
    return {
        **_vessel_payload(vessel),
        "ais": {
            "position_count": int(counts[0]),
            "rejected_count": int(counts[1]),
            "first_position": isoformat_utc(counts[2]) if counts[2] else None,
            "last_position": isoformat_utc(counts[3]) if counts[3] else None,
        },
        "notice": AIS_GAP_DISCLAIMER,
    }


@router.get("/vessels/{vessel_id}/positions", summary="AIS positions for a vessel")
async def get_vessel_positions(
    vessel_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
    include_invalid: bool = False,
) -> dict[str, Any]:
    vessel = await session.get(Vessel, vessel_id)
    if vessel is None:
        raise NotFoundError("Vessel not found.", vessel_id=str(vessel_id))
    trajectory = (
        await session.execute(select(Trajectory).where(Trajectory.vessel_id == vessel_id).limit(1))
    ).scalar_one_or_none()
    if trajectory is not None and trajectory.case_id is not None:
        await CaseRepository(session).get_for_user(trajectory.case_id, user)

    stmt = select(AISPosition).where(AISPosition.vessel_id == vessel_id)
    if not include_invalid:
        stmt = stmt.where(AISPosition.is_valid)
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                stmt.order_by(AISPosition.timestamp)
                .limit(pagination.limit)
                .offset(pagination.offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "timestamp": isoformat_utc(p.timestamp),
                "position": _geojson(p.position),
                "sog_knots": p.sog_knots,
                "cog_deg": p.cog_deg,
                "heading_deg": p.heading_deg,
                "nav_status": p.nav_status,
                "message_type": p.message_type,
                "source": p.source,
                "is_valid": p.is_valid,
                "quality_flags": p.quality_flags,
                "rejection_reason": p.rejection_reason,
            }
            for p in rows
        ],
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
        "notice": AIS_GAP_DISCLAIMER,
    }


def _vessel_payload(vessel: Vessel) -> dict[str, Any]:
    return {
        "id": str(vessel.id),
        "mmsi": vessel.mmsi,
        "imo": vessel.imo,
        "name": vessel.name,
        "callsign": vessel.callsign,
        "ship_type": vessel.ship_type,
        "ship_type_name": vessel.ship_type_name,
        "flag_country": vessel.flag_country,
        "length_m": vessel.length_m,
        "width_m": vessel.width_m,
        "draught_m": vessel.draught_m,
        "destination": vessel.destination,
        "static_completeness": vessel.static_completeness,
        "first_seen": isoformat_utc(vessel.first_seen) if vessel.first_seen else None,
        "last_seen": isoformat_utc(vessel.last_seen) if vessel.last_seen else None,
        "data_provenance": vessel.data_provenance,
        "source": vessel.source,
    }


# ------------------------------------------------------------------ attributions
@router.get("/cases/{case_id}/attributions", summary="Ranked candidate vessels")
async def list_attributions(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        await session.execute(
            select(Attribution, Vessel)
            .join(Vessel, Vessel.id == Attribution.vessel_id)
            .where(Attribution.case_id == case_id)
            .order_by(Attribution.rank)
        )
    ).all()
    return {
        "items": [_attribution_payload(a, v) for a, v in rows],
        "total": len(rows),
        "shortfall_note": shortfall_note(len(rows)),
        # Present as fields, not documentation: a client cannot render a ranking
        # without also receiving these.
        "disclaimer": ATTRIBUTION_DISCLAIMER,
        "score_disclaimer": SCORE_DISCLAIMER,
        "proximity_disclaimer": PROXIMITY_DISCLAIMER,
    }


@router.get("/attributions/{attribution_id}", summary="Factor-by-factor breakdown")
async def get_attribution(
    attribution_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Attribution, Vessel)
            .join(Vessel, Vessel.id == Attribution.vessel_id)
            .where(Attribution.id == attribution_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Attribution not found.", attribution_id=str(attribution_id))
    attribution, vessel = row
    await CaseRepository(session).get_for_user(attribution.case_id, user)
    payload = _attribution_payload(attribution, vessel)
    payload["run_manifest"] = attribution.run_manifest
    payload["evidence"] = attribution.evidence
    return payload


def _attribution_payload(attribution: Attribution, vessel: Vessel) -> dict[str, Any]:
    explanations = attribution.factor_explanations or {}
    ordered = (
        "origin_proximity",
        "time_match",
        "trajectory_match",
        "heading_match",
        "speed_match",
        "ais_reliability",
    )
    return {
        "id": str(attribution.id),
        "rank": attribution.rank,
        "vessel": {"id": str(vessel.id), "mmsi": vessel.mmsi, "name": vessel.name},
        "final_score": round(attribution.final_score, 4),
        "confidence_label": (attribution.evidence or {}).get("confidence_label"),
        "factors": [
            {
                "key": key,
                "label": explanations.get(key, {}).get("label", key),
                "weight": explanations.get(key, {}).get("weight"),
                "score": getattr(attribution, key),
                "contribution": explanations.get(key, {}).get("contribution"),
                "explanation": explanations.get(key, {}).get("explanation"),
                "evidence": explanations.get(key, {}).get("evidence"),
            }
            for key in ordered
        ],
        "weights": attribution.weights,
        "scoring_version": attribution.scoring_version,
        "closest_approach_km": (
            round(attribution.closest_approach_km, 3)
            if attribution.closest_approach_km is not None
            else None
        ),
        "closest_approach_time": (
            isoformat_utc(attribution.closest_approach_time)
            if attribution.closest_approach_time
            else None
        ),
        "data_provenance": attribution.data_provenance,
        "disclaimer": ATTRIBUTION_DISCLAIMER,
    }


# ------------------------------------------------------------------ report & artifacts
@router.get("/cases/{case_id}/artifacts", summary="Stored evidence artifacts")
async def list_artifacts(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await CaseRepository(session).get_for_user(case_id, user)
    rows = (
        (
            await session.execute(
                select(EvidenceArtifact)
                .where(EvidenceArtifact.case_id == case_id)
                .order_by(EvidenceArtifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(a.id),
                "artifact_type": a.artifact_type,
                "label": a.label,
                "media_type": a.media_type,
                "size_bytes": a.size_bytes,
                "checksum_sha256": a.checksum_sha256,
                "storage_uri": a.storage_uri,
                "data_provenance": a.data_provenance,
                "created_at": isoformat_utc(a.created_at),
            }
            for a in rows
        ],
        "total": len(rows),
    }


@router.get("/cases/{case_id}/report.html", summary="Evidence report (HTML)")
async def get_report_html(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    artifact = await _latest_artifact(session, case_id, "REPORT_HTML")
    store = build_object_store(settings)
    body = await store.get_bytes(artifact.storage_uri.split("/", 3)[-1])
    return Response(content=body, media_type="text/html")


@router.get("/cases/{case_id}/report.pdf", summary="Evidence report (PDF)")
async def get_report_pdf(
    case_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    artifact = await _latest_artifact(session, case_id, "REPORT_PDF")
    store = build_object_store(settings)
    body = await store.get_bytes(artifact.storage_uri.split("/", 3)[-1])
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="spilltrace-{case_id}.pdf"'},
    )


async def _latest_artifact(
    session: SessionDep, case_id: uuid.UUID, artifact_type: str
) -> EvidenceArtifact:
    artifact = (
        await session.execute(
            select(EvidenceArtifact)
            .where(
                EvidenceArtifact.case_id == case_id,
                EvidenceArtifact.artifact_type == artifact_type,
            )
            .order_by(EvidenceArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise NotFoundError(
            f"No {artifact_type} artifact exists for this case. Run the report stage first.",
            case_id=str(case_id),
        )
    return artifact


__all__ = ["router"]
