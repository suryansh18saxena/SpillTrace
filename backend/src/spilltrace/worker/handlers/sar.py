"""``sar.preprocess`` and ``ml.detect`` — GRD to georeferenced slick (FR-004, FR-005).

```
GRD bands ──► σ0 → dB ──► per-scene percentile clip ──► standardise ──► valid mask
          ──► tile 128/96 ──► model ──► cosine-blended stitch ──► probability raster
          ──► hysteresis threshold ──► morphology ──► polygonise ──► spill_detections
```

Everything that could quietly change a result is written into the run manifest: the clip
bounds actually used (AD-12), the masking parameters, the tiling geometry, which model
answered and whether it was trained.  A detection produced by the analytical detector is
labelled ``SYNTHETIC`` and says so in its notes; nobody reading the case can mistake it
for a trained model's judgement.

Finding no slick is a **result**.  ``NoDataError`` reports "the scene contains no region
above threshold", which is a true statement about the scene and often the correct one.
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from geoalchemy2.shape import from_shape
from sqlalchemy import select

from spilltrace.adapters.storage import build_object_store
from spilltrace.core.confidence import confidence_manifest
from spilltrace.core.enums import ArtifactType, DataProvenance, DownloadStatus, JobType
from spilltrace.core.errors import NoDataError, ProcessingError
from spilltrace.core.masking import MaskConfig, build_mask
from spilltrace.core.polygonize import polygonize_mask, transform_for_bounds
from spilltrace.core.provenance import RunManifest, combine_provenance
from spilltrace.core.raster import read_geotiff, write_geotiff
from spilltrace.db.models import (
    CaseScene,
    EvidenceArtifact,
    ModelVersion,
    SatelliteScene,
    SpillDetection,
)
from spilltrace.ml.inference import CheckpointRef, build_segmentation_model
from spilltrace.ml.preprocess import (
    DEFAULT_CLIP_PERCENTILES,
    preprocess_bands,
    read_sigma0_band,
)
from spilltrace.ml.stitch import stitch_tiles
from spilltrace.ml.tiling import DEFAULT_STRIDE, DEFAULT_TILE_SIZE, tile_array
from spilltrace.worker.context import JobContext
from spilltrace.worker.handlers.satellite import load_scene_bundle
from spilltrace.worker.registry import register

#: Longest side of the working raster.  A full GRD is decimated to this on read; the
#: decimation factor is recorded so a reported pixel count can be converted back.
DEFAULT_MAX_DIMENSION = 4096
#: Tiles per forward pass.  Small enough to report progress, large enough to amortise.
INFERENCE_BATCH = 64
#: Band order written by ``sar.preprocess`` and expected by ``ml.detect``.
PREPROCESSED_BANDS = ("vv_standardised", "vh_standardised", "valid_mask")
#: ``SceneBundle.extra["units"]`` values that mean "these bands are already in dB".
DB_UNIT_NAMES = frozenset({"db", "sigma0_db", "sigma0 db", "decibel", "decibels"})


@register(JobType.SAR_PREPROCESS)
async def preprocess_scene(ctx: JobContext) -> dict[str, Any]:
    scene = await _downloaded_scene(ctx)
    store = build_object_store(ctx.settings)
    bundle = await load_scene_bundle(store, scene)
    if not bundle.bands:
        raise ProcessingError(
            f"The stored bundle for {scene.product_id} lists no measurement bands."
        )

    max_dimension = int(ctx.payload.get("max_dimension") or DEFAULT_MAX_DIMENSION)
    percentiles = _percentiles(ctx.payload)
    notes = list(bundle.notes)

    arrays: dict[str, np.ndarray] = {}
    band_meta: dict[str, Any] = {}
    footprint_bounds = _scene_bounds(scene)
    bounds = footprint_bounds
    georeferenced = False

    for index, band in enumerate(bundle.bands):
        await ctx.progress(
            0.05 + 0.35 * index / max(1, len(bundle.bands)),
            f"reading {band.polarization} measurement",
        )
        key = f"scenes/{scene.id}/{band.filename}"
        payload = await store.get_bytes(key)
        array, raster_bounds, meta = read_sigma0_band(payload, max_dimension=max_dimension)
        arrays[band.polarization.upper()] = array
        band_meta[band.polarization.upper()] = meta
        if meta["georeferenced"] and not georeferenced:
            bounds, georeferenced = raster_bounds, True

    if not georeferenced:
        notes.append(
            "The measurement files carry no map CRS — a Sentinel-1 GRD is annotated with "
            "a GCP grid rather than an affine transform — so the raster was georeferenced "
            "from the product footprint corners. Positions are approximate at the "
            "sub-kilometre scale."
        )

    shapes = {array.shape for array in arrays.values()}
    if len(shapes) > 1:
        smallest = min(shapes, key=lambda shape: shape[0] * shape[1])
        arrays = {name: array[: smallest[0], : smallest[1]] for name, array in arrays.items()}
        notes.append(f"Bands differed in size ({sorted(shapes)}); all were cropped to {smallest}.")

    # A bundle states the units of the bands it carries.  Catalogue products are linear
    # power; an operator-supplied file may already be in dB, and logging it twice would
    # silently empty the scene rather than fail (see ``sigma0_to_db``).
    already_db = str(bundle.extra.get("units") or "").strip().lower() in DB_UNIT_NAMES
    await ctx.progress(
        0.5, "standardising" if already_db else "converting to dB and standardising"
    )
    scene_data = preprocess_bands(arrays, percentiles=percentiles, already_db=already_db)
    notes.extend(scene_data.notes)

    stack = np.concatenate(
        [scene_data.array, scene_data.valid_mask[np.newaxis, :, :].astype(np.float32)], axis=0
    )
    manifest = RunManifest(
        stage="sar.preprocess",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider=scene.provider,
        parameters={
            "max_dimension": max_dimension,
            "clip_percentiles": list(percentiles),
            "bands_read": dict(band_meta),
            "georeferenced_from": "raster" if georeferenced else "product footprint",
            "bounds": list(bounds),
            **scene_data.to_manifest(),
        },
        data_provenance=DataProvenance(scene.data_provenance),
    )
    manifest.with_input("scene_bundle", scene.checksum_sha256 or str(scene.id))
    for note in notes:
        manifest.note(note)

    await ctx.progress(0.8, "storing the preprocessed stack")
    payload = write_geotiff(
        stack,
        bounds=bounds,
        dtype="float32",
        band_descriptions=PREPROCESSED_BANDS,
        tags={
            "stage": "sar.preprocess",
            "scene_id": str(scene.id),
            "product_id": scene.product_id,
            "provenance": scene.data_provenance,
            "clip_low_db": ",".join(f"{s.clip_low_db:.4f}" for s in scene_data.statistics),
            "clip_high_db": ",".join(f"{s.clip_high_db:.4f}" for s in scene_data.statistics),
        },
    )
    stored = await store.put_bytes(
        f"preprocessed/{ctx.case_id}/{scene.id}.tif", payload, media_type="image/tiff"
    )
    ctx.session.add(
        EvidenceArtifact(
            case_id=ctx.case_id,
            artifact_type=ArtifactType.TILE.value,
            label=f"Preprocessed SAR stack — {scene.product_id}",
            storage_uri=stored.uri,
            media_type="image/tiff",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            related_table="satellite_scenes",
            related_id=scene.id,
            artifact_metadata={
                "bounds": list(bounds),
                "bands": list(PREPROCESSED_BANDS),
                "normalisation": scene_data.to_manifest()["normalisation"],
                "shape": [int(stack.shape[0]), int(stack.shape[1]), int(stack.shape[2])],
                "notes": notes,
            },
            data_provenance=scene.data_provenance,
        )
    )
    await ctx.session.flush()

    await ctx.progress(1.0, "preprocessing complete")
    ctx.log(
        "sar_preprocess_complete",
        scene_id=str(scene.id),
        shape=list(stack.shape),
        clip_bounds=[[s.clip_low_db, s.clip_high_db] for s in scene_data.statistics],
    )
    return {
        "scene_id": str(scene.id),
        "artifact_uri": stored.uri,
        "shape": [int(v) for v in stack.shape],
        "bounds": list(bounds),
        "bands": list(scene_data.bands),
        "normalisation": scene_data.to_manifest()["normalisation"],
        "notes": notes,
        "run_manifest": manifest.to_dict(),
        "data_provenance": scene.data_provenance,
    }


@register(JobType.ML_DETECT)
async def detect_slicks(ctx: JobContext) -> dict[str, Any]:
    store = build_object_store(ctx.settings)
    artifact, scene = await _preprocessed_artifact(ctx)

    key = artifact.storage_uri.split("/", 3)[-1]
    stack, raster_meta = read_geotiff(await store.get_bytes(key))
    if stack.shape[0] < 2:
        raise ProcessingError(
            "The preprocessed stack has fewer than two channels; it cannot be fed to a "
            "two-channel model."
        )
    inputs = stack[:2].astype(np.float32)
    valid = stack[2] > 0.5 if stack.shape[0] > 2 else np.ones(inputs.shape[1:], dtype=bool)
    bounds = _as_bounds(raster_meta["bounds"])
    height, width = int(inputs.shape[1]), int(inputs.shape[2])

    mask_config = _mask_config(ctx.payload)

    checkpoint = await _resolve_checkpoint(ctx, store)
    model = build_segmentation_model(ctx.settings, checkpoint=checkpoint)
    describe = model.describe()

    # A trained model is tiled at the patch size it was trained on (the registry row's
    # ``input_size``; 256 px for the ResNet-34 checkpoint) with a 3/4 stride, unless the
    # job says otherwise.  The analytical detector keeps the 128/96 default.
    tile_size, stride = _tile_geometry(ctx.payload, describe)

    await ctx.progress(0.1, "tiling the scene")
    tiles, windows = tile_array(
        inputs,
        tile_size=tile_size,
        stride=stride,
        transform=tuple(float(v) for v in raster_meta["transform"]),  # type: ignore[arg-type]
    )

    await ctx.progress(0.2, f"running {model.name} over {len(windows)} tiles")
    predictions: list[np.ndarray] = []
    notes: list[str] = []
    provenance = DataProvenance.REAL
    for start in range(0, tiles.shape[0], INFERENCE_BATCH):
        batch = tiles[start : start + INFERENCE_BATCH]
        result = await model.predict(batch)
        predictions.append(np.asarray(result.probability, dtype=np.float32))
        if start == 0:
            notes = list(result.notes)
            provenance = result.data_provenance
        await ctx.progress(
            0.2 + 0.45 * min(1.0, (start + batch.shape[0]) / max(1, tiles.shape[0])),
            f"inference {min(tiles.shape[0], start + batch.shape[0])}/{tiles.shape[0]} tiles",
        )
    tile_probabilities = np.concatenate(predictions, axis=0)

    await ctx.progress(0.7, "blending overlapping tiles")
    padded_shape = (
        max(height, tile_size),
        max(width, tile_size),
    )
    probability = stitch_tiles(tile_probabilities, windows, shape=padded_shape)[:height, :width]
    probability = np.where(valid, probability, 0.0).astype(np.float32)

    await ctx.progress(0.78, "thresholding and cleaning the mask")
    mask_result = build_mask(probability, mask_config, valid_mask=valid)
    if mask_result.pixel_count == 0:
        raise NoDataError(
            "No region of this scene exceeded the detection threshold, so no slick was "
            f"recorded. Threshold {mask_config.threshold} with hysteresis floor "
            f"{mask_config.hysteresis_low}; "
            f"{mask_result.stages['above_threshold']} pixels were above threshold before "
            "morphology.",
            scene_id=str(scene.id) if scene else None,
            model=model.name,
        )

    await ctx.progress(0.85, "polygonising")
    transform = transform_for_bounds(bounds, width, height)
    polygons = polygonize_mask(
        mask_result.mask,
        transform=transform,
        probability=probability,
        labels=mask_result.labels,
        min_area_km2=float(ctx.payload.get("min_area_km2") or 0.0),
        simplify_pixels=float(ctx.payload.get("simplify_pixels") or 0.0),
    )
    if polygons.is_empty:
        raise NoDataError(
            "Every candidate region was removed by the minimum-area filter, so no slick "
            "was recorded.",
            min_area_km2=float(ctx.payload.get("min_area_km2") or 0.0),
        )

    model_version = await _ensure_model_version(ctx, describe)
    scene_provenance = DataProvenance(scene.data_provenance) if scene else DataProvenance.SYNTHETIC
    detection_provenance = combine_provenance(scene_provenance, provenance)

    manifest = RunManifest(
        stage="ml.detect",
        software_version=ctx.settings.version,
        git_sha=ctx.settings.git_sha,
        provider=str(describe.get("framework") or "unknown"),
        model_name=model.name,
        model_version=model.version,
        parameters={
            "tile_size": tile_size,
            "tile_stride": stride,
            "tiles": int(tiles.shape[0]),
            "blend": "cosine window",
            "masking": mask_result.to_dict(),
            "polygons": polygons.to_dict()["polygons"],
            "model": describe,
            **confidence_manifest(mask_config.threshold),
        },
        data_provenance=detection_provenance,
    )
    manifest.with_input("preprocessed_stack", artifact.checksum_sha256 or str(artifact.id))
    for note in notes:
        manifest.note(note)
    if not describe.get("trained"):
        manifest.note(
            "No trained model was used. The regions below were found by a deterministic "
            "contrast detector and are labelled SYNTHETIC for that reason."
        )

    await ctx.progress(0.9, "storing probability and mask rasters")
    probability_uri = await _store_raster(
        ctx,
        store,
        probability,
        bounds=bounds,
        key=f"probability/{ctx.case_id}/{uuid.uuid4()}.tif",
        band="oil_probability",
        artifact_type=ArtifactType.PROBABILITY_RASTER,
        label=f"Oil probability raster ({model.name})",
        provenance=detection_provenance,
        scene_id=scene.id if scene else None,
    )
    mask_uri = await _store_raster(
        ctx,
        store,
        mask_result.mask.astype(np.float32),
        bounds=bounds,
        key=f"mask/{ctx.case_id}/{uuid.uuid4()}.tif",
        band="oil_mask",
        artifact_type=ArtifactType.MASK,
        label=f"Detection mask ({model.name})",
        provenance=detection_provenance,
        scene_id=scene.id if scene else None,
    )

    detection = SpillDetection(
        case_id=ctx.case_id,
        scene_id=scene.id if scene else None,
        model_version_id=model_version.id,
        geometry=from_shape(polygons.multipolygon, srid=4326),
        centroid=from_shape(polygons.multipolygon.centroid, srid=4326),
        area_km2=round(polygons.area_km2, 6),
        perimeter_km=round(polygons.perimeter_km, 6),
        detection_confidence=polygons.detection_confidence,
        mean_probability=round(
            float(probability[mask_result.mask].mean()) if mask_result.pixel_count else 0.0, 4
        ),
        max_probability=round(polygons.max_probability, 4),
        threshold=mask_config.threshold,
        pixel_count=polygons.pixel_count,
        probability_raster_uri=probability_uri,
        mask_raster_uri=mask_uri,
        detected_at=scene.acquisition_time if scene else ctx.job.created_at,
        run_manifest=manifest.to_dict(),
        data_provenance=str(detection_provenance),
    )
    ctx.session.add(detection)
    await ctx.session.flush()

    await ctx.progress(1.0, "detection complete")
    ctx.log(
        "ml_detect_complete",
        model=model.name,
        trained=bool(describe.get("trained")),
        polygons=len(polygons.polygons),
        area_km2=round(polygons.area_km2, 3),
        detection_confidence=polygons.detection_confidence,
    )
    return {
        "spill_id": str(detection.id),
        "scene_id": str(scene.id) if scene else None,
        "model": model.name,
        "model_version": model.version,
        "trained_model_used": bool(describe.get("trained")),
        "polygon_count": len(polygons.polygons),
        "area_km2": round(polygons.area_km2, 4),
        "detection_confidence": polygons.detection_confidence,
        "threshold": mask_config.threshold,
        "pixel_count": polygons.pixel_count,
        "data_provenance": str(detection_provenance),
        "manifest_fingerprint": manifest.fingerprint(),
        "notes": manifest.notes,
    }


# --------------------------------------------------------------------------- helpers


def _tile_geometry(payload: dict[str, Any], describe: dict[str, Any]) -> tuple[int, int]:
    """Tile size / stride for this run: payload override, else the model's patch size."""
    model_size = int(describe.get("input_size") or 0) if describe.get("trained") else 0
    default_size = model_size if model_size >= 32 else DEFAULT_TILE_SIZE
    tile_size = int(payload.get("tile_size") or default_size)
    if payload.get("tile_stride"):
        stride = int(payload["tile_stride"])
    elif tile_size == DEFAULT_TILE_SIZE:
        stride = DEFAULT_STRIDE
    else:
        stride = max(1, (tile_size * 3) // 4)
    return tile_size, min(stride, tile_size)


def _percentiles(payload: dict[str, Any]) -> tuple[float, float]:
    raw = payload.get("clip_percentiles")
    if isinstance(raw, list | tuple) and len(raw) == 2:
        return float(raw[0]), float(raw[1])
    return DEFAULT_CLIP_PERCENTILES


def _mask_config(payload: dict[str, Any]) -> MaskConfig:
    raw = payload.get("masking")
    options: dict[str, Any] = raw if isinstance(raw, dict) else {}
    defaults = MaskConfig()
    return MaskConfig(
        threshold=float(options.get("threshold", defaults.threshold)),
        hysteresis_low=float(options.get("hysteresis_low", defaults.hysteresis_low)),
        opening_radius_px=int(options.get("opening_radius_px", defaults.opening_radius_px)),
        closing_radius_px=int(options.get("closing_radius_px", defaults.closing_radius_px)),
        min_area_px=int(options.get("min_area_px", defaults.min_area_px)),
        fill_holes=bool(options.get("fill_holes", defaults.fill_holes)),
    )


def _as_bounds(values: Any) -> tuple[float, float, float, float]:
    """Narrow a four-element sequence to the bounds tuple the raster helpers expect."""
    parts = [float(v) for v in values]
    if len(parts) != 4:
        raise ProcessingError(f"Expected four bounds coordinates, got {len(parts)}.")
    return (parts[0], parts[1], parts[2], parts[3])


def _scene_bounds(scene: SatelliteScene) -> tuple[float, float, float, float]:
    from geoalchemy2.shape import to_shape

    bounds = to_shape(scene.footprint).bounds
    return (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))


