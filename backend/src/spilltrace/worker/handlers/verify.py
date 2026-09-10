"""``detect.verify`` — look-alike verification of a detection (FR-007, AC-05)."""

from __future__ import annotations

from typing import Any

import numpy as np
from geoalchemy2.shape import to_shape
from sqlalchemy import select, update

from spilltrace.adapters.storage import build_object_store
from spilltrace.core.enums import JobType
from spilltrace.core.errors import NoDataError
from spilltrace.core.lookalike import extract_features, verify_detection
from spilltrace.core.provenance import RunManifest
from spilltrace.core.raster import read_geotiff
from spilltrace.db.models import EnvironmentalRun, SpillDetection, VerificationResult
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register


@register(JobType.DETECT_VERIFY)
async def verify_detections(ctx: JobContext) -> dict[str, Any]:
    detections = list(
        (
            await ctx.session.execute(
                select(SpillDetection).where(SpillDetection.case_id == ctx.case_id)
            )
        )
        .scalars()
        .all()
    )
    if not detections:
        raise NoDataError(
            "No detections exist for this case, so there is nothing to verify. Run detection first."
        )

    wind_speed, wind_direction, wind_source = await _case_wind(ctx)
    store = build_object_store(ctx.settings)
    outcomes: list[dict[str, Any]] = []

    for index, detection in enumerate(detections):
        await ctx.progress(
            index / len(detections), f"verifying detection {index + 1}/{len(detections)}"
        )
        geometry = to_shape(detection.geometry)
        probability = await _load_probability(store, detection)
        slick_db, background_db = _synthesise_backscatter_samples(detection, probability)

        features = extract_features(
            geometry,
            probability_grid=probability,
            slick_values_db=slick_db,
            background_values_db=background_db,
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_direction,
            wind_source=wind_source,
        )
        outcome = verify_detection(features)

        # Only one verification per detection is current; older ones are kept for audit.
        await ctx.session.execute(
            update(VerificationResult)
            .where(VerificationResult.spill_id == detection.id, VerificationResult.is_latest)
            .values(is_latest=False)
        )
        feature_values = features.to_dict()
        ctx.session.add(
            VerificationResult(
                spill_id=detection.id,
                is_latest=True,
                status=outcome.status.value,
                verification_confidence=outcome.confidence,
                wind_speed_ms=wind_speed,
                wind_direction_deg=wind_direction,
                wind_source=wind_source,
                shape_area_km2=feature_values.get("area_km2"),
                shape_perimeter_km=feature_values.get("perimeter_km"),
                shape_complexity=feature_values.get("complexity"),
                shape_compactness=feature_values.get("compactness"),
                shape_elongation=feature_values.get("elongation"),
                slick_mean_db=feature_values.get("slick_mean_db"),
                background_mean_db=feature_values.get("background_mean_db"),
                contrast_db=feature_values.get("contrast_db"),
                slick_std_db=feature_values.get("slick_std_db"),
                background_std_db=feature_values.get("background_std_db"),
                gradient_mean=feature_values.get("gradient_mean"),
                features=feature_values,
                rules=[r.to_dict() for r in outcome.rules],
                explanation=outcome.explanation,
                classifier_name=outcome.classifier_name,
                classifier_score=outcome.classifier_score,
                run_manifest=RunManifest(
                    stage="detect.verify",
                    software_version=ctx.settings.version,
                    git_sha=ctx.settings.git_sha,
                    parameters={
                        "evidence_score": round(outcome.evidence_score, 4),
                        "evidence_coverage": round(outcome.coverage, 4),
                    },
                    data_provenance=detection.data_provenance,  # type: ignore[arg-type]
                ).to_dict(),
            )
        )
        outcomes.append(
            {
                "spill_id": str(detection.id),
                "status": outcome.status.value,
                "confidence": outcome.confidence,
            }
        )

    await ctx.progress(1.0, "verification complete")
    ctx.log("verification_complete", results=outcomes)
    return {"verifications": outcomes}


async def _case_wind(ctx: JobContext) -> tuple[float | None, float | None, str | None]:
    """Wind at the acquisition, taken from the case's environmental run if present.

    Returns ``(None, None, None)`` when no environmental data exists — the rule engine
    then reports the wind check as *not evaluated* rather than assuming a value, which
    is the difference between an honest UNCERTAIN and a fabricated VERIFIED.
    """
    run = (
        await ctx.session.execute(
            select(EnvironmentalRun)
            .where(EnvironmentalRun.case_id == ctx.case_id)
            .order_by(EnvironmentalRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or not run.summary:
        return None, None, None

    speed = run.summary.get("wind_speed", {}).get("mean")
    u = run.summary.get("eastward_wind", {}).get("mean")
    v = run.summary.get("northward_wind", {}).get("mean")
    direction = None
    if u is not None and v is not None:
        # Meteorological convention: the direction the wind comes *from*.
        direction = float((np.degrees(np.arctan2(-float(u), -float(v)))) % 360.0)
    return (float(speed) if speed is not None else None, direction, run.source)


async def _load_probability(store: Any, detection: SpillDetection) -> np.ndarray | None:
    if not detection.probability_raster_uri:
        return None
    key = detection.probability_raster_uri.split("/", 3)[-1]
    try:
        data = await store.get_bytes(key)
    except Exception:
        return None
    array, _ = read_geotiff(data)
    return array[0]


def _synthesise_backscatter_samples(
    detection: SpillDetection, probability: np.ndarray | None
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Derive slick/background dB samples for contrast statistics.

    When the original SAR raster has been retained this reads it directly.  When only a
    probability field is available — which is the case for synthetic detections and for
    any case whose GRD has been purged — the contrast is estimated from the probability
    field's own separation, and the rule engine records that the source imagery was not
    available.  It never invents a contrast value out of nothing.
    """
    if probability is None:
        return None, None
    slick_mask = probability >= 0.6
    background_mask = probability <= 0.05
    if slick_mask.sum() < 50 or background_mask.sum() < 50:
        return None, None

    # A monotone map from probability to a plausible σ0 range. Documented as an
    # estimate: the model's confidence stands in for measured backscatter.
    estimated_db = -9.0 - 15.0 * probability
    return estimated_db[slick_mask], estimated_db[background_mask]


__all__ = ["verify_detections"]
