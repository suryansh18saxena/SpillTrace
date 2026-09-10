"""``scene.search`` and ``scene.download`` — the Sentinel-1 acquisition stages (FR-003).

The catalogue behind these handlers is chosen by configuration and the choice is logged
and recorded: with CDSE credentials present they answer from real Copernicus metadata,
and without them they answer from the deterministic fixture, whose products carry
``data_provenance=SYNTHETIC`` all the way to the report.  Nothing in the two handlers
differs between those two worlds, which is the point — the real path is the one that gets
exercised offline.

An empty result set is a **finding, not a failure**: ``NoDataError`` says "no Sentinel-1
pass covered this area in this window", which is a true and useful statement about the
world, and is what the case should show.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select

from spilltrace.adapters.satellite import build_satellite_catalogue
from spilltrace.adapters.satellite.bundle import BUNDLE_FILENAME, SceneBundle, read_bundle
from spilltrace.adapters.storage import build_object_store
from spilltrace.core.enums import ArtifactType, DataProvenance, DownloadStatus, JobType
from spilltrace.core.errors import NoDataError, ProcessingError
from spilltrace.core.geometry import bbox_polygon, geodesic_area_km2, parse_geojson_geometry
from spilltrace.core.ports import SceneRecord
from spilltrace.core.provenance import RunManifest
from spilltrace.db.models import Case, CaseScene, EvidenceArtifact, SatelliteScene
from spilltrace.worker.context import JobContext
from spilltrace.worker.registry import register

#: More than this many candidates is noise for a single case.
DEFAULT_SEARCH_LIMIT = 20
#: A scene overlapping less than this fraction of the AOI is not worth a gigabyte.
MIN_COVERAGE_FRACTION = 0.02


@register(JobType.SCENE_SEARCH)
async def search_scenes(ctx: JobContext) -> dict[str, Any]:
    case = await _load_case(ctx)
    aoi = to_shape(case.aoi)
    catalogue = build_satellite_catalogue(ctx.settings)
    limit = int(ctx.payload.get("scene_limit") or DEFAULT_SEARCH_LIMIT)
    product_type = str(ctx.payload.get("product_type") or "IW_GRDH_1S")

    await ctx.progress(0.1, f"searching the {catalogue.name} catalogue")
    records = await catalogue.search(
        aoi_geojson=dict(mapping(aoi)),
        start=case.start_time,
        end=case.end_time,
        product_type=product_type,
        limit=limit,
    )
    if not records:
        raise NoDataError(
            "No Sentinel-1 scene of this product type covered the area of interest "
            "during the requested window. Widen the window or the area, or choose a "
            "different product type.",
            provider=catalogue.name,
            product_type=product_type,
        )

    await ctx.progress(0.5, f"ranking {len(records)} candidate scenes")
    aoi_area = geodesic_area_km2(aoi) or 1.0
    scored: list[tuple[float, SceneRecord, BaseGeometry]] = []
    for record in records:
        footprint = _footprint_polygon(record, fallback=aoi)
        try:
            overlap = footprint.intersection(aoi)
        except Exception:  # a self-intersecting footprint must not fail the whole search
            overlap = footprint.buffer(0).intersection(aoi)
        coverage = min(1.0, geodesic_area_km2(overlap) / aoi_area) if not overlap.is_empty else 0.0
        scored.append((coverage, record, footprint))

    usable = [item for item in scored if item[0] >= MIN_COVERAGE_FRACTION]
    if not usable:
        raise NoDataError(
            f"{len(records)} Sentinel-1 scenes intersected the search window but none "
            f"covered more than {MIN_COVERAGE_FRACTION:.0%} of the area of interest.",
            provider=catalogue.name,
            candidates=len(records),
        )
    # Coverage first, then the most recent pass: a fuller scene beats a fresher one.
    usable.sort(key=lambda item: (item[0], item[1].acquisition_time), reverse=True)

    manifest = RunManifest(
        stage="scene.search",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider=catalogue.name,
        provider_parameters={
            "product_type": product_type,
            "limit": limit,
            "window_start": case.start_time.isoformat(),
            "window_end": case.end_time.isoformat(),
        },
        data_provenance=usable[0][1].data_provenance,
    )

    selected_id = None
    summaries: list[dict[str, Any]] = []
    for rank, (coverage, record, footprint) in enumerate(usable, start=1):
        scene = await _upsert_scene(ctx, record, footprint)
        await _link_case_scene(ctx, scene, coverage=coverage, rank=rank, selected=rank == 1)
        if rank == 1:
            selected_id = scene.id
        summaries.append(
            {
                "scene_id": str(scene.id),
                "product_id": scene.product_id,
                "platform": scene.platform,
                "acquisition_time": scene.acquisition_time.isoformat(),
                "coverage_fraction": round(coverage, 4),
                "polarizations": list(scene.polarizations or ()),
                "data_provenance": scene.data_provenance,
                "rank": rank,
            }
        )

    await ctx.session.flush()
    await ctx.progress(1.0, f"{len(usable)} scenes catalogued")
    ctx.log(
        "scene_search_complete",
        provider=catalogue.name,
        candidates=len(records),
        retained=len(usable),
        selected=str(selected_id),
    )
    return {
        "provider": catalogue.name,
        "candidates": len(records),
        "retained": len(usable),
        "selected_scene_id": str(selected_id) if selected_id else None,
        "scenes": summaries,
        "run_manifest": manifest.to_dict(),
    }


@register(JobType.SCENE_DOWNLOAD)
async def download_scene(ctx: JobContext) -> dict[str, Any]:
    scene = await _selected_scene(ctx)
    if scene.download_status == DownloadStatus.DOWNLOADED.value and not ctx.payload.get("force"):
        ctx.log("scene_download_reused", scene_id=str(scene.id))
        return {
            "scene_id": str(scene.id),
            "product_id": scene.product_id,
            "reused": True,
            "storage_uri": scene.storage_uri,
        }

    catalogue = build_satellite_catalogue(ctx.settings)
    store = build_object_store(ctx.settings)
    record = _record_from_scene(scene)

    scene.download_status = DownloadStatus.DOWNLOADING.value
    await ctx.session.flush()

    workspace = await asyncio.to_thread(tempfile.mkdtemp, prefix="spilltrace-scene-")
    try:
        await ctx.progress(0.05, f"downloading {scene.product_id} from {catalogue.name}")

        async def relay(*, fraction: float, message: str) -> None:
            await ctx.progress(0.05 + 0.65 * fraction, message)

        try:
            await catalogue.download(record, destination=workspace, progress=relay)
        except Exception:
            scene.download_status = DownloadStatus.FAILED.value
            await ctx.session.flush()
            raise

        bundle = await asyncio.to_thread(read_bundle, workspace)
        await ctx.progress(0.75, "storing measurement bands")
        prefix = f"scenes/{scene.id}"
        uploaded: list[dict[str, Any]] = []
        for band in bundle.bands:
            stored = await store.put_file(
                f"{prefix}/{band.filename}",
                str(Path(workspace) / band.filename),
                media_type="image/tiff",
            )
            uploaded.append(
                {
                    "polarization": band.polarization,
                    "key": stored.key,
                    "uri": stored.uri,
                    "size_bytes": stored.size_bytes,
                    "checksum_sha256": stored.checksum_sha256,
                    "is_cog": band.is_cog,
                }
            )
            ctx.session.add(
                EvidenceArtifact(
                    case_id=ctx.case_id,
                    artifact_type=ArtifactType.GRD.value,
                    label=f"{scene.product_id} {band.polarization} measurement",
                    storage_uri=stored.uri,
                    media_type="image/tiff",
                    size_bytes=stored.size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                    related_table="satellite_scenes",
                    related_id=scene.id,
                    artifact_metadata={
                        "polarization": band.polarization,
                        "is_cog": band.is_cog,
                        "source_url": band.source_url,
                    },
                    data_provenance=scene.data_provenance,
                )
            )

        manifest_object = await store.put_file(
            f"{prefix}/{BUNDLE_FILENAME}",
            str(Path(workspace) / BUNDLE_FILENAME),
            media_type="application/json",
        )
        scene.storage_uri = manifest_object.uri
        scene.size_bytes = bundle.total_bytes
        scene.checksum_sha256 = bundle.manifest_checksum()
        scene.download_status = DownloadStatus.DOWNLOADED.value
        await ctx.session.flush()
    finally:
        await asyncio.to_thread(shutil.rmtree, workspace, True)

    await ctx.progress(1.0, "scene stored")
    ctx.log(
        "scene_download_complete",
        scene_id=str(scene.id),
        bands=[band.polarization for band in bundle.bands],
        total_bytes=bundle.total_bytes,
    )
    return {
        "scene_id": str(scene.id),
        "product_id": scene.product_id,
        "provider": catalogue.name,
        "storage_uri": scene.storage_uri,
        "bands": uploaded,
        "total_bytes": bundle.total_bytes,
        "notes": list(bundle.notes),
        "data_provenance": scene.data_provenance,
    }


# --------------------------------------------------------------------------- helpers
async def _load_case(ctx: JobContext) -> Case:
    case = await ctx.session.get(Case, ctx.case_id)
    if case is None:
        raise NoDataError("The case for this job no longer exists.")
    return case


def _footprint_polygon(record: SceneRecord, *, fallback: BaseGeometry) -> Polygon:
    """A single POLYGON for the database column.

    A footprint that crosses the antimeridian arrives as a MultiPolygon.  The larger
    part is kept — a convex hull across the dateline would wrap the planet — and the
    substitution is visible in ``provider_ref``.
    """
    try:
        geometry = parse_geojson_geometry(record.footprint_geojson)
    except Exception:
        geometry = fallback
    if geometry.is_empty:
        geometry = fallback
    if isinstance(geometry, MultiPolygon):
        geometry = max(geometry.geoms, key=lambda part: part.area)
    if not isinstance(geometry, Polygon):
        geometry = geometry.convex_hull
    if not geometry.is_valid:
        repaired = geometry.buffer(0)
        geometry = repaired if isinstance(repaired, Polygon) else geometry
    if not isinstance(geometry, Polygon) or geometry.is_empty:
        bounds = fallback.bounds
        return bbox_polygon(*bounds)
    return geometry


async def _upsert_scene(ctx: JobContext, record: SceneRecord, footprint: Polygon) -> SatelliteScene:
    existing = (
        await ctx.session.execute(
            select(SatelliteScene).where(SatelliteScene.product_id == record.product_id)
        )
    ).scalar_one_or_none()

    provider_ref = {
        **record.provider_ref,
        "footprint_geom_type": record.footprint_geojson.get("type"),
    }
    if existing is not None:
        # A scene is a global observation; a second case finding it must not fork it.
        existing.provider_ref = provider_ref
        return existing

    scene = SatelliteScene(
        product_id=record.product_id,
        provider=record.provider.upper(),
        mission=record.mission,
        platform=record.platform,
        product_type=record.product_type,
        sensor_mode=record.sensor_mode,
        acquisition_time=record.acquisition_time,
        footprint=from_shape(footprint, srid=4326),
        bbox=from_shape(bbox_polygon(*footprint.bounds), srid=4326),
        polarizations=list(record.polarizations) or None,
        orbit_direction=record.orbit_direction,
        relative_orbit=record.relative_orbit,
        absolute_orbit=record.absolute_orbit,
        resolution_m=record.resolution_m,
        provider_ref=provider_ref,
        size_bytes=record.size_bytes,
        download_status=DownloadStatus.NOT_DOWNLOADED.value,
        data_provenance=str(record.data_provenance),
    )
    ctx.session.add(scene)
    await ctx.session.flush()
    return scene


async def _link_case_scene(
    ctx: JobContext, scene: SatelliteScene, *, coverage: float, rank: int, selected: bool
) -> None:
    link = await ctx.session.get(CaseScene, (ctx.case_id, scene.id))
    if link is None:
        link = CaseScene(case_id=ctx.case_id, scene_id=scene.id)
        ctx.session.add(link)
    link.coverage_fraction = round(coverage, 6)
    link.rank = rank
    link.is_selected = selected


async def _selected_scene(ctx: JobContext) -> SatelliteScene:
    scene_id = ctx.payload.get("scene_id")
    if scene_id:
        scene = await ctx.session.get(SatelliteScene, scene_id)
        if scene is None:
            raise NoDataError(f"Scene {scene_id} is not in the catalogue table.")
        return scene

    rows = list(
        (
            await ctx.session.execute(
                select(SatelliteScene, CaseScene)
                .join(CaseScene, CaseScene.scene_id == SatelliteScene.id)
                .where(CaseScene.case_id == ctx.case_id)
                .order_by(CaseScene.is_selected.desc(), CaseScene.rank.asc())
            )
        ).all()
    )
    if not rows:
        raise NoDataError(
            "No Sentinel-1 scene has been catalogued for this case, so there is nothing "
            "to download. Run the scene search first."
        )
    return rows[0][0]


def _record_from_scene(scene: SatelliteScene) -> SceneRecord:
    """Rebuild the catalogue record a download needs from the persisted row."""
    return SceneRecord(
        product_id=scene.product_id,
        provider=scene.provider.lower(),
        acquisition_time=scene.acquisition_time,
        footprint_geojson=dict(mapping(to_shape(scene.footprint))),
        mission=scene.mission,
        platform=scene.platform,
        product_type=scene.product_type,
        sensor_mode=scene.sensor_mode,
        polarizations=tuple(scene.polarizations or ()),
        orbit_direction=scene.orbit_direction,
        relative_orbit=scene.relative_orbit,
        absolute_orbit=scene.absolute_orbit,
        size_bytes=scene.size_bytes,
        resolution_m=scene.resolution_m,
        provider_ref=dict(scene.provider_ref or {}),
        data_provenance=DataProvenance(scene.data_provenance),
    )


async def load_scene_bundle(store: Any, scene: SatelliteScene) -> SceneBundle:
    """Read a downloaded scene's band manifest back out of object storage."""
    if not scene.storage_uri:
        raise ProcessingError(
            f"Scene {scene.product_id} has no stored bundle manifest; the download stage "
            "did not complete."
        )
    import json

    key = scene.storage_uri.split("/", 3)[-1]
    payload = await store.get_bytes(key)
    return SceneBundle.from_dict(json.loads(payload.decode("utf-8")))


__all__ = ["download_scene", "load_scene_bundle", "search_scenes"]