async def _downloaded_scene(ctx: JobContext) -> SatelliteScene:
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
    for scene, _ in rows:
        if scene.download_status == DownloadStatus.DOWNLOADED.value and scene.storage_uri:
            return scene
    if not rows:
        raise NoDataError(
            "No Sentinel-1 scene is linked to this case. Run the scene search and "
            "download stages first."
        )
    raise NoDataError(
        "No scene for this case has been downloaded, so there is nothing to preprocess."
    )


async def _preprocessed_artifact(
    ctx: JobContext,
) -> tuple[EvidenceArtifact, SatelliteScene | None]:
    artifact = (
        await ctx.session.execute(
            select(EvidenceArtifact)
            .where(
                EvidenceArtifact.case_id == ctx.case_id,
                EvidenceArtifact.artifact_type == ArtifactType.TILE.value,
            )
            .order_by(EvidenceArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if artifact is None or not artifact.storage_uri:
        raise NoDataError(
            "This case has no preprocessed SAR stack, so detection cannot run. Run "
            "sar.preprocess first."
        )
    scene = (
        await ctx.session.get(SatelliteScene, artifact.related_id) if artifact.related_id else None
    )
    return artifact, scene


async def _store_raster(
    ctx: JobContext,
    store: Any,
    array: np.ndarray,
    *,
    bounds: tuple[float, float, float, float],
    key: str,
    band: str,
    artifact_type: ArtifactType,
    label: str,
    provenance: DataProvenance,
    scene_id: uuid.UUID | None,
) -> str:
    payload = write_geotiff(
        array,
        bounds=bounds,
        dtype="float32",
        nodata=0.0,
        band_descriptions=(band,),
        tags={"stage": "ml.detect", "band": band, "provenance": str(provenance)},
    )
    stored = await store.put_bytes(key, payload, media_type="image/tiff")
    ctx.session.add(
        EvidenceArtifact(
            case_id=ctx.case_id,
            artifact_type=artifact_type.value,
            label=label,
            storage_uri=stored.uri,
            media_type="image/tiff",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            related_table="satellite_scenes",
            related_id=scene_id,
            artifact_metadata={"bounds": list(bounds), "band": band},
            data_provenance=str(provenance),
        )
    )
    return str(stored.uri)


async def _ensure_model_version(ctx: JobContext, describe: dict[str, Any]) -> ModelVersion:
    """Find or create the ``model_versions`` row that produced this detection.

    ``metrics`` stays **empty** unless a training run measured them: a number here would
    be a benchmark nobody ran (AD-10).
    """
    name = str(describe.get("model") or "unknown")
    version = str(describe.get("version") or "0.0.0")
    existing = (
        await ctx.session.execute(
            select(ModelVersion).where(ModelVersion.name == name, ModelVersion.version == version)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = ModelVersion(
        name=name,
        version=version,
        framework=str(describe.get("framework") or "unknown"),
        task="oil-slick-segmentation",
        metrics=dict(describe.get("metrics") or {}),
        params=dict(describe.get("parameters") or {}),
        training_manifest={},
        input_channels=int(describe.get("input_channels") or 2),
        input_size=int(describe.get("input_size") or DEFAULT_TILE_SIZE),
        normalization=dict(describe.get("normalization") or {}),
        is_active=False,
        notes=str(describe.get("note") or ""),
    )
    ctx.session.add(row)
    await ctx.session.flush()
    return row


async def _resolve_checkpoint(ctx: JobContext, store: Any) -> CheckpointRef | None:
    """Materialise the active trained checkpoint, if one is registered.

    Returns ``None`` when no ``model_versions`` row carries an artifact — which is the
    normal state until a training run has happened, and is exactly what makes
    ``build_segmentation_model`` fall back to the analytical detector.
    """
    if ctx.settings.segmentation_model != "unet":
        return None
    row = (
        await ctx.session.execute(
            select(ModelVersion)
            .where(ModelVersion.is_active, ModelVersion.artifact_uri.isnot(None))
            .order_by(ModelVersion.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not row.artifact_uri:
        return None

    import tempfile
    from pathlib import Path

    payload = await store.get_bytes(row.artifact_uri.split("/", 3)[-1])
    directory = tempfile.mkdtemp(prefix="spilltrace-model-")
    path = Path(directory) / f"{row.name}-{row.version}.pt"
    path.write_bytes(payload)
    return CheckpointRef(
        path=str(path),
        name=row.name,
        version=row.version,
        input_channels=int(row.input_channels or 2),
        input_size=int(row.input_size or DEFAULT_TILE_SIZE),
        normalization=dict(row.normalization or {}),
        params={"metrics": dict(row.metrics or {})},
    )


__all__ = ["detect_slicks", "preprocess_scene"]
