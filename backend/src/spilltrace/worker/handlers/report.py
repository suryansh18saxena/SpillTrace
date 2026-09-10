"""``report.build`` — assemble and store the evidence report (FR-018, AC-12)."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select

from spilltrace.adapters.storage import build_object_store
from spilltrace.core.enums import ArtifactType, JobType
from spilltrace.core.errors import NoDataError
from spilltrace.core.geometry import geodesic_area_km2
from spilltrace.core.jsonsafe import to_json_safe
from spilltrace.core.report import assemble_report, render_html
from spilltrace.core.scoring import shortfall_note
from spilltrace.core.time import isoformat_utc
from spilltrace.db.models import (
    AISPosition,
    Attribution,
    Case,
    CaseScene,
    DriftRun,
    EnvironmentalRun,
    EvidenceArtifact,
    ModelVersion,
    SatelliteScene,
    SpillDetection,
    Trajectory,
    VerificationResult,
    Vessel,
)
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register


@register(JobType.REPORT_BUILD)
async def build_report(ctx: JobContext) -> dict[str, Any]:
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")

    await ctx.progress(0.1, "collecting case artifacts")
    report = assemble_report(
        case=_case_section(case),
        scene=await _scene_section(ctx, case),
        detection=(detection_section := await _detection_section(ctx, case)),
        verification=await _verification_section(ctx, detection_section),
        environment=await _environment_section(ctx, case),
        drift=await _drift_section(ctx, case),
        ais=await _ais_section(ctx, case),
        attributions=(attributions := await _attribution_section(ctx, case)),
        artifacts=await _artifact_section(ctx, case),
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider_modes=ctx.settings.provider_modes(),
        shortfall_note=shortfall_note(len(attributions)),
    )

    missing = report.missing_sections()
    if missing:
        # Not fatal — a case can legitimately lack a stage — but it is recorded so the
        # report never silently omits something the reader expects.
        ctx.log("report_sections_missing", sections=missing)

    await ctx.progress(0.5, "rendering report")
    document = render_html(report)
    payload = document.encode("utf-8")

    store = build_object_store(ctx.settings)
    html_stored = await store.put_bytes(
        f"reports/{case.id}/report-{uuid.uuid4()}.html", payload, media_type="text/html"
    )
    ctx.session.add(
        EvidenceArtifact(
            case_id=case.id,
            artifact_type=ArtifactType.REPORT_HTML.value,
            label="Evidence report (HTML)",
            storage_uri=html_stored.uri,
            media_type="text/html",
            size_bytes=html_stored.size_bytes,
            checksum_sha256=html_stored.checksum_sha256,
            related_table="cases",
            related_id=case.id,
            artifact_metadata={"missing_sections": missing},
            data_provenance=case.data_provenance,
        )
    )

    await ctx.progress(0.75, "exporting PDF")
    pdf_uri = await _try_pdf(ctx, case, document, store)

    await ctx.session.flush()
    await ctx.progress(1.0, "evidence report ready")
    ctx.log(
        "report_built",
        html_uri=html_stored.uri,
        pdf_uri=pdf_uri,
        candidates=len(attributions),
    )
    return {
        "report_html_uri": html_stored.uri,
        "report_pdf_uri": pdf_uri,
        "checksum_sha256": html_stored.checksum_sha256,
        "missing_sections": missing,
        "candidate_count": len(attributions),
        "report": to_json_safe(report.to_dict()),
    }


async def _try_pdf(ctx: JobContext, case: Case, document: str, store: Any) -> str | None:
    """PDF export degrades to HTML-only rather than failing the job.

    WeasyPrint needs pango/cairo at runtime. When they are unavailable the HTML report —
    which is the canonical artifact — is still produced, and the absence is recorded.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:
        ctx.log("pdf_export_unavailable", reason=type(exc).__name__)
        return None
    try:
        import asyncio

        pdf_bytes = await asyncio.to_thread(lambda: HTML(string=document).write_pdf())
        stored = await store.put_bytes(
            f"reports/{case.id}/report-{uuid.uuid4()}.pdf",
            pdf_bytes,
            media_type="application/pdf",
        )
        ctx.session.add(
            EvidenceArtifact(
                case_id=case.id,
                artifact_type=ArtifactType.REPORT_PDF.value,
                label="Evidence report (PDF)",
                storage_uri=stored.uri,
                media_type="application/pdf",
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                related_table="cases",
                related_id=case.id,
                artifact_metadata={},
                data_provenance=case.data_provenance,
            )
        )
        return stored.uri
    except Exception as exc:
        ctx.log("pdf_export_failed", reason=type(exc).__name__)
        return None


