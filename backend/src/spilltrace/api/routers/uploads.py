"""``POST /cases/{case_id}/scenes/upload`` — run the chain on a supplied scene (FR-003).

The catalogue path answers "which Sentinel-1 pass covered this area?".  This endpoint
answers a different question: an operator already holds a measurement file — a research
dataset tile, an archived GRD subset — and wants the ordinary investigation run over it.
Everything downstream is unchanged; this endpoint's only job is to leave the database in
exactly the state ``scene.download`` would have left it in, so the pipeline can start at
``sar.preprocess``.

Two properties of a supplied file are **recorded rather than assumed**, because guessing
either one wrong fails silently rather than loudly:

* **Units.**  Catalogue products carry σ0 as linear power.  Several public SAR training
  sets publish σ0 in **dB**.  Converting a dB raster to dB again rejects every pixel (dB
  values are negative, and the conversion's validity floor is positive), so the scene
  comes back *empty* rather than wrong — the hardest kind of defect to notice in a demo.
* **Georeferencing.**  A tile with no map CRS cannot be placed from its own contents.  It
  is stretched onto the case's area of interest so the chain can run, and that
  substitution is written into the scene's notes instead of being applied quietly.

Provenance is ``REAL``: a Sentinel-1 measurement does not stop being a real observation
because it arrived by upload.  What the platform cannot do is *vouch* for it — it did not
retrieve the file and cannot check its processing history — so every scene created here
carries that sentence in its notes and in the evidence report.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile, status
from geoalchemy2.shape import from_shape, to_shape
from pydantic import BaseModel, Field

from spilltrace.adapters.satellite.bundle import BUNDLE_FILENAME, SceneBand, SceneBundle
from spilltrace.adapters.storage import build_object_store
from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.core.enums import ArtifactType, DataProvenance, DownloadStatus, JobType
from spilltrace.core.errors import ValidationError
from spilltrace.core.geometry import bbox_polygon
from spilltrace.core.raster import write_geotiff
from spilltrace.db.models import Case, CaseScene, EvidenceArtifact, SatelliteScene
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.logging import get_logger
from spilltrace.worker.pipeline import create_pipeline, runnable_jobs
from spilltrace.worker.queue import JobQueue

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])
log = get_logger(__name__)

#: Refuse anything larger before it reaches memory.  A 2048 × 2048 × 2 float32 tile is
#: 32 MB; a decimated GRD subset is a few hundred.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
#: Longest side kept on read, matching ``sar.preprocess``'s own working resolution.
MAX_DIMENSION = 4096
#: A dual-pol SAR scene is two channels; the model takes exactly two.
MAX_BANDS = 2
#: The stages an uploaded scene still needs — the catalogue stages are already satisfied.
UPLOAD_STAGES: tuple[JobType, ...] = (
    JobType.SAR_PREPROCESS,
    JobType.ML_DETECT,
    JobType.ENV_FETCH,
    JobType.DETECT_VERIFY,
    JobType.DRIFT_HINDCAST,
    JobType.AIS_INGEST,
    JobType.AIS_CLEAN,
    JobType.TRAJ_BUILD,
    JobType.CORRELATE,
    JobType.SCORE,
    JobType.REPORT_BUILD,
)

UNVERIFIED_ORIGIN_NOTE = (
    "This measurement file was supplied by an operator. SPILLTRACE did not retrieve it "
    "from a catalogue and cannot verify its origin, acquisition time or processing "
    "history; those fields are as stated at upload."
)

UnitsHint = Literal["auto", "db", "linear"]


class SceneUploadResponse(BaseModel):
    """What the platform read out of the file, in the words the UI shows the operator."""

    scene_id: uuid.UUID
    product_id: str
    polarizations: list[str]
    units: Literal["db", "linear"]
    units_reason: str
    georeferenced: bool
    source_crs: str | None
    bbox: list[float] = Field(description="[west, south, east, north] in EPSG:4326.")
    pixels: list[int] = Field(description="[height, width] of the stored raster.")
    acquired_at: datetime
    size_bytes: int
    notes: list[str]
    pipeline_id: uuid.UUID | None


# --------------------------------------------------------------------------- reading
@dataclass(frozen=True, slots=True)
class _ReadResult:
    """The decoded upload: bands in EPSG:4326 plus everything worth recording."""

    arrays: list[np.ndarray]
    polarizations: list[str]
    bounds: tuple[float, float, float, float]
    georeferenced: bool
    source_crs: str | None
    units: str
    units_reason: str
    source_shape: list[int]
    notes: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    band_descriptions: list[str] = field(default_factory=list)
    source_dtype: str = "float32"
    source_band_count: int = 1
    nodata: float | None = None
    driver: str = "GTiff"
    source_bounds: tuple[float, float, float, float] | None = None


def _decide_units(arrays: list[np.ndarray], hint: UnitsHint) -> tuple[str, str]:
    if hint != "auto":
        return hint, "stated at upload by the operator"
    finite_minimum: float | None = None
    for array in arrays:
        finite = array[np.isfinite(array)]
        if finite.size:
            candidate = float(finite.min())
            finite_minimum = candidate if finite_minimum is None else min(finite_minimum, candidate)
    if finite_minimum is None:
        return "linear", "the file holds no finite value; the catalogue default was assumed"
    if finite_minimum < 0.0:
        return (
            "db",
            f"the file contains negative values (minimum {finite_minimum:.2f}), which "
            "linear σ0 cannot take, so it was read as σ0 in dB",
        )
    return (
        "linear",
        f"every value is non-negative (minimum {finite_minimum:.4g}), consistent with σ0 "
        "in linear power",
    )


def _read_upload(
    payload: bytes, *, aoi_bounds: tuple[float, float, float, float] | None, hint: UnitsHint
) -> _ReadResult:
    """Decode the upload into EPSG:4326 bands.  Runs in a worker thread."""
    from affine import Affine
    from rasterio.enums import Resampling
    from rasterio.io import MemoryFile
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling as WarpResampling
    from rasterio.warp import calculate_default_transform, reproject

    notes: list[str] = []
    try:
        memfile = MemoryFile(payload)
        dataset = memfile.open()
    except Exception as exc:  # rasterio raises a family of driver errors
        raise ValidationError(
            "The uploaded file could not be opened as a GeoTIFF. Upload a single- or "
            f"dual-band .tif measurement file. ({exc})"
        ) from exc

    with memfile, dataset:
        if dataset.count < 1:
            raise ValidationError("The uploaded GeoTIFF contains no raster bands.")
        height, width = int(dataset.height), int(dataset.width)
        decimation = max(1, -(-max(height, width) // MAX_DIMENSION))
        out_height = max(1, height // decimation)
        out_width = max(1, width // decimation)
        source_band_count = int(dataset.count)
        band_count = min(source_band_count, MAX_BANDS)
        arrays = [
            np.asarray(
                dataset.read(
                    index, out_shape=(out_height, out_width), resampling=Resampling.average
                ),
                dtype=np.float32,
            )
            for index in range(1, band_count + 1)
        ]
        source_crs = dataset.crs
        nodata = dataset.nodata
        tags = {str(k): str(v) for k, v in dataset.tags().items()}
        band_descriptions = [d or "" for d in dataset.descriptions]
        source_dtype = str(dataset.dtypes[0])
        driver = str(dataset.driver)
        source_bounds = tuple(float(v) for v in dataset.bounds)
        # The decimated grid has its own transform; the file's is for the full raster.
        src_transform = dataset.transform * Affine.scale(width / out_width, height / out_height)

    if decimation > 1:
        notes.append(
            f"The raster was decimated {decimation}× on read, to {out_height} × {out_width} "
            f"pixels from {height} × {width}, to keep it within the working resolution."
        )
    if source_band_count > MAX_BANDS:
        notes.append(
            f"The file carries {source_band_count} bands; the first {MAX_BANDS} were read as "
            "VV and VH and the rest were ignored."
        )

    polarizations = ["VV", "VH"][:band_count]
    if band_count == 1:
        notes.append(
            "The file carries one band, which was read as VV. Band order is not recorded "
            "in a bare GeoTIFF, so this is an assumption, not a measurement."
        )
    else:
        notes.append(
            "Band 1 was read as VV and band 2 as VH. Band order is not recorded in a bare "
            "GeoTIFF, so this is an assumption, not a measurement."
        )

    source_crs_name = source_crs.to_string() if source_crs else None
    if source_crs is not None:
        dst_transform, dst_width, dst_height = calculate_default_transform(
            source_crs,
            "EPSG:4326",
            out_width,
            out_height,
            *array_bounds(out_height, out_width, src_transform),
        )
        reprojected: list[np.ndarray] = []
        for array in arrays:
            destination = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
            reproject(
                source=array,
                destination=destination,
                src_transform=src_transform,
                src_crs=source_crs,
                src_nodata=nodata,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                dst_nodata=np.nan,
                resampling=WarpResampling.bilinear,
            )
            reprojected.append(destination)
        arrays = reprojected
        bounds = tuple(float(v) for v in array_bounds(dst_height, dst_width, dst_transform))
        georeferenced = True
        if source_crs_name != "EPSG:4326":
            notes.append(
                f"The raster was reprojected from {source_crs_name} to EPSG:4326 so its "
                "detections share one coordinate system with every other layer."
            )
    elif aoi_bounds is None:
        # Inspection before a case exists: there is nothing to place the raster on yet.
        bounds = (0.0, 0.0, 0.0, 0.0)
        georeferenced = False
        notes.append(
            "The file carries no map CRS, so its location cannot be read from it. State "
            "the geographic bounds before running the investigation; any detection's "
            "latitude and longitude will then be a placement, not a measurement."
        )
    else:
        bounds = aoi_bounds
        georeferenced = False
        notes.append(
            "The file carries no map CRS, so it cannot be positioned from its own "
            "contents. It was stretched onto the case's area of interest so the chain "
            "could run: the shape of any detection is real, but its latitude and "
            "longitude are a placement, not a measurement."
        )

    units, units_reason = _decide_units(arrays, hint)
    return _ReadResult(
        arrays=arrays,
        polarizations=polarizations,
        bounds=bounds,
        georeferenced=georeferenced,
        source_crs=source_crs_name,
        units=units,
        units_reason=units_reason,
        notes=notes,
        source_shape=[height, width],
        tags=tags,
        band_descriptions=band_descriptions,
        source_dtype=source_dtype,
        source_band_count=source_band_count,
        nodata=None if nodata is None else float(nodata),
        driver=driver,
        source_bounds=source_bounds,
    )


async def _collect(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(4 * 1024 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise ValidationError(
                f"The upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
            )
        chunks.append(chunk)
    if not total:
        raise ValidationError("The uploaded file is empty.")
    return b"".join(chunks)


# --------------------------------------------------------------------------- ingest
@dataclass(frozen=True, slots=True)
class IngestedScene:
    scene: SatelliteScene
    response: SceneUploadResponse


async def ingest_scene(
    session: Any,
    settings: Any,
    *,
    case: Case,
    user: Any,
    read: _ReadResult,
    filename: str,
    acquired_at: datetime | None,
    run_pipeline: bool,
    extra_notes: list[str] | None = None,
    acquisition_source: str | None = None,
) -> IngestedScene:
    """Store a decoded scene exactly as ``scene.download`` would have, and optionally run.

    Shared by the attach-to-existing-case endpoint and the upload-first case creation, so
    there is one ingest path and nothing downstream can tell them apart.
    """
    from spilltrace.core.scene_metadata import render_quicklook

    filename = (filename or "upload.tif").rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0][:48] or "upload"
    scene_id = uuid.uuid4()
    # The catalogue's uniqueness constraint is on product_id; two uploads of the same
    # file are two observations of the record, not one, so each gets its own identity.
    product_id = f"UPLOAD-{stem}-{scene_id.hex[:8]}"
    observed_at = acquired_at or case.end_time
    footprint = bbox_polygon(*read.bounds)
    height, width = read.arrays[0].shape
    notes = [*read.notes, *(extra_notes or [])]

    store = build_object_store(settings)
    bands: list[SceneBand] = []
    artifacts: list[tuple[str, Any]] = []
    for polarization, array in zip(read.polarizations, read.arrays, strict=True):
        band_filename = f"{polarization.lower()}.tif"
        tiff = await asyncio.to_thread(
            write_geotiff,
            array,
            bounds=read.bounds,
            crs="EPSG:4326",
            band_descriptions=(polarization,),
            tags={"units": read.units, "source_filename": filename},
        )
        stored = await store.put_bytes(
            f"scenes/{scene_id}/{band_filename}", tiff, media_type="image/tiff"
        )
        bands.append(
            SceneBand(
                polarization=polarization,
                filename=band_filename,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                source_url=None,
                is_cog=False,
            )
        )
        artifacts.append((polarization, stored))

    # A display quicklook, stored beside the bands so the map can show the scene itself.
    quicklook_png, stretch = await asyncio.to_thread(render_quicklook, read.arrays[0], read.units)
    quicklook = await store.put_bytes(
        f"scenes/{scene_id}/quicklook.png", quicklook_png, media_type="image/png"
    )

    bundle = SceneBundle(
        product_id=product_id,
        provider="upload",
        bands=tuple(bands),
        data_provenance=DataProvenance.REAL,
        notes=(UNVERIFIED_ORIGIN_NOTE, *notes),
        extra={
            "units": read.units,
            "units_reason": read.units_reason,
            "georeferenced": read.georeferenced,
            "source_crs": read.source_crs,
            "source_filename": filename,
            "source_shape": read.source_shape,
            "uploaded_by": str(user.id),
        },
    )
    manifest = await store.put_bytes(
        f"scenes/{scene_id}/{BUNDLE_FILENAME}",
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True).encode("utf-8"),
        media_type="application/json",
    )

    scene = SatelliteScene(
        id=scene_id,
        product_id=product_id,
        provider="UPLOAD",
        mission="Sentinel-1",
        platform=None,
        product_type="UPLOAD",
        sensor_mode=None,
        acquisition_time=observed_at,
        footprint=from_shape(footprint, srid=4326),
        bbox=from_shape(footprint, srid=4326),
        polarizations=list(read.polarizations),
        orbit_direction=None,
        relative_orbit=None,
        absolute_orbit=None,
        resolution_m=None,
        provider_ref={
            "source_filename": filename,
            "units": read.units,
            "units_reason": read.units_reason,
            "georeferenced": read.georeferenced,
            "source_crs": read.source_crs,
            "source_shape": read.source_shape,
            "acquisition_source": acquisition_source,
            "notes": list(bundle.notes),
            "quicklook_key": f"scenes/{scene_id}/quicklook.png",
            "quicklook_stretch": stretch,
            "quicklook_checksum": quicklook.checksum_sha256,
        },
        size_bytes=bundle.total_bytes,
        checksum_sha256=bundle.manifest_checksum(),
        storage_uri=manifest.uri,
        download_status=DownloadStatus.DOWNLOADED.value,
        data_provenance=DataProvenance.REAL.value,
    )
    session.add(scene)
    await session.flush()

    session.add(
        CaseScene(
            case_id=case.id,
            scene_id=scene.id,
            # Coverage is a catalogue-search notion: it measures how much of the AOI a
            # candidate pass covered.  Nothing measured it here, so it stays unknown
            # rather than being written as a confident 1.0.
            coverage_fraction=None,
            rank=1,
            is_selected=True,
        )
    )
    for polarization, stored in artifacts:
        session.add(
            EvidenceArtifact(
                case_id=case.id,
                artifact_type=ArtifactType.GRD.value,
                label=f"{product_id} {polarization} measurement (uploaded)",
                storage_uri=stored.uri,
                media_type="image/tiff",
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                related_table="satellite_scenes",
                related_id=scene.id,
                artifact_metadata={
                    "polarization": polarization,
                    "units": read.units,
                    "source_filename": filename,
                    "georeferenced": read.georeferenced,
                },
                data_provenance=DataProvenance.REAL.value,
            )
        )

    pipeline_id: uuid.UUID | None = None
    if run_pipeline:
        pipeline_id = await start_upload_pipeline(session, settings, case=case, scene=scene)
    else:
        await session.commit()

    log.info(
        "scene_uploaded",
        case_id=str(case.id),
        scene_id=str(scene.id),
        units=read.units,
        georeferenced=read.georeferenced,
        bands=read.polarizations,
        pipeline_id=str(pipeline_id) if pipeline_id else None,
    )
    response = SceneUploadResponse(
        scene_id=scene.id,
        product_id=product_id,
        polarizations=list(read.polarizations),
        units=read.units,  # type: ignore[arg-type]
        units_reason=read.units_reason,
        georeferenced=read.georeferenced,
        source_crs=read.source_crs,
        bbox=[round(v, 6) for v in read.bounds],
        pixels=[int(height), int(width)],
        acquired_at=observed_at,
        size_bytes=bundle.total_bytes,
        notes=list(bundle.notes),
        pipeline_id=pipeline_id,
    )
    return IngestedScene(scene=scene, response=response)


async def start_upload_pipeline(
    session: Any, settings: Any, *, case: Case, scene: SatelliteScene
) -> uuid.UUID:
    """Create the upload DAG (catalogue stages skipped), commit, and enqueue."""
    pipeline_id, _ = await create_pipeline(
        session,
        case=case,
        mode="REAL",
        stages=list(UPLOAD_STAGES),
        params={"scene_id": str(scene.id)},
    )
    ready = await runnable_jobs(session, pipeline_id)
    await session.commit()
    queue = JobQueue(settings)
    try:
        for job in ready:
            await queue.enqueue(job.id, priority=job.priority)
    finally:
        await queue.close()
    return pipeline_id


# --------------------------------------------------------------------------- endpoint
@router.post(
    "/{case_id}/scenes/upload",
    response_model=SceneUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a supplied SAR measurement file to a case and run the chain on it",
)
async def upload_scene(
    case_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="Single- or dual-band GeoTIFF of σ0.")],
    units: Annotated[UnitsHint, Form()] = "auto",
    acquired_at: Annotated[datetime | None, Form()] = None,
    run_pipeline: Annotated[bool, Form()] = True,
) -> SceneUploadResponse:
    # Same visibility rule as every other case endpoint: an analyst cannot attach
    # evidence to a case they cannot read.
    case = await CaseRepository(session).get_for_user(case_id, user)

    payload = await _collect(file)
    aoi_bounds = tuple(float(v) for v in to_shape(case.aoi).bounds)
    read = await asyncio.to_thread(_read_upload, payload, aoi_bounds=aoi_bounds, hint=units)
    ingested = await ingest_scene(
        session,
        settings,
        case=case,
        user=user,
        read=read,
        filename=file.filename or "upload.tif",
        acquired_at=acquired_at,
        run_pipeline=run_pipeline,
        acquisition_source="stated at upload" if acquired_at else None,
    )
    return ingested.response


__all__ = [
    "UPLOAD_STAGES",
    "IngestedScene",
    "ingest_scene",
    "router",
    "start_upload_pipeline",
]