# --------------------------------------------------------------------------- sections
def _case_section(case: Case) -> dict[str, Any]:
    aoi = to_shape(case.aoi)
    min_lon, min_lat, max_lon, max_lat = aoi.bounds
    return {
        "case_ref": case.case_ref,
        "title": case.title,
        "description": case.description,
        "status": case.status,
        "start_time": isoformat_utc(case.start_time),
        "end_time": isoformat_utc(case.end_time),
        "created_at": isoformat_utc(case.created_at),
        "data_provenance": case.data_provenance,
        "aoi_summary": (
            f"{min_lat:.4f}°–{max_lat:.4f}° N, {min_lon:.4f}°–{max_lon:.4f}° E "
            f"({geodesic_area_km2(aoi):,.0f} km²)"
        ),
        "aoi_geojson": _mapping(case.aoi),
        "scenario": case.scenario,
        "seed": case.seed,
    }


async def _scene_section(ctx: JobContext, case: Case) -> dict[str, Any] | None:
    row = (
        await ctx.session.execute(
            select(SatelliteScene)
            .join(CaseScene, CaseScene.scene_id == SatelliteScene.id)
            .where(CaseScene.case_id == case.id)
            .order_by(CaseScene.is_selected.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "product_id": row.product_id,
        "provider": row.provider,
        "mission": row.mission,
        "platform": row.platform,
        "product_type": row.product_type,
        "sensor_mode": row.sensor_mode,
        "acquisition_time": isoformat_utc(row.acquisition_time),
        "polarizations": row.polarizations,
        "orbit_direction": row.orbit_direction,
        "relative_orbit": row.relative_orbit,
        "storage_uri": row.storage_uri,
        "checksum_sha256": row.checksum_sha256,
        "data_provenance": row.data_provenance,
    }


async def _detection_section(ctx: JobContext, case: Case) -> dict[str, Any] | None:
    row = (
        await ctx.session.execute(
            select(SpillDetection)
            .where(SpillDetection.case_id == case.id)
            .order_by(SpillDetection.area_km2.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    model = (
        await ctx.session.get(ModelVersion, row.model_version_id) if row.model_version_id else None
    )
    return {
        "id": str(row.id),
        "detected_at": isoformat_utc(row.detected_at),
        "area_km2": round(row.area_km2, 3),
        "perimeter_km": round(row.perimeter_km, 3) if row.perimeter_km else None,
        "detection_confidence": row.detection_confidence,
        "mean_probability": row.mean_probability,
        "max_probability": row.max_probability,
        "threshold": row.threshold,
        "model_name": model.name if model else None,
        "model_version": model.version if model else None,
        "model_metrics": model.metrics if model else None,
        "probability_raster_uri": row.probability_raster_uri,
        "geometry": _mapping(row.geometry),
        "data_provenance": row.data_provenance,
        "run_manifest": row.run_manifest,
    }


async def _verification_section(
    ctx: JobContext, detection: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not detection:
        return None
    row = (
        await ctx.session.execute(
            select(VerificationResult).where(
                VerificationResult.spill_id == uuid.UUID(detection["id"]),
                VerificationResult.is_latest,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "status": row.status,
        "verification_confidence": row.verification_confidence,
        "wind_speed_ms": row.wind_speed_ms,
        "wind_direction_deg": round(row.wind_direction_deg, 1) if row.wind_direction_deg else None,
        "wind_source": row.wind_source,
        "explanation": row.explanation,
        "rules": row.rules,
        "features": row.features,
    }


async def _environment_section(ctx: JobContext, case: Case) -> dict[str, Any] | None:
    row = (
        await ctx.session.execute(
            select(EnvironmentalRun)
            .where(EnvironmentalRun.case_id == case.id)
            .order_by(EnvironmentalRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "source": row.source,
        "provider": row.provider,
        "dataset_id": row.dataset_id,
        "variables": row.variables,
        "time_start": isoformat_utc(row.time_start),
        "time_end": isoformat_utc(row.time_end),
        "grid_resolution_deg": row.grid_resolution_deg,
        "storage_uri": row.storage_uri,
        "checksum_sha256": row.checksum_sha256,
        "summary": row.summary,
        "data_provenance": row.data_provenance,
    }


async def _drift_section(ctx: JobContext, case: Case) -> dict[str, Any] | None:
    row = (
        await ctx.session.execute(
            select(DriftRun)
            .where(DriftRun.case_id == case.id, DriftRun.status == "COMPLETED")
            .order_by(DriftRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    from shapely.geometry import shape

    contour_areas = [
        (
            feature["properties"]["probability_mass"],
            round(geodesic_area_km2(shape(feature["geometry"])), 1),
        )
        for feature in (row.contours or {}).get("features", [])
    ]
    return {
        "engine": row.engine,
        "mode": row.mode,
        "seed": row.seed,
        "parameters": row.parameters,
        "number_of_particles": row.number_of_particles,
        "ensemble_members": row.ensemble_members,
        "duration_hours": row.duration_hours,
        "time_step_seconds": row.time_step_seconds,
        "origin_confidence": row.origin_confidence,
        "origin_area_km2": round(geodesic_area_km2(to_shape(row.origin_geometry)), 1)
        if row.origin_geometry is not None
        else None,
        "contour_areas": contour_areas,
        "inferred_start": isoformat_utc(row.inferred_start) if row.inferred_start else None,
        "inferred_end": isoformat_utc(row.inferred_end) if row.inferred_end else None,
        "density_grid_uri": row.density_grid_uri,
        "data_provenance": row.data_provenance,
        "run_manifest": row.run_manifest,
    }


async def _ais_section(ctx: JobContext, case: Case) -> dict[str, Any]:
    total = int(
        (
            await ctx.session.execute(
                select(func.count())
                .select_from(AISPosition)
                .where(
                    AISPosition.timestamp >= case.start_time,
                    AISPosition.timestamp <= case.end_time,
                )
            )
        ).scalar_one()
    )
    rejected = int(
        (
            await ctx.session.execute(
                select(func.count())
                .select_from(AISPosition)
                .where(
                    AISPosition.timestamp >= case.start_time,
                    AISPosition.timestamp <= case.end_time,
                    AISPosition.is_valid.is_(False),
                )
            )
        ).scalar_one()
    )
    trajectories = list(
        (await ctx.session.execute(select(Trajectory).where(Trajectory.case_id == case.id)))
        .scalars()
        .all()
    )
    by_vessel = {t.vessel_id: t for t in trajectories}
    vessels = list((await ctx.session.execute(select(Vessel))).scalars().all())

    source = "SYNTHETIC" if case.data_provenance != "REAL" else ctx.settings.ais_provider.upper()
    return {
        "source": source,
        "vessel_count": len(vessels),
        "position_count": total,
        "rejected_count": rejected,
        "trajectory_count": len(trajectories),
        "vessels": [
            {
                "mmsi": v.mmsi,
                "imo": v.imo,
                "name": v.name,
                "ship_type_name": v.ship_type_name,
                "flag_country": v.flag_country,
                "position_count": by_vessel[v.id].position_count if v.id in by_vessel else 0,
                "max_gap_minutes": round(by_vessel[v.id].max_gap_minutes, 1)
                if v.id in by_vessel
                else None,
                "coverage_ratio": round(by_vessel[v.id].coverage_ratio, 3)
                if v.id in by_vessel
                else None,
            }
            for v in vessels
        ],
    }


async def _attribution_section(ctx: JobContext, case: Case) -> list[dict[str, Any]]:
    rows = list(
        (
            await ctx.session.execute(
                select(Attribution, Vessel)
                .join(Vessel, Vessel.id == Attribution.vessel_id)
                .where(Attribution.case_id == case.id)
                .order_by(Attribution.rank)
            )
        ).all()
    )
    out: list[dict[str, Any]] = []
    for attribution, vessel in rows:
        factors = attribution.factor_explanations or {}
        out.append(
            {
                "rank": attribution.rank,
                "mmsi": vessel.mmsi,
                "imo": vessel.imo,
                "vessel_name": vessel.name,
                "final_score": round(attribution.final_score, 4),
                "confidence_label": (attribution.evidence or {}).get("confidence_label"),
                "closest_approach_km": round(attribution.closest_approach_km, 2)
                if attribution.closest_approach_km is not None
                else None,
                "closest_approach_time": isoformat_utc(attribution.closest_approach_time)
                if attribution.closest_approach_time
                else None,
                "scoring_version": attribution.scoring_version,
                "weights": attribution.weights,
                "factors": [
                    {
                        "key": key,
                        "label": value.get("label"),
                        "weight": value.get("weight"),
                        "score": value.get("score"),
                        "contribution": value.get("contribution"),
                        "explanation": value.get("explanation"),
                    }
                    for key, value in factors.items()
                ],
                "evidence": attribution.evidence,
            }
        )
    return out


async def _artifact_section(ctx: JobContext, case: Case) -> list[dict[str, Any]]:
    rows = list(
        (
            await ctx.session.execute(
                select(EvidenceArtifact)
                .where(EvidenceArtifact.case_id == case.id)
                .order_by(EvidenceArtifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "artifact_type": r.artifact_type,
            "label": r.label,
            "storage_uri": r.storage_uri,
            "media_type": r.media_type,
            "size_bytes": r.size_bytes,
            "checksum_sha256": r.checksum_sha256,
            "data_provenance": r.data_provenance,
        }
        for r in rows
    ]


def _mapping(geometry: Any) -> dict[str, Any] | None:
    if geometry is None:
        return None
    from shapely.geometry import mapping

    return mapping(to_shape(geometry))


__all__ = ["build_report"]
